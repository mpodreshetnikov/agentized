"""Hard-by-default lint for weak oracles and mock-call-only tests.

Config: context/quality.json → test_smells (mode: hard|warn).
Does not replace the quality-gates skill rules — it only catches common smells.
"""

from __future__ import annotations

import ast
import fnmatch
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .paths import DEFAULT_CONTEXT, find_repo_root
from .quality import load_quality

_WEAK_COMPARE_OPS = {ast.Is, ast.IsNot, ast.In, ast.NotIn}
_MOCK_ASSERT_ATTRS = {
    "assert_called",
    "assert_called_once",
    "assert_called_with",
    "assert_called_once_with",
    "assert_any_call",
    "assert_has_calls",
    "assert_not_called",
}


def _expand_brace_glob(pattern: str) -> list[str]:
    """Expand a single `{a,b}` brace group (enough for *.{test,spec}.{js,ts})."""
    if "{" not in pattern or "}" not in pattern:
        return [pattern]
    start = pattern.index("{")
    end = pattern.index("}", start)
    body = pattern[start + 1 : end]
    if "," not in body:
        return [pattern]
    prefix, suffix = pattern[:start], pattern[end + 1 :]
    out: list[str] = []
    for part in body.split(","):
        for expanded in _expand_brace_glob(prefix + part + suffix):
            out.append(expanded)
    return out


def _glob_match(rel: str, pattern: str) -> bool:
    """Match repo-relative paths; treat `**` as 'any directories'; expand `{a,b}`."""
    for pat in _expand_brace_glob(pattern):
        if fnmatch.fnmatch(rel, pat):
            return True
        if "**" not in pat:
            continue
        # tests/unit/**/*.py → under tests/unit/ and ends with .py
        if pat.endswith("/**/*.py"):
            prefix = pat[: -len("/**/*.py")]
            if rel.startswith(prefix + "/") and rel.endswith(".py"):
                return True
            continue
        if pat.startswith("**/"):
            rest = pat[3:]
            if fnmatch.fnmatch(rel, rest) or any(
                fnmatch.fnmatch(rel[i + 1 :], rest) for i, ch in enumerate(rel) if ch == "/"
            ):
                return True
            continue
        simplified = pat.replace("/**/", "/").replace("**/", "").replace("**", "*")
        if fnmatch.fnmatch(rel, simplified):
            return True
    return False


_TEST_FILE_SUFFIXES = (".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")


def _iter_test_files(root: Path, globs: list[str]) -> list[Path]:
    out: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in _TEST_FILE_SUFFIXES:
            continue
        rel = path.relative_to(root).as_posix()
        if any(part in {"node_modules", ".git", "mutants", "coverage", "dist", "build"} for part in rel.split("/")):
            continue
        if any(_glob_match(rel, g) for g in globs):
            out.append(path)
    return sorted(out)


def _is_count_membership_bypass(node: ast.Compare) -> bool:
    """``assert expr.count(lit) >= 1`` / ``> 0`` / ``== 0`` ≡ membership checks."""
    if len(node.ops) != 1 or len(node.comparators) != 1:
        return False
    left = node.left
    if not isinstance(left, ast.Call):
        return False
    if not isinstance(left.func, ast.Attribute) or left.func.attr != "count":
        return False
    if not left.args or not isinstance(left.args[0], ast.Constant):
        return False
    right = node.comparators[0]
    if not isinstance(right, ast.Constant) or not isinstance(right.value, int):
        return False
    op = node.ops[0]
    val = right.value
    if isinstance(op, ast.GtE) and val == 1:
        return True
    if isinstance(op, ast.Gt) and val == 0:
        return True
    if isinstance(op, (ast.Eq, ast.NotEq)) and val == 0:
        return True
    return False


def _is_int_bool_truth_bypass(node: ast.Compare) -> bool:
    """``assert int(x) == 1`` / ``bool(x) == True`` ≡ bare truthiness."""
    if len(node.ops) != 1 or len(node.comparators) != 1:
        return False
    left = node.left
    if not isinstance(left, ast.Call) or not isinstance(left.func, ast.Name):
        return False
    name = left.func.id
    if name not in {"int", "bool"}:
        return False
    if not isinstance(node.ops[0], (ast.Eq, ast.NotEq)):
        return False
    right = node.comparators[0]
    if not isinstance(right, ast.Constant):
        return False
    if name == "int" and right.value in (0, 1):
        return True
    if name == "bool" and isinstance(right.value, bool):
        return True
    return False


def _is_weak_assert(node: ast.Assert) -> bool:
    test = node.test
    if isinstance(test, ast.Constant) and isinstance(test.value, bool):
        return True
    if isinstance(test, ast.Name):
        return True
    if (
        isinstance(test, ast.UnaryOp)
        and isinstance(test.op, ast.Not)
        and isinstance(test.operand, ast.Name)
    ):
        return True
    if isinstance(test, ast.Compare) and len(test.ops) == 1:
        if _is_count_membership_bypass(test) or _is_int_bool_truth_bypass(test):
            return True
        op = test.ops[0]
        if type(op) in _WEAK_COMPARE_OPS:
            return True
        if isinstance(op, (ast.Eq, ast.NotEq)) and isinstance(test.comparators[0], ast.Constant):
            val = test.comparators[0].value
            if val is None or isinstance(val, bool):
                return True
    return False


