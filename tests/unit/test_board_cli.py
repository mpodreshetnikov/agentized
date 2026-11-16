"""cmd_board CLI — exit 1, -o rel/abs, --lang, --stamp (lead remarks)."""
from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import agentized_cli as cli


def _task(tasks: Path, tid: str = "T-261116-cli1", status: str = "open") -> None:
    (tasks / f"{tid}.md").write_text(
        f"# {tid} — t\n\nстатус: {status}\nтеги: _(нет)_\n"
        "родитель: _(пусто)_\nclaim: _(пусто)_\n\n## Цель\n\ng\n\n"
        "## Progress\n\n_(append-only)_\n",
        encoding="utf-8",
    )


def _ns(**kw: object) -> Namespace:
    base = {
        "output": "board.html",
        "stamp": False,
        "title": "Доска задач Agentized",
        "lang": "ru",
        "context": "context",
    }
    base.update(kw)
    return Namespace(**base)


def test_cmd_board_ok_rel_abs_lang_stamp(tmp_path: Path, monkeypatch, capsys) -> None:
    root = tmp_path
    tasks = root / "context" / "tasks"
    tasks.mkdir(parents=True)
    _task(tasks)
    monkeypatch.setattr(cli, "find_repo_root", lambda: root)
    assert cli.cmd_board(_ns(output="out/board.html", lang="en")) == 0
    out = capsys.readouterr().out
    assert "board:" in out and (root / "out" / "board.html").is_file()
    html = (root / "out" / "board.html").read_text(encoding="utf-8")
    assert "Kanban from context/tasks" in html
    abs_out = root / "abs-board.html"
    assert cli.cmd_board(_ns(output=str(abs_out), stamp=True)) == 0
    assert abs_out.is_file()
    stamped = abs_out.read_text(encoding="utf-8")
    assert "Сгенерировано" in stamped


def test_cmd_board_fail_bad_task(tmp_path: Path, monkeypatch, capsys) -> None:
    root = tmp_path
    tasks = root / "context" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "T-261116-bad.md").write_text("not a header\n", encoding="utf-8")
    monkeypatch.setattr(cli, "find_repo_root", lambda: root)
    assert cli.cmd_board(_ns()) == 1
    err = capsys.readouterr().err
    assert err.startswith("board FAIL:") and "T-261116-bad.md" in err
