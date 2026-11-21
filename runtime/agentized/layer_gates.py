"""Detect e2e and DB test layers (AGE-31a). Gate evaluation lands in AGE-31b."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

_SKIP_DIR_NAMES = {
    ".git",
    "node_modules",
    "mutants",
    "coverage",
    "reports",
    ".venv",
    "venv",
    "dist",
    "build",
    "__pycache__",
    ".tox",
    ".next",
    ".turbo",
    "vendor",
}
_AGENTIZED_SKIP_REL_PREFIXES = ("templates/", "tests/fixtures/")
E2E_CONFIG_NAMES = (
    "playwright.config.ts",
    "playwright.config.js",
    "playwright.config.mjs",
    "playwright.config.cjs",
    "cypress.config.ts",
    "cypress.config.js",
    "cypress.config.mjs",
)
E2E_PKG_DEPS = ("@playwright/test", "playwright", "cypress")
E2E_DIR_NAMES = ("e2e", "playwright")
DB_DIR_SUFFIXES = (
    "/migrations",
    "/db/migrations",
    "/supabase/migrations",
    "/prisma/migrations",
    "/alembic/versions",
    "/flyway/sql",
    "/pgtap",
    "/db/tests",
    "/tests/db",
    "/tests/sql",
)
DB_DIR_ROOT_NAMES = (
    "migrations",
    "db/migrations",
    "supabase/migrations",
    "prisma/migrations",
    "alembic/versions",
    "flyway/sql",
    "liquibase",
    "pgtap",
    "db/tests",
    "tests/db",
    "tests/sql",
)
DB_FILE_MARKERS = ("alembic.ini", "schema.sql")
ORM_JS_DEPS = ("prisma", "@prisma/client", "drizzle-orm", "typeorm", "sequelize", "knex")
ORM_PY_DEPS = ("sqlalchemy", "django", "alembic")
PLACEHOLDER_NAMES = {".gitkeep", ".keep"}
_JSON_ENCODING = "utf-8"


def _iter_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIR_NAMES)
        base = Path(dirpath)
        out.extend(base / name for name in sorted(filenames))
    return sorted(out)


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def is_agentized_repo(root: Path) -> bool:
    has_pkg = (root / "runtime" / "agentized").is_dir() or (root / "agentized").is_dir()
    return has_pkg and (root / "templates" / "quality").is_dir()


def skip_rel_prefixes(root: Path, section: dict[str, Any] | None = None) -> tuple[str, ...]:
    section = section or {}
    configured = section.get("skip_rel_prefixes")
    if isinstance(configured, list):
        return tuple(str(p) for p in configured)
    return _AGENTIZED_SKIP_REL_PREFIXES if is_agentized_repo(root) else ()


def _is_skipped_rel(rel: str, prefixes: tuple[str, ...]) -> bool:
    rel = rel.replace("\\", "/")
    return any(rel == p.rstrip("/") or rel.startswith(p) for p in prefixes)


def _read_package_deps(path: Path) -> set[str]:
    try:
        data = json.loads(path.read_bytes().decode(_JSON_ENCODING))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return set()
    if not isinstance(data, dict):
        return set()
    names: set[str] = set()
    for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        block = data.get(key)
        if isinstance(block, dict):
            names.update(str(k) for k in block)
    return names


def _read_python_deps(root: Path, prefixes: tuple[str, ...]) -> list[tuple[str, set[str]]]:
    found: list[tuple[str, set[str]]] = []
    for path in [root / "pyproject.toml", *sorted(root.glob("requirements*.txt"))]:
        if not path.is_file():
            continue
        rel = _rel(root, path)
        if _is_skipped_rel(rel, prefixes):
            continue
        try:
            lower = path.read_bytes().decode(_JSON_ENCODING, "ignore").lower()
        except OSError:
            continue
        names = {
            dep
            for dep in ORM_PY_DEPS
            if re.search(rf"(?m)^\s*{re.escape(dep)}\b", lower)
            or f'"{dep}"' in lower
            or f"'{dep}'" in lower
        }
        if names:
            found.append((rel, names))
    return found


def _decode_text(path: Path) -> str:
    return path.read_bytes().decode(_JSON_ENCODING, "ignore")


def _dir_has_real_files(root: Path, rel_dir: str, prefixes: tuple[str, ...]) -> bool:
    base = root / rel_dir
    if not base.is_dir():
        return False
    for path in sorted(p for p in base.rglob("*") if p.is_file()):
        rel = _rel(root, path)
        if _is_skipped_rel(rel, prefixes) or set(Path(rel).parts) & _SKIP_DIR_NAMES:
            continue
        if path.name in PLACEHOLDER_NAMES:
            continue
        try:
            if path.stat().st_size == 0:
                continue
            if not _decode_text(path).strip():
                continue
        except OSError:
            continue
        return True
    return False


def _normalize_rel(rel: str) -> str:
    return rel.replace("\\", "/").rstrip("/")


def _looks_like_db_dir(rel: str) -> str | None:
    rel = _normalize_rel(rel)
    if rel not in DB_DIR_ROOT_NAMES and not any(rel.endswith(suf) for suf in DB_DIR_SUFFIXES):
        return None
    if rel == "pgtap" or rel.endswith("/pgtap"):
        return "pgtap_dir"
    if rel.endswith(("db/tests", "tests/db", "tests/sql")):
        return "db_tests_dir"
    return "migrations_dir"


def _uniq_evidence(evidence: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str | None, str | None]] = set()
    uniq: list[dict[str, str]] = []
    for item in evidence:
        key = (item.get("kind"), item.get("path"))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(item)
    return uniq


def detect_e2e(root: Path, *, skip_prefixes: tuple[str, ...] | None = None) -> dict[str, Any]:
    prefixes = skip_rel_prefixes(root) if skip_prefixes is None else skip_prefixes
    evidence: list[dict[str, str]] = []
    for path in _iter_files(root):
        rel = _rel(root, path)
        if _is_skipped_rel(rel, prefixes):
            continue
        if path.name in E2E_CONFIG_NAMES:
            evidence.append({"kind": "config", "path": rel})
        if path.name == "package.json":
            hit = sorted(d for d in E2E_PKG_DEPS if d in _read_package_deps(path))
            if hit:
                evidence.append({"kind": "package_dep", "path": rel, "detail": ",".join(hit)})
        parts = Path(rel).parts
        # "e2e" / "playwright" dir segments cover cypress/e2e without a special-case branch.
        for i, part in enumerate(parts[:-1]):
            if part not in E2E_DIR_NAMES:
                continue
            dir_rel = "/".join(parts[: i + 1])
            # reports/ is already pruned via _SKIP_DIR_NAMES in _iter_files.
            if _dir_has_real_files(root, dir_rel, prefixes):
                evidence.append({"kind": "tests_dir", "path": dir_rel})
    uniq = _uniq_evidence(evidence)
    return {"present": bool(uniq), "evidence": uniq, "framework": _e2e_framework(uniq)}


def detect_db_layer(root: Path, *, skip_prefixes: tuple[str, ...] | None = None) -> dict[str, Any]:
    prefixes = skip_rel_prefixes(root) if skip_prefixes is None else skip_prefixes
    evidence: list[dict[str, str]] = []
    # Walk + markers only (no duplicate root-name loop — that left dual-path survivors).
    for name in DB_FILE_MARKERS:
        if (root / name).is_file() and not _is_skipped_rel(name, prefixes):
            evidence.append({"kind": "marker_file", "path": name})
    for path in _iter_files(root):
        rel = _rel(root, path)
        if _is_skipped_rel(rel, prefixes):
            continue
        parent = Path(rel).parent.as_posix()
        kind = _looks_like_db_dir(parent)
        if kind is not None:
            if path.name in PLACEHOLDER_NAMES:
                continue
            try:
                if path.stat().st_size == 0 or not _decode_text(path).strip():
                    continue
            except OSError:
                continue
            evidence.append({"kind": kind, "path": parent})
        if path.name == "schema.prisma":
            evidence.append({"kind": "marker_file", "path": rel})
        if path.name == "package.json":
            hit = sorted(d for d in ORM_JS_DEPS if d in _read_package_deps(path))
            if hit:
                evidence.append({"kind": "orm_dep", "path": rel, "detail": ",".join(hit)})
        if path.suffix == ".sql":
            try:
                head = _decode_text(path)[:4000].lower()
            except OSError:
                continue
            if "select plan(" in head or "pgtap" in head or "tap:" in head:
                evidence.append({"kind": "pgtap_sql", "path": rel})
    for rel, names in _read_python_deps(root, prefixes):
        evidence.append({"kind": "orm_dep", "path": rel, "detail": ",".join(sorted(names))})
    uniq = _uniq_evidence(evidence)
    return {"present": bool(uniq), "evidence": uniq, "framework": _db_framework(uniq)}


def _evidence_blob(evidence: list[dict[str, str]]) -> str:
    parts: list[str] = []
    for item in evidence:
        parts.append(str(item.get("path") or ""))
        parts.append(str(item.get("detail") or ""))
    return " ".join(parts).lower()


def _e2e_framework(evidence: list[dict[str, str]]) -> str | None:
    blob = _evidence_blob(evidence)
    if "playwright" in blob:
        return "playwright"
    if "cypress" in blob:
        return "cypress"
    return None


def _db_framework(evidence: list[dict[str, str]]) -> str | None:
    kinds = {e.get("kind") for e in evidence}
    if "pgtap_sql" in kinds or "pgtap_dir" in kinds:
        return "pgtap"
    blob = _evidence_blob(evidence)
    if "prisma" in blob:
        return "prisma"
    if "drizzle" in blob:
        return "drizzle"
    if "alembic" in blob or "sqlalchemy" in blob:
        return "alembic"
    if "django" in blob:
        return "django"
    if kinds & {"migrations_dir", "orm_dep", "marker_file", "db_tests_dir"}:
        return "sql"
    return None


def _has_supabase(root: Path) -> bool:
    return (root / "supabase" / "config.toml").is_file()


def default_test_command(
    gate_name: str, detection: dict[str, Any], *, root: Path | None = None
) -> str | None:
    framework = detection.get("framework")
    if gate_name == "e2e":
        if framework == "playwright":
            return "npx playwright test"
        if framework == "cypress":
            return "npx cypress run"
        return None
    if gate_name == "db_tests":
        if root is not None and _has_supabase(root):
            return "supabase test db"
        if framework == "pgtap":
            return "pg_prove db/tests/*.sql tests/db/*.sql pgtap/*.sql"
        return None
    return None
