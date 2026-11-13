#!/usr/bin/env python3
"""Combine per-module coverage into coverage/combined-* (Orbit coverage-report mechanism)."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "runtime"))

from agentized.paths import DEFAULT_CONTEXT, find_repo_root  # noqa: E402
from agentized.quality import load_quality, module_thresholds  # noqa: E402


def _pct(hit: int, found: int) -> float:
    return 100.0 if not found else round((hit / found) * 100.0, 2)


def _zero() -> dict:
    return {
        "lines_hit": 0,
        "lines_found": 0,
        "lines_pct": 100.0,
        "branches_hit": 0,
        "branches_found": 0,
        "branches_pct": 100.0,
    }


def _rel(path: str) -> str:
    p = path.replace("\\", "/")
    try:
        return str(Path(p).resolve().relative_to(ROOT.resolve())).replace("\\", "/")
    except Exception:
        root_s = str(ROOT.resolve()).replace("\\", "/")
        return p[len(root_s) + 1 :] if p.startswith(root_s + "/") else p


def parse_lcov(path: Path) -> dict:
    if not path.exists():
        return {"totals": _zero(), "records": []}
    records: list[dict] = []
    current: dict | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("SF:"):
            if current:
                records.append(current)
            current = {"file": _rel(line[3:]), "LH": 0, "LF": 0, "BRH": 0, "BRF": 0}
        elif current is None:
            continue
        elif line.startswith("LH:"):
            current["LH"] = int(line[3:] or 0)
        elif line.startswith("LF:"):
            current["LF"] = int(line[3:] or 0)
        elif line.startswith("BRH:"):
            current["BRH"] = int(line[4:] or 0)
        elif line.startswith("BRF:"):
            current["BRF"] = int(line[4:] or 0)
        elif line == "end_of_record":
            records.append(current)
            current = None
    if current:
        records.append(current)
    merged = _merge(records)
    return {"totals": _from_records(merged), "records": merged}


def parse_coverage_json(path: Path) -> dict:
    if not path.exists():
        return _zero()
    data = json.loads(path.read_text(encoding="utf-8"))
    total = data.get("totals") or data.get("total") or {}
    if "num_statements" in total or "covered_lines" in total:
        lh, lf = int(total.get("covered_lines") or 0), int(total.get("num_statements") or 0)
        bh, bf = int(total.get("covered_branches") or 0), int(total.get("num_branches") or 0)
        return {
            "lines_hit": lh, "lines_found": lf, "lines_pct": _pct(lh, lf),
            "branches_hit": bh, "branches_found": bf, "branches_pct": _pct(bh, bf),
        }
    lines, branches = total.get("lines") or {}, total.get("branches") or {}
    lh = int(lines.get("covered_lines") or lines.get("covered") or 0)
    lf = int(lines.get("num_statements") or lines.get("total") or 0)
    bh = int(branches.get("covered_branches") or branches.get("covered") or 0)
    bf = int(branches.get("num_branches") or branches.get("total") or 0)
    return {
        "lines_hit": lh, "lines_found": lf, "lines_pct": float(lines.get("pct") or _pct(lh, lf)),
        "branches_hit": bh, "branches_found": bf,
        "branches_pct": float(branches.get("pct") or _pct(bh, bf)),
    }


def _from_records(records: list[dict]) -> dict:
    lh = sum(r.get("LH", 0) for r in records)
    lf = sum(r.get("LF", 0) for r in records)
    bh = sum(r.get("BRH", 0) for r in records)
    bf = sum(r.get("BRF", 0) for r in records)
    return {
        "lines_hit": lh, "lines_found": lf, "lines_pct": _pct(lh, lf),
        "branches_hit": bh, "branches_found": bf, "branches_pct": _pct(bh, bf),
    }


def _merge(records: list[dict]) -> list[dict]:
    by_file: dict[str, dict] = {}
    for record in records:
        existing = by_file.get(record["file"])
        if not existing:
            by_file[record["file"]] = dict(record)
            continue
        for key in ("LH", "LF", "BRH", "BRF"):
            existing[key] = max(int(existing.get(key) or 0), int(record.get(key) or 0))
    return list(by_file.values())


def build_report(root: Path, context_rel: str = DEFAULT_CONTEXT) -> dict:
    cfg = load_quality(root, context_rel)
    modules_out: dict[str, dict] = {}
    combined_records: list[dict] = []
    for module in cfg.get("modules") or []:
        mid = module.get("id") or "module"
        lcov = parse_lcov(root / module["coverage_lcov"]) if module.get("coverage_lcov") else {
            "totals": _zero(), "records": []
        }
        json_totals = (
            parse_coverage_json(root / module["coverage_json"])
            if module.get("coverage_json") else None
        )
        totals = json_totals if json_totals and json_totals["lines_found"] else lcov["totals"]
        line_min, branch_min = module_thresholds(cfg, module)
        modules_out[mid] = {
            "totals": totals,
            "thresholds": {"lines": line_min, "branches": branch_min},
            "pass": totals["lines_pct"] + 1e-9 >= line_min and totals["branches_pct"] + 1e-9 >= branch_min,
            "files": len(lcov["records"]),
        }
        combined_records.extend(lcov["records"])
    combined = _from_records(_merge(combined_records)) if combined_records else (
        next(iter(modules_out.values()))["totals"] if modules_out else _zero()
    )
    # Prefer JSON totals for combined when single module (more accurate branch counts)
    if len(modules_out) == 1:
        combined = next(iter(modules_out.values()))["totals"]
    g_lines = float((cfg.get("coverage") or {}).get("lines") or 80)
    g_branches = float((cfg.get("coverage") or {}).get("branches") or 80)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "context": context_rel,
        "coverage_thresholds": {"lines": g_lines, "branches": g_branches},
        "modules": modules_out,
        "combined": combined,
        "combined_pass": combined["lines_pct"] + 1e-9 >= g_lines
        and combined["branches_pct"] + 1e-9 >= g_branches,
    }


def write_report(root: Path, summary: dict) -> tuple[Path, Path]:
    out_dir = root / "coverage"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path, md_path = out_dir / "combined-summary.json", out_dir / "combined-report.md"
    json_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Coverage Report", "", f"Generated: {summary['generated_at']}", "",
        "## Combined", "",
        f"- lines: {summary['combined']['lines_pct']}% "
        f"({summary['combined']['lines_hit']}/{summary['combined']['lines_found']})",
        f"- branches: {summary['combined']['branches_pct']}% "
        f"({summary['combined']['branches_hit']}/{summary['combined']['branches_found']})",
        f"- pass: {summary['combined_pass']} "
        f"(need ≥{summary['coverage_thresholds']['lines']}% / "
        f"≥{summary['coverage_thresholds']['branches']}%)",
        "", "## Modules", "",
    ]
    for mid, mod in summary["modules"].items():
        t, th = mod["totals"], mod["thresholds"]
        lines.append(
            f"- {mid}: lines {t['lines_pct']}% (≥{th['lines']}), "
            f"branches {t['branches_pct']}% (≥{th['branches']}), pass={mod['pass']}"
        )
    lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def main(argv: list[str] | None = None) -> int:
    root = find_repo_root()
    args = list(argv or sys.argv[1:])
    context = args[args.index("--context") + 1] if "--context" in args else DEFAULT_CONTEXT
    summary = build_report(root, context)
    json_path, md_path = write_report(root, summary)
    print(f"[coverage-report] {json_path.relative_to(root)}")
    print(f"[coverage-report] {md_path.relative_to(root)}")
    print(
        f"[coverage-report] combined lines={summary['combined']['lines_pct']}% "
        f"branches={summary['combined']['branches_pct']}% pass={summary['combined_pass']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
