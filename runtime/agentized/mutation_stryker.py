"""Stryker (JS/TS) mutation helpers (AGE-34)."""
from __future__ import annotations

import json
import os
import subprocess
from collections import Counter
from collections.abc import Callable
from pathlib import Path

WriteSummary = Callable[[Path, dict], Path]

_WRAPPER_CANDIDATES = (
    ("scripts", "quality", "run-mutation-js.cjs"),
    ("run-mutation-js.cjs",),
    ("templates", "quality", "run-mutation-js.cjs"),
    ("templates", "quality", "run-mutation-js.cjs.example"),
)
_REPORT_NAMES = ("mutation.json", "mutation-result.json")
_STATUS_MAP = {
    "Killed": "killed",
    "Survived": "survived",
    "NoCoverage": "no_tests",
    "Timeout": "timeout",
}

def find_stryker_wrapper(root: Path) -> Path | None:
    for parts in _WRAPPER_CANDIDATES:
        path = root.joinpath(*parts)
        if path.is_file():
            return path
    return None

def read_stryker_covered(root: Path) -> dict | None:
    for name in _REPORT_NAMES:
        file = root / "reports" / "mutation" / name
        if not file.is_file():
            continue
        data = json.loads(file.read_text())
        files = data.get("files") or {}
        counts: Counter[str] = Counter()
        for entry in files.values():
            for mutant in entry.get("mutants") or []:
                key = _STATUS_MAP.get(str(mutant.get("status")))
                if key is not None:
                    counts[key] += 1
        killed = counts["killed"]
        survived = counts["survived"]
        no_coverage = counts["no_tests"]
        timeout = counts["timeout"]
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
        return {
            "mutationScoreCovered": computed_covered,
            "mutationScore": computed_overall,
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
    """Fail closed unless project/template wrapper exists; wrapper owns the score gate."""
    del mut  # API symmetry; wrapper reads quality.json
    wrapper = find_stryker_wrapper(root)
    if wrapper is None:
        write_summary(
            root,
            {
                "schemaVersion": 1,
                "mode": "incremental",
                "base": base,
                "gate": "hard",
                "tool": "stryker",
                "passed": False,
                "reasons": ["no_stryker_runner"],
                "changedFiles": list(changed),
                "languages": list(languages),
                "minScoreCovered": min_score,
            },
        )
        return 1
    env = {
        **os.environ,
        "MUTATION_BASE": base,
        "STRYKER_BASE": base,
        "MUTATION_MIN_SCORE_COVERED": str(min_score),
    }
    run = subprocess.run(["node", str(wrapper)], cwd=root, env=env)
    return int(run.returncode)
