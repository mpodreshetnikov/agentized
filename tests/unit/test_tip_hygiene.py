"""AGE-76: PR tip hygiene + INDEX freshness hard gates."""

from __future__ import annotations

import json
from pathlib import Path

from agentized.status_gates import GateResult
from agentized.tip_hygiene import (
    EMPTY_CLAIM_PLACEHOLDER,
    MSG_INDEX_STALE,
    MSG_TIP_CLAIM,
    MSG_TIP_STATUS,
    MSG_UNREADABLE,
    apply_ready,
    claim_is_held,
    parse_pr_number,
    resolve_validate_pr_number,
    run_tip_hygiene_gates,
    task_pr_matches,
    validate_index_freshness,
    validate_tip_hygiene,
)
from agentized.task_schema import rebuild_task_index


def _task(
    status: str,
    *,
    claim: str = "_(пусто)_",
    pr: str = "",
    extra: str = "",
    value: bool = True,
) -> str:
    lines = [
        "# T-261121-tip — Tip hygiene",
        "",
        f"статус: {status}",
        "теги: age-76",
        "родитель: _(пусто)_",
        f"claim: {claim}",
    ]
    if pr:
        lines.append(f"pr: {pr}")
    if extra:
        lines.append(extra.rstrip())
    lines.append("")
    if value:
        lines.extend(["Ценность: tip ready means self-review + empty claim", ""])
    lines.append("## Цель\n\nGate tip hygiene.\n")
    return "\n".join(lines) + "\n"


def _write_index(tasks: Path) -> None:
    (tasks / "INDEX.md").write_text(rebuild_task_index(tasks), encoding="utf-8")


def test_parse_pr_number_shapes():
    assert parse_pr_number(None) is parse_pr_number("") is parse_pr_number("  ") is None
    assert parse_pr_number(0) is parse_pr_number(-3) is parse_pr_number("0") is None
    assert parse_pr_number(76) == 76
    assert parse_pr_number("76") == parse_pr_number(" 76 ") == 76
    assert parse_pr_number("#76") == parse_pr_number("PR #76") == parse_pr_number("pr #76") == 76
    assert parse_pr_number("https://github.com/o/r/pull/76") == 76
    assert parse_pr_number("https://github.com/o/r/pull/76?x=1#frag") == 76
    assert parse_pr_number("pull/99") == 99
    assert parse_pr_number("not-a-pr") is None
    assert parse_pr_number("https://example.com/76") is None


def test_resolve_validate_pr_number_env_and_event(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("TASKS_VALIDATE_PR", raising=False)
    monkeypatch.delenv("GITHUB_PR_NUMBER", raising=False)
    monkeypatch.delenv("PULL_REQUEST_NUMBER", raising=False)
    monkeypatch.delenv("GITHUB_REF", raising=False)
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)

    assert resolve_validate_pr_number() is None
    assert resolve_validate_pr_number(explicit=76) == 76
    assert resolve_validate_pr_number(explicit="#76") == 76
    assert resolve_validate_pr_number(explicit="nope") is None

    monkeypatch.setenv("TASKS_VALIDATE_PR", "12")
    assert resolve_validate_pr_number() == 12
    monkeypatch.setenv("TASKS_VALIDATE_PR", "bad")
    monkeypatch.setenv("GITHUB_PR_NUMBER", "34")
    assert resolve_validate_pr_number() == 34
    monkeypatch.delenv("GITHUB_PR_NUMBER", raising=False)
    monkeypatch.setenv("PULL_REQUEST_NUMBER", "56")
    assert resolve_validate_pr_number() == 56
    monkeypatch.delenv("TASKS_VALIDATE_PR", raising=False)
    monkeypatch.delenv("PULL_REQUEST_NUMBER", raising=False)

    monkeypatch.setenv("GITHUB_REF", "refs/pull/88/merge")
    assert resolve_validate_pr_number() == 88
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    assert resolve_validate_pr_number() is None

    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"number": 91}}), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    assert resolve_validate_pr_number() == 91

    event.write_text(
        json.dumps({"issue": {"number": 92, "pull_request": {"url": "x"}}}),
        encoding="utf-8",
    )
    assert resolve_validate_pr_number() == 92

    event.write_text(json.dumps({"issue": {"number": 93}}), encoding="utf-8")
    assert resolve_validate_pr_number() is None

    event.write_text(json.dumps({"number": 94}), encoding="utf-8")
    assert resolve_validate_pr_number() == 94

    # pull_request present but unparsable number → fall through to top-level number
    event.write_text(
        json.dumps({"pull_request": {"number": "bad"}, "number": 95}),
        encoding="utf-8",
    )
    assert resolve_validate_pr_number() == 95

    event.write_text("not-json", encoding="utf-8")
    assert resolve_validate_pr_number() is None
    event.write_text("[]", encoding="utf-8")
    assert resolve_validate_pr_number() is None
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(tmp_path / "missing.json"))
    assert resolve_validate_pr_number() is None


