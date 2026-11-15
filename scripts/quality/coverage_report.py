#!/usr/bin/env python3
"""Thin wrapper — prefer: python3 -m agentized.coverage_report or agentized quality check."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))
from agentized.coverage_report import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
