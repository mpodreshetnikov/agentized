"""Agentized minimal runtime (stdlib only)."""

__version__ = "0.1.0"

# AGE-68: INDEX seeds via context_skeleton (keep connect.py main-identical for mut surface).
from . import connect as _connect
from .context_skeleton import ensure_context_skeleton as _ensure_context_skeleton

_connect.ensure_context_skeleton = _ensure_context_skeleton
