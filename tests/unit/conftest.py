from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Mutmut copies tests into mutants/; prefer checkout root, fall back to runtime/.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if not (ROOT / "agentized").exists():
    runtime = ROOT / "runtime"
    if runtime.is_dir() and str(runtime) not in sys.path:
        sys.path.insert(0, str(runtime))
script_quality = ROOT / "scripts" / "quality"
if script_quality.is_dir() and str(script_quality) not in sys.path:
    sys.path.append(str(script_quality))
