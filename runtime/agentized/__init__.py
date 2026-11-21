"""Agentized minimal runtime (stdlib only)."""

__version__ = "0.1.0"

# AGE-52: rebind connect.install_* / connect.connect to merge-safe hooks wiring.
from . import connect_hooks as _connect_hooks  # noqa: E402,F401
