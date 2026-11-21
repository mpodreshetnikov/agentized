"""Incremental mutation hard gate on covered changed lines (mutmut).

Required gate (Orbit Lead + Maxim intent): fail the build when the covered
mutation score on changed sources is below context/quality.json threshold.
Self-contained under runtime/agentized for connected foreign repos.
"""

from __future__ import annotations

import ast
import fnmatch
import re
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .paths import DEFAULT_CONTEXT, find_repo_root
from .quality import load_quality

DURABLE_SETUP = """[mutmut]
# Top-level `agentized` symlink → runtime/agentized so trampoline keys match imports.
source_paths = agentized
mutate_only_covered_lines = false
use_git_change_detection = false
# Equivalent lexemes (Python treats these the same) — do not count as survivors.
ignore_lexemes =
  utf-8
  UTF-8
also_copy =
  tests/
  context/
  pyproject.toml
  setup.cfg
"""


def _test_selection_for(only_mutate: list[str], root: Path) -> list[str]:
    """Map mutated modules to unit tests (newline-separated multi-file selection).

    ``agentized/foo.py`` → ``tests/unit/test_foo.py`` and ``tests/unit/test_foo_*.py``.
    Falls back to ``tests/unit`` when no matching test file exists.
    """
    unit = root / "tests" / "unit"
    selected: list[str] = []
    for item in only_mutate:
        stem = Path(item).stem
        exact = unit / f"test_{stem}.py"
        if exact.is_file():
            selected.append(f"tests/unit/test_{stem}.py")
        if unit.is_dir():
            for path in sorted(unit.glob(f"test_{stem}_*.py")):
                selected.append(f"tests/unit/{path.name}")
    return list(dict.fromkeys(selected)) or ["tests/unit"]


def _ensure_agentized_link(root: Path) -> bool:
    link = root / "agentized"
    if link.exists() or link.is_symlink():
        return False
    link.symlink_to(Path("runtime") / "agentized", target_is_directory=True)
    return True


def _changed_py_files(root: Path, base_ref: str, prefixes: list[str]) -> list[str]:
    proc = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACMR", f"{base_ref}...HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        proc = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=ACMR", base_ref],
            cwd=root,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            print(proc.stderr or "git diff failed", file=sys.stderr)
            raise SystemExit(proc.returncode or 1)
    out = []
    for name in proc.stdout.splitlines():
        name = name.strip().replace("\\", "/")
        if not name.endswith(".py"):
            continue
        if name.startswith("tests/") or "/test" in name or name.endswith("_test.py"):
            continue
        if any(name == p or name.startswith(p.rstrip("/") + "/") for p in prefixes):
            out.append(name)
    return sorted(set(out))


def _write_summary(root: Path, payload: dict) -> Path:
    out = root / "reports" / "mutation"
    out.mkdir(parents=True, exist_ok=True)
    path = out / "mutation-summary.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _write_setup(root: Path, only_mutate: list[str]) -> None:
    lines = [DURABLE_SETUP.rstrip(), ""]
    tests = _test_selection_for(only_mutate, root)
    lines.append("pytest_add_cli_args_test_selection =")
    lines.extend(f"  {t}" for t in tests)
    lines.append("")
    if only_mutate:
        lines.append("only_mutate =")
        lines.extend(f"  {item}" for item in only_mutate)
        lines.append("")
    (root / "setup.cfg").write_text("\n".join(lines), encoding="utf-8")


# pragma: no mutate start
def _diff_added_lines(root: Path, base_ref: str, rel: str) -> set[int]:
    proc = None
    for spec in (f"{base_ref}...HEAD", base_ref):
        proc = subprocess.run(
            ["git", "diff", "-U0", spec, "--", rel],
            cwd=root, capture_output=True, text=True,
        )
        if getattr(proc, "returncode", 1) == 0 or spec == base_ref:
            break
    out: set[int] = set()
    for row in (getattr(proc, "stdout", None) or "").splitlines():
        m = re.search(r"\+(\d+)(?:,(\d+))?", row) if row.startswith("@@") else None
        if not m:
            continue
        start, n = int(m.group(1)), int(m.group(2) or "1")
        if n > 0:
            out.update(range(start, start + n))
    return out

