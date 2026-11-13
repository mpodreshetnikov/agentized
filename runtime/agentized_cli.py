#!/usr/bin/env python3
"""Agentized minimal CLI — connect, tasks, leases, digests, checks."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT_RUNTIME = Path(__file__).resolve().parent
if str(ROOT_RUNTIME) not in sys.path:
    sys.path.insert(0, str(ROOT_RUNTIME))

from agentized import __version__
from agentized.connect import connect
from agentized.leases import (
    find_overlaps,
    list_leases,
    rebuild_lease_index,
    render_lease_file,
    warn_message,
)
from agentized.paths import DEFAULT_CONTEXT, find_repo_root, load_state
from agentized.quality import load_quality, set_coverage_threshold
from agentized.tasks import (
    ACTIVE_STATUSES,
    ALL_STATUSES,
    allocate_task_id,
    append_progress,
    list_tasks,
    parse_task,
    rebuild_task_index,
    render_task_file,
    set_field,
)


def _ctx(root: Path, args) -> Path:
    rel = getattr(args, "context", None) or load_state(root).get("context") or DEFAULT_CONTEXT
    return root / rel


def cmd_connect(args: argparse.Namespace) -> int:
    root = find_repo_root()
    harnesses = args.harness
    if harnesses == ["all"]:
        harnesses = ["cursor", "claude", "codex"]
    result = connect(
        root,
        context_rel=args.context,
        harnesses=harnesses,
        coverage_pct=args.coverage,
    )
    print("connect OK")
    print(f"  context: {args.context}/")
    print(f"  version: {__version__}")
    print(f"  AGENTS.md updated: {result['state']['agents_md_updated']}")
    print(f"  CLAUDE.md updated: {result['state']['claude_md_updated']}")
    print(f"  harnesses: {', '.join(harnesses)}")
    if result.get("quality"):
        cov = load_quality(root, args.context).get("coverage") or {}
        print(f"  quality.json: {result['quality']['path']} (lines/branches ≥{cov.get('lines')}%)")
    if result.get("quality_templates"):
        qt = result["quality_templates"]
        print(f"  quality templates: pre-push={qt.get('pre_push')} ci={qt.get('ci_workflow')}")
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_env_check(args: argparse.Namespace) -> int:
    from agentized.env_check import check

    root = find_repo_root()
    ctx_rel = getattr(args, "context", None) or load_state(root).get("context") or DEFAULT_CONTEXT
    result = check(repo_root=root, context_rel=ctx_rel)
    stream = sys.stdout if result["ok"] else sys.stderr
    stream.write(result["message"] + "\n")
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


def cmd_quality(args: argparse.Namespace) -> int:
    root = find_repo_root()
    ctx_rel = getattr(args, "context", None) or load_state(root).get("context") or DEFAULT_CONTEXT
    if args.quality_cmd == "show":
        data = load_quality(root, ctx_rel)
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    if args.quality_cmd == "set-coverage":
        data = set_coverage_threshold(root, args.pct, context_rel=ctx_rel)
        print(
            f"coverage thresholds → lines={data['coverage']['lines']}% "
            f"branches={data['coverage']['branches']}%"
        )
        return 0
    if args.quality_cmd == "check":
        from agentized.coverage_check import run_coverage_check
        from agentized.mutation import run_mutation

        cov_rc = run_coverage_check(root, context=ctx_rel)
        if cov_rc != 0:
            return cov_rc
        return run_mutation(root, context=ctx_rel)
    print("неизвестная подкоманда quality", file=sys.stderr)
    return 1


def cmd_new(args: argparse.Namespace) -> int:
    root = find_repo_root()
    ctx = _ctx(root, args)
    tasks_dir = ctx / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)

    if not args.yes:
        reply = input(f"Создать задачу «{args.title}»? [y/N]: ").strip().lower()
        if reply not in {"y", "yes", "д", "да"}:
            print("отменено (нужно подтверждение человека)")
            return 2

    task_id = allocate_task_id(tasks_dir)
    parent = args.parent or ""
    text = render_task_file(
        task_id,
        args.title,
        status="open",
        tags=args.tags or "",
        parent=parent,
        goal=args.goal or "Что должно быть сделано.",
    )
    path = tasks_dir / f"{task_id}.md"
    path.write_text(text, encoding="utf-8")
    (tasks_dir / "INDEX.md").write_text(rebuild_task_index(tasks_dir), encoding="utf-8")
    print(f"создано: {path.relative_to(root)}")
    print(f"id: {task_id}")
    return 0


def cmd_claim(args: argparse.Namespace) -> int:
    root = find_repo_root()
    ctx = _ctx(root, args)
    path = ctx / "tasks" / f"{args.task_id}.md"
    if not path.exists():
        print(f"нет задачи {args.task_id}", file=sys.stderr)
        return 1
    text = path.read_text(encoding="utf-8")
    text = set_field(text, "claim", args.owner)
    text = set_field(text, "статус", "in-progress")
    text = append_progress(text, f"claim by {args.owner}")
    path.write_text(text, encoding="utf-8")
    (ctx / "tasks" / "INDEX.md").write_text(
        rebuild_task_index(ctx / "tasks"), encoding="utf-8"
    )
    print(f"claimed {args.task_id} → {args.owner} (статус: in-progress)")
    return 0


def cmd_progress(args: argparse.Namespace) -> int:
    root = find_repo_root()
    ctx = _ctx(root, args)
    path = ctx / "tasks" / f"{args.task_id}.md"
    if not path.exists():
        print(f"нет задачи {args.task_id}", file=sys.stderr)
        return 1
    text = append_progress(path.read_text(encoding="utf-8"), args.text)
    path.write_text(text, encoding="utf-8")
    print(f"progress appended → {path.relative_to(root)}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    root = find_repo_root()
    ctx = _ctx(root, args)
    path = ctx / "tasks" / f"{args.task_id}.md"
    if not path.exists():
        print(f"нет задачи {args.task_id}", file=sys.stderr)
        return 1
    if args.status not in ALL_STATUSES:
        print(f"неизвестный статус {args.status}; ожидалось одно из {ALL_STATUSES}", file=sys.stderr)
        return 1
    text = set_field(path.read_text(encoding="utf-8"), "статус", args.status)
    path.write_text(text, encoding="utf-8")
    (ctx / "tasks" / "INDEX.md").write_text(
        rebuild_task_index(ctx / "tasks"), encoding="utf-8"
    )
    print(f"{args.task_id}: статус → {args.status} (файл не перемещался)")
    return 0


def cmd_index(args: argparse.Namespace) -> int:
    root = find_repo_root()
    ctx = _ctx(root, args)
    tasks_index = rebuild_task_index(ctx / "tasks")
    leases_index = rebuild_lease_index(ctx / "leases")
    (ctx / "tasks" / "INDEX.md").write_text(tasks_index, encoding="utf-8")
    (ctx / "leases" / "INDEX.md").write_text(leases_index, encoding="utf-8")
    print("пересобраны:")
    print(f"  {ctx.relative_to(root)}/tasks/INDEX.md")
    print(f"  {ctx.relative_to(root)}/leases/INDEX.md")
    if args.print:
        print("\n--- tasks/INDEX.md ---\n")
        print(tasks_index)
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    root = find_repo_root()
    ctx = _ctx(root, args)
    errors: list[str] = []
    warnings: list[str] = []

    if not (root / "AGENTS.md").exists():
        errors.append("нет AGENTS.md")
    else:
        agents = (root / "AGENTS.md").read_text(encoding="utf-8")
        if "NAV.md" not in agents:
            errors.append("AGENTS.md без указателя на NAV.md — нужен connect")
    if not (ctx / "NAV.md").exists():
        errors.append(f"нет {ctx.relative_to(root)}/NAV.md")
    for required in (
        "tasks/INDEX.md",
        "leases/INDEX.md",
        "skills",
        "hooks",
        "quality.json",
    ):
        if not (ctx / required).exists():
            errors.append(f"нет {ctx.relative_to(root)}/{required}")
    if not (ctx / "skills" / "quality-gates" / "SKILL.md").exists():
        warnings.append("нет pinned skill quality-gates — запустите connect")

    # live index freshness (soft): statuses in INDEX vs files
    tasks = list_tasks(ctx / "tasks")
    index_text = (ctx / "tasks" / "INDEX.md").read_text(encoding="utf-8") if (ctx / "tasks" / "INDEX.md").exists() else ""
    for t in tasks:
        if t.status in ACTIVE_STATUSES and t.task_id not in index_text:
            warnings.append(f"задача {t.task_id} активна, но нет в INDEX — запустите index")

    # harness wiring
    for label, path in (
        ("cursor hooks", root / ".cursor" / "hooks.json"),
        ("claude settings", root / ".claude" / "settings.json"),
        ("codex hooks", root / ".codex" / "hooks.json"),
    ):
        if not path.exists():
            warnings.append(f"нет {path.relative_to(root)} (connect --harness …)")

    state = load_state(root)
    if not state:
        warnings.append("нет .agentized/connect.json — connect ещё не запускали?")

    if errors:
        print("check FAIL")
        for e in errors:
            print(f"  ERROR: {e}")
        for w in warnings:
            print(f"  WARN: {w}")
        return 1
    print("check OK")
    for w in warnings:
        print(f"  WARN: {w}")
    if args.json:
        print(json.dumps({"ok": True, "warnings": warnings, "state": state}, ensure_ascii=False, indent=2))
    return 0


def cmd_lease(args: argparse.Namespace) -> int:
    root = find_repo_root()
    ctx = _ctx(root, args)
    leases_dir = ctx / "leases"
    leases_dir.mkdir(parents=True, exist_ok=True)

    if args.lease_cmd == "list":
        leases = list_leases(leases_dir)
        if not leases:
            print("(нет активных leases)")
            return 0
        for lease in leases:
            print(f"{lease.task_id} owner={lease.owner} paths={', '.join(lease.paths)} expires={lease.expires}")
        return 0

    if args.lease_cmd == "acquire":
        overlaps = find_overlaps(
            list_leases(leases_dir), args.paths, ignore_task=args.task_id
        )
        if overlaps:
            print(warn_message(overlaps))
            print("(запись не блокируется)")
        text = render_lease_file(args.task_id, args.owner, args.paths)
        path = leases_dir / f"{args.task_id}.md"
        path.write_text(text, encoding="utf-8")
        (leases_dir / "INDEX.md").write_text(rebuild_lease_index(leases_dir), encoding="utf-8")
        print(f"lease acquired: {path.relative_to(root)}")
        return 0

    if args.lease_cmd == "release":
        path = leases_dir / f"{args.task_id}.md"
        if not path.exists():
            print(f"нет lease для {args.task_id}", file=sys.stderr)
            return 1
        text = path.read_text(encoding="utf-8")
        text = text.replace("status: active", "status: released")
        if "status: released" not in text:
            text = text.rstrip() + "\nstatus: released\n"
        path.write_text(text, encoding="utf-8")
        (leases_dir / "INDEX.md").write_text(rebuild_lease_index(leases_dir), encoding="utf-8")
        print(f"lease released: {args.task_id}")
        return 0

    if args.lease_cmd == "check":
        overlaps = find_overlaps(list_leases(leases_dir), args.paths, ignore_task=args.task_id)
        if overlaps:
            print(warn_message(overlaps))
            return 0
        print("нет пересечений")
        return 0

    print("неизвестная подкоманда lease", file=sys.stderr)
    return 1


def cmd_sync_status(args: argparse.Namespace) -> int:
    root = find_repo_root()
    ctx = _ctx(root, args)
    state = load_state(root)
    tasks = list_tasks(ctx / "tasks")
    active = [t for t in tasks if t.status in ACTIVE_STATUSES]
    leases = list_leases(ctx / "leases")
    print("sync-status")
    print(f"  connected: {'yes' if state else 'no'}")
    print(f"  context: {ctx.relative_to(root)}/")
    print(f"  active tasks: {len(active)}")
    for t in active:
        claim = t.claim if t.claim and not t.claim.startswith("_") else "—"
        print(f"    - {t.task_id} [{t.status}] claim={claim} — {t.title}")
    print(f"  active leases: {len(leases)}")
    for lease in leases:
        print(f"    - {lease.task_id} owner={lease.owner} → {', '.join(lease.paths)}")
    # overlap summary among active leases
    warnings = []
    for i, a in enumerate(leases):
        for b in leases[i + 1 :]:
            for pa in a.paths:
                for pb in b.paths:
                    from agentized.leases import path_overlaps

                    if path_overlaps(pa, pb):
                        warnings.append(f"{a.task_id}/{pa} ↔ {b.task_id}/{pb}")
    if warnings:
        print("  lease overlaps (warn-only):")
        for w in warnings:
            print(f"    - {w}")
    else:
        print("  lease overlaps: none")
    return 0


def cmd_digest(args: argparse.Namespace) -> int:
    root = find_repo_root()
    ctx = _ctx(root, args)
    if args.type not in {"development", "management"}:
        print("type: development|management", file=sys.stderr)
        return 1
    day = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir = ctx / "digests" / args.type
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{day}.md"
    tasks = list_tasks(ctx / "tasks")
    active = [t for t in tasks if t.status in ACTIVE_STATUSES]
    done = [t for t in tasks if t.status == "done"]
    leases = list_leases(ctx / "leases")
    if args.type == "development":
        body = [
            f"# Digest development — {day}",
            "",
            "## Сейчас в работе",
        ]
        body.extend(
            [f"- {t.task_id} [{t.status}] {t.title} (claim: {t.claim or '—'})" for t in active]
            or ["- _(пусто)_"]
        )
        body += ["", "## Активные path leases", ""]
        body.extend(
            [f"- {l.task_id}: {', '.join(l.paths)} (owner {l.owner})" for l in leases]
            or ["- _(пусто)_"]
        )
        body += ["", "## Заметки", "", args.notes or "_(нет)_", ""]
    else:
        body = [
            f"# Digest management — {day}",
            "",
            "## Прогресс",
            f"- Активных задач: {len(active)}",
            f"- Done (в дереве): {len(done)}",
            "",
            "## Риски / пересечения",
        ]
        overlaps = []
        for i, a in enumerate(leases):
            for b in leases[i + 1 :]:
                from agentized.leases import path_overlaps

                for pa in a.paths:
                    for pb in b.paths:
                        if path_overlaps(pa, pb):
                            overlaps.append(f"{a.task_id}↔{b.task_id} на `{pa}`/`{pb}`")
        body.extend([f"- {o}" for o in overlaps] or ["- пересечений leases нет"])
        body += ["", "## Заметки", "", args.notes or "_(нет)_", ""]
    path.write_text("\n".join(body) + "\n", encoding="utf-8")
    # drop .gitkeep if present and we have content
    gk = out_dir / ".gitkeep"
    if gk.exists():
        gk.unlink()
    print(f"digest: {path.relative_to(root)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agentized",
        description="Минимальный runtime Agentized (connect / tasks / leases / digest).",
    )
    p.add_argument("--version", action="version", version=f"agentized {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("connect", help="Идемпотентный connect к Project Context + harness wiring")
    c.add_argument("--context", default=DEFAULT_CONTEXT, help="относительный путь Context")
    c.add_argument(
        "--harness",
        nargs="+",
        default=["all"],
        choices=["all", "cursor", "claude", "codex"],
        help="какие harness установить (по умолчанию all)",
    )
    c.add_argument(
        "--coverage",
        type=float,
        default=None,
        metavar="PCT",
        help="задать порог coverage lines+branches в context/quality.json (по умолчанию 80)",
    )
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=cmd_connect)

    ec = sub.add_parser("env-check", help="Fail-closed agent/cloud hook wiring check")
    ec.add_argument("--context", default=None)
    ec.add_argument("--json", action="store_true")
    ec.set_defaults(func=cmd_env_check)

    q = sub.add_parser("quality", help="Пороги coverage / mutation / quality.json")
    q_sub = q.add_subparsers(dest="quality_cmd", required=True)
    qs = q_sub.add_parser("show", help="Показать context/quality.json")
    qs.add_argument("--context", default=None)
    qsc = q_sub.add_parser("set-coverage", help="Изменить глобальный порог coverage")
    qsc.add_argument("pct", type=float)
    qsc.add_argument("--context", default=None)
    qc = q_sub.add_parser("check", help="coverage_check + mutation hard gate")
    qc.add_argument("--context", default=None)
    q.set_defaults(func=cmd_quality)

    n = sub.add_parser("new", help="Создать задачу (по умолчанию с подтверждением человека)")
    n.add_argument("--title", required=True)
    n.add_argument("--parent", default="")
    n.add_argument("--tags", default="")
    n.add_argument("--goal", default="")
    n.add_argument("--context", default=None)
    n.add_argument(
        "--yes",
        action="store_true",
        help="пропустить подтверждение (только для автотестов; не использовать в runbook)",
    )
    n.set_defaults(func=cmd_new)

    cl = sub.add_parser("claim", help="Claim задачи + статус in-progress")
    cl.add_argument("task_id")
    cl.add_argument("--owner", required=True)
    cl.add_argument("--context", default=None)
    cl.set_defaults(func=cmd_claim)

    pr = sub.add_parser("progress", help="Append-only Progress в файл задачи")
    pr.add_argument("task_id")
    pr.add_argument("--text", required=True)
    pr.add_argument("--context", default=None)
    pr.set_defaults(func=cmd_progress)

    st = sub.add_parser("status", help="Сменить статус (файл не перемещается)")
    st.add_argument("task_id")
    st.add_argument("--status", required=True, choices=list(ALL_STATUSES))
    st.add_argument("--context", default=None)
    st.set_defaults(func=cmd_status)

    ix = sub.add_parser("index", help="Пересобрать живые индексы tasks/leases")
    ix.add_argument("--context", default=None)
    ix.add_argument("--print", action="store_true")
    ix.set_defaults(func=cmd_index)

    ch = sub.add_parser("check", help="Проверить connect layout и целостность")
    ch.add_argument("--context", default=None)
    ch.add_argument("--json", action="store_true")
    ch.set_defaults(func=cmd_check)

    lease = sub.add_parser("lease", help="Path leases (warn-only)")
    lease_sub = lease.add_subparsers(dest="lease_cmd", required=True)
    la = lease_sub.add_parser("acquire")
    la.add_argument("task_id")
    la.add_argument("paths", nargs="+")
    la.add_argument("--owner", required=True)
    la.add_argument("--context", default=None)
    lr = lease_sub.add_parser("release")
    lr.add_argument("task_id")
    lr.add_argument("--context", default=None)
    ll = lease_sub.add_parser("list")
    ll.add_argument("--context", default=None)
    lc = lease_sub.add_parser("check")
    lc.add_argument("paths", nargs="+")
    lc.add_argument("--task-id", dest="task_id", default=None)
    lc.add_argument("--context", default=None)
    lease.set_defaults(func=cmd_lease)

    ss = sub.add_parser("sync-status", help="Сводка claim/leases для сессии")
    ss.add_argument("--context", default=None)
    ss.set_defaults(func=cmd_sync_status)

    dg = sub.add_parser("digest", help="Регулярный digest development|management")
    dg.add_argument("--type", required=True, choices=["development", "management"])
    dg.add_argument("--date", default=None)
    dg.add_argument("--notes", default="")
    dg.add_argument("--context", default=None)
    dg.set_defaults(func=cmd_digest)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
