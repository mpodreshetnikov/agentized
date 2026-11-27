"""AGE-85 e2e: empty/small consumer connect → real pre-push + CI steps green."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from agentized.connect import connect
from agentized.quality import load_quality

# mutmut copies tests under mutants/ without bin/ — resolve real source tree.
_TEST_ROOT = Path(__file__).resolve().parents[2]
AGENTIZED_ROOT = _TEST_ROOT.parent if _TEST_ROOT.name == "mutants" else _TEST_ROOT
BIN = AGENTIZED_ROOT / "bin" / "agentized"


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
    )


def _commit(cwd: Path, msg: str) -> None:
    _git(cwd, "-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-m", msg)


def _env_with_cli() -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = f"{BIN.parent}:{env.get('PATH', '')}"
    env["PYTHONPATH"] = f"{AGENTIZED_ROOT / 'runtime'}{os.pathsep}{env.get('PYTHONPATH', '')}"
    # Clear size/mutation bases so first-push / connect-baseline logic applies.
    env.pop("PROCESS_BASE", None)
    env.pop("MUTATION_BASE", None)
    return env


def _run_cli(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(BIN), *args],
        cwd=cwd,
        env=_env_with_cli(),
        capture_output=True,
        text=True,
        check=False,
    )


def _init_consumer(path: Path) -> None:
    path.mkdir(parents=True)
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.email", "t@t.com")
    _git(path, "config", "user.name", "t")


def _bare_remote(tmp_path: Path, name: str = "remote.git") -> Path:
    bare = tmp_path / name
    _git(tmp_path, "init", "--bare", "-b", "main", str(bare))
    return bare


def test_e2e_empty_consumer_push_and_ci_steps(tmp_path: Path):
    consumer = tmp_path / "empty"
    _init_consumer(consumer)
    connect(consumer, harnesses=["cursor"])
    q = load_quality(consumer)
    assert q["modules"] == []
    assert q["mutation"]["include_globs"] == []

    _git(consumer, "add", "-A")
    _commit(consumer, "chore: agentized connect")
    bare = _bare_remote(tmp_path)
    _git(consumer, "remote", "add", "origin", str(bare))

    push = subprocess.run(
        ["git", "push", "-u", "origin", "main"],
        cwd=consumer,
        env=_env_with_cli(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert push.returncode == 0, push.stdout + push.stderr
    assert "pre-push" in (push.stderr + push.stdout) or "process size" in (
        push.stderr + push.stdout
    )

    # Template CI steps (process size + quality check) with PROCESS_BASE=origin/main.
    env = _env_with_cli()
    env["PROCESS_BASE"] = "origin/main"
    env["MUTATION_BASE"] = "origin/main"
    size = subprocess.run(
        [str(BIN), "process", "size"],
        cwd=consumer,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    # After push, origin/main has managed.json → normal size (0 vs itself tip).
    assert size.returncode == 0, size.stdout + size.stderr
    qc = subprocess.run(
        [str(BIN), "quality", "check"],
        cwd=consumer,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert qc.returncode == 0, qc.stdout + qc.stderr
    assert "no modules configured" in qc.stdout


def test_e2e_small_repo_with_src_tests(tmp_path: Path):
    consumer = tmp_path / "small"
    _init_consumer(consumer)
    (consumer / "src").mkdir()
    (consumer / "src" / "pkg.py").write_text("VALUE = 42\n", encoding="utf-8")
    (consumer / "tests").mkdir()
    (consumer / "tests" / "test_pkg.py").write_text(
        "from src.pkg import VALUE\n\ndef test_value():\n    assert VALUE == 42\n",
        encoding="utf-8",
    )
    connect(consumer, harnesses=["cursor"])
    q = load_quality(consumer)
    assert q["modules"][0]["source"] == ["src"]
    assert "pytest tests" in q["modules"][0]["test_command"]

    _git(consumer, "add", "-A")
    _commit(consumer, "chore: connect + src")
    bare = _bare_remote(tmp_path, "small.git")
    _git(consumer, "remote", "add", "origin", str(bare))

    # Seed origin/main with empty commit so size compares connect tree (baseline path).
    # Real push uses pre-push; first push to empty bare uses no-origin/main baseline.
    push = subprocess.run(
        ["git", "push", "-u", "origin", "main"],
        cwd=consumer,
        env=_env_with_cli(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert push.returncode == 0, push.stdout + push.stderr

    env = _env_with_cli()
    env["PROCESS_BASE"] = "origin/main"
    env["MUTATION_BASE"] = "origin/main"
    pytest.importorskip("pytest_cov")
    qc = subprocess.run(
        [str(BIN), "quality", "check"],
        cwd=consumer,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert qc.returncode == 0, qc.stdout + qc.stderr


def test_e2e_negative_stale_runtime_module_fails_closed(tmp_path: Path):
    consumer = tmp_path / "stale"
    _init_consumer(consumer)
    connect(consumer, harnesses=["cursor"])
    # Poison quality.json with dogfood module (the pre-AGE-85 bug).
    path = consumer / "context" / "quality.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["modules"] = [
        {
            "id": "runtime",
            "source": ["runtime/agentized"],
            "test_command": "python3 -m pytest tests/unit -q",
            "coverage_lcov": "coverage/runtime/lcov.info",
            "coverage_json": "coverage/runtime/coverage.json",
            "thresholds": {},
        }
    ]
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    qc = _run_cli(consumer, "quality", "check")
    assert qc.returncode != 0
    err = qc.stderr + qc.stdout
    assert "FAIL runtime" in err
    assert "missing" in err.lower()


def test_e2e_negative_huge_user_file_blocks_push(tmp_path: Path):
    consumer = tmp_path / "huge"
    _init_consumer(consumer)
    # Pre-seed remote with empty commit so size compares against origin/main.
    seed = tmp_path / "seed"
    _init_consumer(seed)
    _git(seed, "commit", "--allow-empty", "-m", "init")
    bare = tmp_path / "huge.git"
    _git(tmp_path, "clone", "--bare", str(seed), str(bare))
    _git(consumer, "remote", "add", "origin", str(bare))
    _git(consumer, "fetch", "origin")
    _git(consumer, "reset", "--hard", "origin/main")

    connect(consumer, harnesses=["cursor"])
    (consumer / "src").mkdir()
    (consumer / "src" / "blob.py").write_text("x\n" * 2000, encoding="utf-8")
    _git(consumer, "add", "-A")
    _commit(consumer, "connect + huge")

    push = subprocess.run(
        ["git", "push", "origin", "main"],
        cwd=consumer,
        env=_env_with_cli(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert push.returncode != 0
    assert "PR size" in (push.stderr + push.stdout) or "process-control" in (
        push.stderr + push.stdout
    )
