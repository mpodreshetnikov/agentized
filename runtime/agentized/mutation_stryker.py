"""Stryker (JS/TS) mutation helpers (AGE-34)."""
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
        return {
            "mutationScoreCovered": (
                data.get("mutationScoreOfCoveredCode")
                or metrics.get("mutationScoreOfCoveredCode")
                or computed_covered
            ),
            "mutationScore": (
                data.get("mutationScore") or metrics.get("mutationScore") or computed_overall
            ),
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
    # mut retained for API symmetry with callers; wrapper reads quality.json itself.
    _ = mut
    run = subprocess.run(["node", str(wrapper)], cwd=root, env=env)
    return run.returncode or 0