def _touched_functions(source: Path, changed_lines: set[int]) -> set[str] | None:
    if not changed_lines or not source.is_file():
        return set()
    try:
        tree = ast.parse(source.read_text(encoding="utf-8"))
    except SyntaxError:
        return None
    ranges: list[tuple[str, int, int]] = []
    skip = (
        ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef,
        ast.ClassDef, ast.Assign, ast.AnnAssign, ast.Expr,
    )
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            ranges.append((node.name, node.lineno, node.end_lineno or node.lineno))
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    ranges.append((child.name, child.lineno, child.end_lineno or child.lineno))
    touched: set[str] = set()
    for lineno in changed_lines:
        name = next((n for n, a, b in ranges if a <= lineno <= b), None)
        if name:
            touched.add(name)
            continue
        for node in tree.body:
            end = getattr(node, "end_lineno", None) or node.lineno
            if node.lineno <= lineno <= end:
                if isinstance(node, skip):
                    break
                return None
    return touched

def _mutant_function_name(key: str) -> str | None:
    m = re.search(r"\.x_([A-Za-z_][\w]*)__mutmut_(?:\d+|orig)\b", key)
    return m.group(1) if m else None

def _function_start_lines(source: Path) -> dict[str, int]:
    try:
        tree = ast.parse(source.read_text(encoding="utf-8"))
    except (SyntaxError, OSError):
        return {}
    out: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[node.name] = node.lineno
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out[child.name] = child.lineno
    return out

def _trampoline_func_bodies(trampoline: Path, fn: str) -> dict[str, list[str]]:
    if not trampoline.is_file():
        return {}
    prefix = f"def x_{fn}__mutmut_"
    rows = trampoline.read_text(encoding="utf-8").splitlines()
    starts = [i for i, row in enumerate(rows) if row.startswith(prefix)]
    if not starts:
        return {}
    starts.append(len(rows))
    bodies: dict[str, list[str]] = {}
    for a, b in zip(starts, starts[1:]):
        name = rows[a][len("def ") :].split("(", 1)[0]
        end = b
        for j in range(a + 1, b):
            if rows[j].startswith("def ") and not rows[j].startswith(prefix):
                end = j
                break
        bodies[name] = rows[a:end]
    return bodies

def _mutant_hits_changed_lines(
    trampoline: Path, fn: str, mutant_key: str, func_lineno: int, changed_lines: set[int]
) -> bool:
    short = mutant_key.rsplit(".", 1)[-1]
    bodies = _trampoline_func_bodies(trampoline, fn)
    orig, mut = bodies.get(f"x_{fn}__mutmut_orig"), bodies.get(short)
    if not orig or not mut:
        return True
    for i, (o, m) in enumerate(zip(orig, mut)):
        if o != m and (func_lineno + i) in changed_lines:
            return True
    if len(mut) != len(orig):
        return any(func_lineno <= ln <= func_lineno + max(len(orig), len(mut)) for ln in changed_lines)
    return False