def _is_mock_assert_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
        return False
    func = node.value.func
    if isinstance(func, ast.Attribute) and func.attr in _MOCK_ASSERT_ATTRS:
        return True
    return False


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _call_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


_JS_WEAK_PATTERNS = (
    (".toBeTruthy(", "weak_primary_oracle"),
    (".toBeFalsy(", "weak_primary_oracle"),
    (".toBeDefined(", "weak_primary_oracle"),
    (".toBeUndefined(", "weak_primary_oracle"),
    ("assert.ok(", "weak_primary_oracle"),
    ("assert.equal(true", "weak_primary_oracle"),
)


def _scan_js_ts_file(path: Path, root: Path) -> list[dict]:
    """Lightweight test-smell lint for JS/TS tests (Orbit weak-oracle patterns)."""
    rel = path.relative_to(root).as_posix()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [{"file": rel, "line": 1, "kind": "read_error", "detail": str(exc)}]
    findings: list[dict] = []
    for i, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("*"):
            continue
        for needle, kind in _JS_WEAK_PATTERNS:
            if needle in line:
                findings.append(
                    {
                        "file": rel,
                        "line": i,
                        "kind": kind,
                        "detail": f"JS/TS weak oracle ({needle.strip('(')} ) — prefer exact value asserts",
                    }
                )
                break
    return findings


def _scan_file(path: Path, root: Path) -> list[dict]:
    rel = path.relative_to(root).as_posix()
    if path.suffix.lower() in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}:
        return _scan_js_ts_file(path, root)
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
    except SyntaxError as exc:
        return [{"file": rel, "line": exc.lineno or 1, "kind": "syntax_error", "detail": str(exc)}]

    findings: list[dict] = []
    for fn in [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        if not fn.name.startswith("test"):
            continue
        body_nodes = list(ast.walk(fn))
        asserts = [n for n in body_nodes if isinstance(n, ast.Assert)]
        mock_asserts = [n for n in fn.body if _is_mock_assert_call(n)]
        # Also walk nested for mock asserts
        mock_asserts_deep = [
            n
            for n in body_nodes
            if isinstance(n, ast.Expr)
            and isinstance(n.value, ast.Call)
            and isinstance(n.value.func, ast.Attribute)
            and n.value.func.attr in _MOCK_ASSERT_ATTRS
        ]

        if asserts and all(_is_weak_assert(a) for a in asserts) and not mock_asserts_deep:
            findings.append(
                {
                    "file": rel,
                    "line": fn.lineno,
                    "kind": "weak_primary_oracle",
                    "detail": f"{fn.name}: only truthy/defined/membership asserts",
                }
            )

        if mock_asserts_deep and not asserts:
            findings.append(
                {
                    "file": rel,
                    "line": fn.lineno,
                    "kind": "mock_call_only",
                    "detail": f"{fn.name}: mock call asserts without behavior oracle",
                }
            )

        # patch("module.under.test...") as decorator — skill forbids mocking MUT
        for dec in fn.decorator_list:
            call = dec if isinstance(dec, ast.Call) else None
            if call is None:
                continue
            name = _call_name(call.func)
            if "patch" not in name:
                continue
            if (
                call.args
                and isinstance(call.args[0], ast.Constant)
                and isinstance(call.args[0].value, str)
            ):
                target = call.args[0].value
                findings.append(
                    {
                        "file": rel,
                        "line": fn.lineno,
                        "kind": "patch_decorator",
                        "detail": f"{fn.name}: @patch({target!r}) — prefer fakes of collaborators, not MUT",
                    }
                )

    return findings


def run_test_smells(
    root: Path | None = None,
    *,
    context: str = DEFAULT_CONTEXT,
) -> int:
    root = root or find_repo_root()
    cfg = load_quality(root, context)
    section = cfg.get("test_smells") or {}
    if not section.get("enabled", False):
        print("[test-smells] disabled — skip")
        return 0

    mode = str(section.get("mode") or "hard").lower()
    globs = list(
        section.get("include_globs")
        or ["tests/unit/**/*.py", "tests/quality/**/*.py", "tests/**/test_*.py"]
    )
    files = _iter_test_files(root, globs)
    findings: list[dict] = []
    for path in files:
        findings.extend(_scan_file(path, root))

    out_dir = root / "reports" / "test-smells"
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schemaVersion": 1,
        "mode": mode,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "filesScanned": len(files),
        "findings": findings,
        "passed": True if mode == "warn" else not findings,
    }
    (out_dir / "test-smells-summary.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )

    if findings:
        print(f"[test-smells] {len(findings)} finding(s) (mode={mode})")
        for item in findings[:40]:
            print(f"  {item['file']}:{item['line']} {item['kind']}: {item['detail']}")
        if len(findings) > 40:
            print(f"  … +{len(findings) - 40} more")
    else:
        print(f"[test-smells] PASS (0 findings, {len(files)} files)")

    if mode == "warn":
        print("[test-smells] warn mode — not failing the gate")
        return 0
    return 0 if not findings else 1


def main(argv: list[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    context = args[args.index("--context") + 1] if "--context" in args else DEFAULT_CONTEXT
    return run_test_smells(find_repo_root(), context=context)


if __name__ == "__main__":
    raise SystemExit(main())
