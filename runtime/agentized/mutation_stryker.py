"""Stryker (JS/TS) mutation gate helpers (AGE-34).

Extracted from mutation.py so dispatch stays thin and this module is
unit-tested to mutationScoreCovered 100% under full-cover globs.
"""
from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path

WriteSummary = Callable[[Path, dict], Path]

_WRAPPER_CANDIDATES = (
    ("scripts", "quality", "run-mutation-js.cjs"),
    ("run-mutation-js.cjs",),
    ("templates", "quality", "run-mutation-js.cjs"),
    ("templates", "quality", "run-mutation-js.cjs.example"),
)


def find_stryker_wrapper(root: Path) -> Path | None:
    for parts in _WRAPPER_CANDIDATES:
        path = root.joinpath(*parts)
        if path.is_file():
            return path
    return None


def read_stryker_covered(root: Path) -> dict | None:
    for name in ("mutation.json", "mutation-result.json"):
        file = root / "reports" / "mutation" / name
        if not file.is_file():
            continue
        data = json.loads(file.read_text(encoding="utf-8"))
        files = data.get("files") or {}
        killed = survived = no_coverage = timeout = 0
        for entry in files.values():
            for mutant in entry.get("mutants") or []:
                status = mutant.get("status")
                if status == "Killed":
                    killed += 1
                elif status == "Survived":
                    survived += 1
                elif status == "NoCoverage":
                    no_coverage += 1
                elif status == "Timeout":
                    timeout += 1
        covered = killed + survived + timeout
        computed_covered = (
            None if covered == 0 else round(10000 * (killed + timeout) / covered) / 100
        )
        overall_den = killed + survived + no_coverage + timeout
        computed_overall = (
            None
            if overall_den == 0
            else round(10000 * (killed + timeout) / overall_den) / 100
        )
        metrics = data.get("metrics") if isinstance(data.get("metrics"), dict) else {}
        from_tool = (
            data.get("mutationScoreOfCoveredCode")
            or metrics.get("mutationScoreOfCoveredCode")
            or computed_covered
        )
        overall = data.get("mutationScore") or metrics.get("mutationScore") or computed_overall
        return {
            "mutationScoreCovered": from_tool,
            "mutationScore": overall,
            "killed": killed,
            "survived": survived,
            "no_tests": no_coverage,
            "timeout": timeout,
            "totalMutants": overall_den,
            "files": list(files.keys()),
            "source": str(file.relative_to(root)),
        }
    return None


def run_stryker_gate(
    root: Path,
    *,
    changed: list[str],
    mut: dict,
    base: str,
    min_score: float,
    languages: list[str],
    write_summary: WriteSummary,
) -> int:
    """Fail closed unless a project/template Stryker wrapper exists."""
    print(
        f"[mutation] stryker hard gate vs {base} ({len(changed)} files, "
        f"langs={','.join(languages)}, min_score_covered={min_score})"
    )
    for path in changed:
        print(f"  {path}")

    wrapper = find_stryker_wrapper(root)
    if wrapper is None:
        summary = write_summary(
            root,
            {
                "schemaVersion": 1,
                "mode": "incremental",
                "base": base,
                "gate": "hard",
                "tool": "stryker",
                "passed": False,
                "reasons": ["no_stryker_runner"],
                "changedFiles": changed,
                "note": (
                    "JS/TS changed but no run-mutation-js.cjs. "
                    "Copy templates/quality/run-mutation-js.cjs.example."
                ),
            },
        )
        print(
            f"[mutation] FAIL: no Stryker runner for changed JS/TS files (see {summary})",
            flush=True,
        )
        return 1

    env = {
        **os.environ,
        "MUTATION_BASE": base,
        "STRYKER_BASE": base,
        "MUTATION_MIN_SCORE_COVERED": str(min_score),
    }
    run = subprocess.run(["node", str(wrapper)], cwd=root, env=env)
    stryker_rc = run.returncode or 0
    if stryker_rc != 0:
        write_summary(
            root,
            {
                "schemaVersion": 1,
                "mode": "incremental",
                "base": base,
                "gate": "hard",
                "tool": "stryker",
                "passed": False,
                "reasons": [f"stryker_exit={stryker_rc}"],
                "changedFiles": changed,
            },
        )
        print(f"[mutation] FAIL: stryker_exit={stryker_rc}", flush=True)
        return stryker_rc

    stats = read_stryker_covered(root)
    reasons: list[str] = []
    if stats is None:
        reasons.append("missing_stryker_json")
        stats = {
            "mutationScoreCovered": None,
            "mutationScore": None,
            "killed": 0,
            "survived": 0,
            "no_tests": 0,
            "timeout": 0,
            "totalMutants": 0,
            "files": [],
        }
    else:
        score = stats["mutationScoreCovered"]
        if score is None:
            reasons.append("no_covered_mutants")
        elif float(score) + 1e-9 < min_score:
            reasons.append(f"score_covered={score}<{min_score}")
        if mut.get("break_on_survived", True) and int(stats.get("survived", 0)) > 0:
            reasons.append(f"survived={stats['survived']}")

    passed = not reasons
    write_summary(
        root,
        {
            "schemaVersion": 1,
            "mode": "incremental",
            "base": base,
            "gate": "hard",
            "scope": "covered_changed_lines",
            "tool": "stryker",
            "languages": languages,
            "minScoreCovered": min_score,
            "changedFiles": changed,
            "passed": passed,
            "reasons": reasons,
            **stats,
        },
    )
    if not passed:
        print(f"[mutation] FAIL: {', '.join(reasons)}", flush=True)
        return 1
    print("[mutation] PASS hard gate (stryker)")
    return 0