def _score_changed(
    root: Path,
    *,
    base_ref: str | None,
    changed_files: list[str] | None,
    context: str,
) -> dict:
    killed = survived = no_tests = timeout = other = 0
    files: list[str] = []
    mutants_dir = root / "mutants"
    allow: dict[str, set[str] | None] = {}
    changed_by: dict[str, set[int]] = {}
    starts_by: dict[str, dict[str, int]] = {}
    if base_ref is None and changed_files is None and (root / context / "quality.json").is_file():
        try:
            cfg = load_quality(root, context)
            mut = cfg.get("mutation") or {}
            base_ref = os.environ.get("MUTATION_BASE") or mut.get("base_ref") or "origin/main"
            prefixes = [
                str(src).replace("\\", "/")
                for module in cfg.get("modules") or []
                for src in module.get("source") or []
            ] or ["runtime/agentized"]
            changed_files = _changed_py_files(root, base_ref, prefixes)
            globs = list(mut.get("include_globs") or [])
            if globs:
                changed_files = [p for p in changed_files if any(fnmatch.fnmatch(p, g) for g in globs)]
        except Exception:
            base_ref = None
            changed_files = None
    if base_ref and changed_files:
        for rel in changed_files:
            key = rel.replace("\\", "/")
            lines = _diff_added_lines(root, base_ref, rel)
            allow[key] = _touched_functions(root / rel, lines)
            changed_by[key] = lines
            starts_by[key] = _function_start_lines(root / rel)
            if key.startswith("runtime/agentized/"):
                aka = "agentized/" + key[len("runtime/agentized/") :]
                allow[aka] = allow[key]
                changed_by[aka] = lines
                starts_by[aka] = starts_by[key]
    for meta in mutants_dir.rglob("*.meta") if mutants_dir.exists() else []:
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
        except Exception:
            continue
        exit_map = data.get("exit_code_by_key") or {}
        if not exit_map:
            continue
        rel_meta = str(meta.relative_to(mutants_dir)).replace("\\", "/")
        src_key = rel_meta[: -len(".meta")] if rel_meta.endswith(".meta") else rel_meta
        if allow and src_key not in allow:
            continue
        allowed = allow.get(src_key)
        changed_lines = changed_by.get(src_key) or set()
        starts = starts_by.get(src_key) or {}
        trampoline = meta.with_suffix("")
        files.append(rel_meta)
        for key, code in exit_map.items():
            if allowed is not None:
                fn = _mutant_function_name(key)
                if fn is None or fn not in allowed:
                    continue
                if changed_lines and fn in starts:
                    if not _mutant_hits_changed_lines(trampoline, fn, key, starts[fn], changed_lines):
                        continue
            if code in (1, 3):
                killed += 1
            elif code == 0:
                survived += 1
            elif code in (5, 33):
                no_tests += 1
            elif code in (36, 24, 152, 255, -24):
                timeout += 1
            else:
                other += 1
    total = killed + survived + no_tests + timeout
    covered = killed + survived + timeout
    return {
        "killed": killed, "survived": survived, "no_tests": no_tests, "timeout": timeout,
        "other": other, "totalMutants": total, "files": files,
        "mutationScore": round(10000 * (killed + timeout) / total) / 100 if total else None,
        "mutationScoreCovered": (
            round(10000 * (killed + timeout) / covered) / 100 if covered else None
        ),
    }
# pragma: no mutate end


def _collect_stats(  # pragma: no mutate
    root: Path,
    *,
    base_ref: str | None = None,
    changed_files: list[str] | None = None,
    context: str = DEFAULT_CONTEXT,
) -> dict:
    return _score_changed(
        root, base_ref=base_ref, changed_files=changed_files, context=context
    )