def test_claim_held_and_pr_match():
    assert claim_is_held("alice") is True
    assert claim_is_held("  bob  ") is True
    assert claim_is_held("") is claim_is_held(None) is False
    assert claim_is_held("_(пусто)_") is False
    assert claim_is_held("_(пусто или кто ведёт)_") is False
    assert task_pr_matches("#76", 76) is True
    assert task_pr_matches("https://github.com/a/b/pull/76", 76) is True
    assert task_pr_matches("#75", 76) is False
    assert task_pr_matches("", 76) is False
    assert task_pr_matches(None, 76) is False


def test_tip_hygiene_status_and_claim(tmp_path: Path):
    assert validate_tip_hygiene(tmp_path, pr_number=None) == GateResult(True)

    path = tmp_path / "T-261121-tip.md"
    path.write_text(
        _task("in-progress", claim="worker", pr="#76"),
        encoding="utf-8",
    )
    bad = validate_tip_hygiene(tmp_path, pr_number=76)
    assert bad.ok is False
    assert MSG_TIP_STATUS.format(name=path.name, num=76, st="in-progress") in bad.errors
    assert MSG_TIP_CLAIM.format(name=path.name, num=76, claim="worker") in bad.errors

    path.write_text(
        _task(
            "self-review",
            claim="worker",
            pr="https://github.com/o/r/pull/76",
            extra="review_note: tip green",
        ),
        encoding="utf-8",
    )
    held = validate_tip_hygiene(tmp_path, pr_number=76)
    assert held == GateResult(
        False,
        (MSG_TIP_CLAIM.format(name=path.name, num=76, claim="worker"),),
    )

    path.write_text(
        _task(
            "self-review",
            claim="_(пусто)_",
            pr="#76",
            extra="review_note: tip green",
        ),
        encoding="utf-8",
    )
    assert validate_tip_hygiene(tmp_path, pr_number=76) == GateResult(True)

    path.write_text(
        _task("done", claim="_(пусто)_", pr="#76", extra="acceptance_note: merged"),
        encoding="utf-8",
    )
    assert validate_tip_hygiene(tmp_path, pr_number=76) == GateResult(True)

    path.write_text(_task("in-progress", claim="worker", pr="#75"), encoding="utf-8")
    assert validate_tip_hygiene(tmp_path, pr_number=76) == GateResult(True)

    path.write_text(
        _task(
            "for-review",
            claim="_(пусто)_",
            pr="#76",
            extra="review_note: tip",
        ),
        encoding="utf-8",
    )
    fr = validate_tip_hygiene(tmp_path, pr_number=76)
    assert fr == GateResult(
        False,
        (MSG_TIP_STATUS.format(name=path.name, num=76, st="for-review"),),
    )

    assert validate_tip_hygiene(tmp_path, pr_number=76, skip_stems=frozenset({"T-261121-tip"})) == (
        GateResult(True)
    )


