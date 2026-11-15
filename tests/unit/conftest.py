from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_QUALITY = ROOT / "scripts" / "quality"
RUNTIME = ROOT / "runtime"
for path in (RUNTIME, SCRIPT_QUALITY):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
