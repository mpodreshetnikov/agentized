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
    """Fail closed: real wrapper required; Python re-checks covered score."""
    del mut
    wrapper = find_stryker_wrapper(root)
    base_payload = {
        "schemaVersion": 1,
        "mode": "incremental",
        "base": base,
        "gate": "hard",
        "tool": "stryker",
        "changedFiles": list(changed),
        "languages": list(languages),
        "minScoreCovered": min_score,
    }
    if wrapper is None:
        write_summary(root, {**base_payload, "passed": False, "reasons": ["no_stryker_runner"]})
        return 1
    env = {
        **os.environ,
        "MUTATION_BASE": base,
        "STRYKER_BASE": base,
        "MUTATION_MIN_SCORE_COVERED": str(min_score),
    }
    run = subprocess.run(["node", str(wrapper)], cwd=root, env=env)
    if int(run.returncode) != 0:
        return int(run.returncode)
    stats = read_stryker_covered(root)
    if stats is None:
        write_summary(root, {**base_payload, "passed": False, "reasons": ["no_stryker_report"]})
        return 1
    score = stats["mutationScoreCovered"]
    survived = stats["survived"]
    reasons: list[str] = []
    if score is None or float(score) < min_score:
        reasons.append(f"score_covered={score}<{min_score}")
    if survived != 0:
        reasons.append(f"survived={survived}")
    passed = reasons == []
    write_summary(
        root,
        {
            **base_payload,
            "passed": passed,
            "reasons": reasons,
            "stats": stats,
        },
    )
    return 0 if passed else 1