def test_tip_hygiene_unreadable(tmp_path: Path):
    path = tmp_path / "T-261121-bad.md"
    path.write_bytes(b"\xff\xfe not utf-8")
    try:
        path.read_bytes().decode("utf-8")
        raise AssertionError("expected UnicodeDecodeError")
    except UnicodeDecodeError as exc:
        bad = validate_tip_hygiene(tmp_path, pr_number=1)
        assert bad == GateResult(False, (f"{path.name}: {MSG_UNREADABLE.format(detail=exc)}",))


def test_index_freshness(tmp_path: Path):
    tasks = tmp_path
    (tasks / "T-261121-ix.md").write_text(_task("open"), encoding="utf-8")
    assert validate_index_freshness(tasks) == GateResult(False, (MSG_INDEX_STALE,))
    _write_index(tasks)
    assert validate_index_freshness(tasks) == GateResult(True)
    (tasks / "INDEX.md").write_text("# stale\n", encoding="utf-8")
    assert validate_index_freshness(tasks) == GateResult(False, (MSG_INDEX_STALE,))


def test_index_freshness_unreadable(tmp_path: Path):
    index = tmp_path / "INDEX.md"
    index.write_text("x", encoding="utf-8")
    index.chmod(0)
    try:
        try:
            index.read_text(encoding="utf-8")
            raise AssertionError("expected OSError")
        except OSError as exc:
            bad = validate_index_freshness(tmp_path)
            assert bad == GateResult(False, (MSG_UNREADABLE.format(detail=exc),))
    finally:
        index.chmod(0o644)


def test_apply_ready_releases_claim_and_status():
    base = _task("in-progress", claim="worker")
    out = apply_ready(base, pr="#76", review_note="CI green; tip hygiene")
    assert "статус: self-review" in out
    assert f"claim: {EMPTY_CLAIM_PLACEHOLDER}" in out
    assert "pr: #76" in out
    assert "review_note: CI green; tip hygiene" in out
    assert "статус → self-review" in out
    again = apply_ready(out)
    assert again.count("статус → self-review") == 1
    bare = apply_ready(_task("in-progress", claim="x"), pr="  ", review_note="  ")
    header = bare.split("## Цель", 1)[0]
    assert "pr:" not in header
    assert "review_note:" not in header
    assert f"claim: {EMPTY_CLAIM_PLACEHOLDER}" in header


def test_run_tip_hygiene_gates_wires_tip_and_index(tmp_path: Path):
    path = tmp_path / "T-261121-wire.md"
    path.write_text(
        _task("in-progress", claim="worker", pr="#76"),
        encoding="utf-8",
    )
    _write_index(tmp_path)
    wired = run_tip_hygiene_gates(tmp_path, pr_number=76, check_index=True)
    assert wired.ok is False
    assert any("tip hygiene" in e for e in wired.errors)

    path.write_text(
        _task(
            "self-review",
            claim="_(пусто)_",
            pr="#76",
            extra="review_note: ready",
        ),
        encoding="utf-8",
    )
    _write_index(tmp_path)
    assert run_tip_hygiene_gates(tmp_path, pr_number=76, check_index=True) == GateResult(True)

    (tmp_path / "INDEX.md").write_text("stale", encoding="utf-8")
    stale = run_tip_hygiene_gates(tmp_path, pr_number=76, check_index=True)
    assert MSG_INDEX_STALE in stale.errors
    assert run_tip_hygiene_gates(tmp_path, pr_number=76, check_index=False).ok is True


def test_run_tip_hygiene_gates_reads_pr_env(tmp_path: Path, monkeypatch):
    tasks = tmp_path / "context" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "T-261121-env.md").write_text(
        _task("in-progress", claim="worker", pr="#41"),
        encoding="utf-8",
    )
    _write_index(tasks)
    monkeypatch.setenv("TASKS_VALIDATE_PR", "41")
    result = run_tip_hygiene_gates(tasks, check_index=True)
    assert result.ok is False
    assert any("tip hygiene" in e and "#41" in e for e in result.errors)

    monkeypatch.delenv("TASKS_VALIDATE_PR", raising=False)
    ok = run_tip_hygiene_gates(tasks, pr_number=None, check_index=True)
    assert ok.ok is True