def run_mutation(
    root: Path | None = None,
    *,
    context: str = DEFAULT_CONTEXT,
) -> int:
    root = root or find_repo_root()
    os.chdir(root)
    cfg = load_quality(root, context)
    mut = cfg.get("mutation") or {}
    if not mut.get("enabled", True):
        print("[mutation] disabled — skip")
        return 0

    base = os.environ.get("MUTATION_BASE") or mut.get("base_ref") or "origin/main"
    min_score = float(mut.get("min_score_covered", 100))
    prefixes = [
        str(src).replace("\\", "/")
        for module in cfg.get("modules") or []
        for src in module.get("source") or []
    ] or ["runtime/agentized"]
    changed = _changed_py_files(root, base, prefixes)
    include_globs = list(mut.get("include_globs") or [])
    if include_globs:
        changed = [
            path for path in changed if any(fnmatch.fnmatch(path, pat) for pat in include_globs)
        ]
    if not changed:
        path = _write_summary(
            root,
            {
                "schemaVersion": 1,
                "mode": "incremental-skip",
                "base": base,
                "generatedAt": datetime.now(timezone.utc).isoformat(),
                "mutationScore": None,
                "mutationScoreCovered": None,
                "survived": 0,
                "killed": 0,
                "no_tests": 0,
                "files": [],
                "gate": "hard",
                "passed": True,
                "note": f"No mutable source files changed vs {base}",
            },
        )
        print(f"[mutation] skip vs {base}; wrote {path.relative_to(root)}")
        return 0

    print(f"[mutation] hard gate vs {base} ({len(changed)} files, min_score_covered={min_score})")
    for f in changed:
        print(f"  {f}")

    unit_tests = root / "tests" / "unit"
    if unit_tests.is_dir():
        pre = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/unit", "-q", "--tb=no"],
            cwd=root,
        )
        if pre.returncode != 0:
            print("[mutation] unit tests failed before mutation", file=sys.stderr)
            return pre.returncode

    only = [
        ("agentized/" + p[len("runtime/agentized/") :]) if p.startswith("runtime/agentized/") else p
        for p in changed
    ]
    setup = root / "setup.cfg"
    backup = setup.read_text(encoding="utf-8") if setup.exists() else DURABLE_SETUP
    created_link = _ensure_agentized_link(root)
    _write_setup(root, only)
    # Wipe prior mutants so a failed current run cannot PASS on cached results.
    mutants_dir = root / "mutants"
    if mutants_dir.exists():
        shutil.rmtree(mutants_dir, ignore_errors=True)
    env = {**os.environ, "PYTHONPATH": str(root)}
    mutmut_rc = 0
    try:
        run = subprocess.run([sys.executable, "-m", "mutmut", "run"], cwd=root, env=env)
        mutmut_rc = run.returncode or 0
        if mutmut_rc != 0:
            print(f"[mutation] mutmut exited {mutmut_rc}", file=sys.stderr)
    finally:
        setup.write_text(backup if backup.strip() else DURABLE_SETUP, encoding="utf-8")
        link = root / "agentized"
        if created_link and link.is_symlink():
            link.unlink(missing_ok=True)

    stats = _collect_stats(root)
    reasons: list[str] = []
    # Always fail closed on runner failure (Codex P1) — never trust cached/partial stats.
    if mutmut_rc != 0:
        reasons.append(f"mutmut_exit={mutmut_rc}")
    if mut.get("break_on_no_tests", True) and stats["no_tests"] > 0:
        reasons.append(f"no_tests={stats['no_tests']}")
    score = stats["mutationScoreCovered"]
    if score is None and changed and stats["totalMutants"] == 0 and mutmut_rc == 0:
        reasons.append("no_mutants_evaluated")
    if score is not None and score + 1e-9 < min_score:
        reasons.append(f"score_covered={score}<{min_score}")
    if mut.get("break_on_survived") and stats["survived"] > 0:
        reasons.append(f"survived={stats['survived']}")

    passed = not reasons
    path = _write_summary(
        root,
        {
            "schemaVersion": 1,
            "mode": "incremental",
            "base": base,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "gate": "hard",
            "scope": "covered_changed_lines",
            "tool": "mutmut",
            "minScoreCovered": min_score,
            "changedFiles": changed,
            "passed": passed,
            "reasons": reasons,
            "mutmutExit": mutmut_rc,
            **stats,
        },
    )
    print(
        f"[mutation] score={stats['mutationScore']} covered={stats['mutationScoreCovered']} "
        f"killed={stats['killed']} survived={stats['survived']} no_tests={stats['no_tests']}"
    )
    print(f"[mutation] wrote {path.relative_to(root)}")
    if not passed:
        print(f"[mutation] FAIL: {', '.join(reasons)}", file=sys.stderr)
        return 1
    print("[mutation] PASS hard gate")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    context = args[args.index("--context") + 1] if "--context" in args else DEFAULT_CONTEXT
    return run_mutation(find_repo_root(), context=context)


if __name__ == "__main__":
    raise SystemExit(main())
