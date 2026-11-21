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
from agentized.context_paths import path_under, resolve_context_dir
from agentized.context_layout import (
    apply_external_env_check,
    prepare_connect_layout,
    require_registry_ready,
    resolve_layout,
)
from agentized.paths import DEFAULT_CONTEXT, find_repo_root, load_state
from agentized.quality import load_quality, set_coverage_threshold
from agentized.status_gates import run_tasks_validate
from agentized.tasks import (
    ACTIVE_STATUSES,
    ALL_STATUSES,
    allocate_task_id,
    append_progress,
    append_status_progress,
    list_tasks,
    parse_task,
    rebuild_task_index,
    render_task_file,
    set_field,
)


def _context_rel(root: Path, args) -> str:
    return getattr(args, "context", None) or load_state(root).get("context") or DEFAULT_CONTEXT


def _layout(root: Path, args):
    rel = _context_rel(root, args)
    resolve_context_dir(root, str(rel))  # AGE-30: refuse abs / .. / escape
    try:
        return resolve_layout(root, rel)
    except ValueError as exc:
        print(f"context layout error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def _ctx(root: Path, args, *, require_ready: bool = False) -> Path:
    """Registry root (tasks/decisions/goals/…) — may be an external Context clone."""
    layout = _layout(root, args)
    if require_ready:
        try:
            require_registry_ready(layout)
        except ValueError as exc:
            print(f"context layout error: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
    return layout.registry_root


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


def cmd_connect(args: argparse.Namespace) -> int:
    root = find_repo_root()
    harnesses = args.harness
    if harnesses == ["all"]:
        harnesses = ["cursor", "claude", "codex"]
    bridged: list[str] = []
    layout = None
    try:
        # Preflight → seed → bridges before connect (skeleton no-ops on NAV bridge).
        # On connect() failure, roll back bridges we just created.
        from agentized.context_layout import (
            ensure_bridge_gitignore,
            ensure_code_context_bridges,
            rollback_code_context_bridges,
        )

        layout = prepare_connect_layout(root, args.context, bridges=False)
        if layout.is_external:
            bridged = ensure_code_context_bridges(layout)
            ensure_bridge_gitignore(root, context_rel=args.context)
        result = connect(
            root,
            context_rel=args.context,
            harnesses=harnesses,
            coverage_pct=args.coverage,
        )
    except ValueError as exc:
        if layout is not None and bridged:
            rollback_code_context_bridges(layout, bridged)
        print(f"context layout error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        # Rollback bridges; seed/.gitignore stay (manual cleanup). No raw traceback.
        if layout is not None and bridged:
            rollback_code_context_bridges(layout, bridged)
        print(f"connect error: {exc}", file=sys.stderr)
        return 1
    result["layout"] = {
        "placement": layout.placement,
        "registry": str(layout.registry_root),
        "config": str((root / args.context / "context.json").relative_to(root)),
    }
    print("connect OK")
    print(f"  context: {args.context}/")
    print(f"  version: {__version__}")
    sk = result.get("skeleton") or {}
    if sk.get("created"):
        print(f"  context skeleton: created ({', '.join(sk.get('files') or [])})")
    else:
        print("  context skeleton: existing (unchanged)")
    print(f"  AGENTS.md updated: {result['state']['agents_md_updated']}")
    print(f"  CLAUDE.md updated: {result['state']['claude_md_updated']}")
    print(f"  harnesses: {', '.join(harnesses)}")
    if result.get("managed_manifest"):
        print(f"  managed manifest: {result['managed_manifest']}")
    skipped = result.get("skipped_user") or []
    if skipped:
        print(f"  skipped_user ({len(skipped)}):")
        for path in skipped:
            print(f"    - {path}")
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
    result = apply_external_env_check(
        check(repo_root=root, context_rel=ctx_rel),
        root,
        ctx_rel,
    )
    stream = sys.stdout if result["ok"] else sys.stderr
    stream.write(result["message"] + "\n")
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


def cmd_review(args: argparse.Namespace) -> int:
    from agentized.review_budget import (
        allow_review,
        record_review,
        reset_scope,
        status as review_status,
    )
    from agentized.quality import set_reviewer_options

    root = find_repo_root()
    ctx_rel = getattr(args, "context", None) or load_state(root).get("context") or DEFAULT_CONTEXT
    scope = getattr(args, "scope", None)
    if args.review_cmd == "status":
        print(json.dumps(review_status(root, context_rel=ctx_rel, scope=scope), indent=2))
        return 0
    if args.review_cmd == "reset":
        result = reset_scope(root, scope=scope)
        print(result["message"])
        if getattr(args, "json", False):
            print(json.dumps(result, indent=2))
        return 0
    if args.review_cmd == "allow":
        result = allow_review(root, context_rel=ctx_rel, force=bool(args.force), scope=scope)
        stream = sys.stdout if result.get("ok") else sys.stderr
        stream.write(result["message"] + "\n")
        if args.json:
            print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1
    if args.review_cmd == "record":
        try:
            result = record_review(
                root,
                args.sha or "",
                findings=int(args.findings),
                context_rel=ctx_rel,
                scope=scope,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(result["message"])
        if args.json:
            print(json.dumps(result, indent=2))
        return 0
    if args.review_cmd == "set":
        from agentized.connect import pin_reviewer_agents

        data = set_reviewer_options(
            root,
            context_rel=ctx_rel,
            model=args.model,
            effort=args.effort,
            helper_model=args.helper_model,
            budget_max=args.budget_max,
            harness=getattr(args, "harness", None),
        )
        # Explicit model/effort change must rewrite agent files even if customized.
        pin_reviewer_agents(root, ctx_rel, force=True)
        rev = data.get("reviewer") or {}
        harness = getattr(args, "harness", None)
        if harness:
            h = (rev.get("harnesses") or {}).get(harness) or {}
            print(
                f"reviewer[{harness}] → model={h.get('model')} effort={h.get('effort')} "
                f"helper={rev.get('helper_model')} budget_max={rev.get('budget_max')}"
            )
        else:
            print(
                f"reviewer → model={rev.get('model')} effort={rev.get('effort')} "
                f"helper={rev.get('helper_model')} budget_max={rev.get('budget_max')}"
            )
        return 0
    print("usage: agentized review status|allow|record|reset|set", file=sys.stderr)
    return 2


def cmd_reporting(args: argparse.Namespace) -> int:
    from agentized.reporting import load_reporting, set_reporting_level

    root = find_repo_root()
    ctx_rel = getattr(args, "context", None) or load_state(root).get("context") or DEFAULT_CONTEXT
    if args.reporting_cmd == "show":
        data = load_reporting(root, ctx_rel)
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    if args.reporting_cmd == "set":
        try:
            data = set_reporting_level(root, args.level, context_rel=ctx_rel)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"reporting level → {data.get('level')}")
        return 0
    print("usage: agentized reporting show|set", file=sys.stderr)
    return 2


def cmd_process(args: argparse.Namespace) -> int:
    from agentized.process_control import claim_check
    from agentized.process_size import size_check

    root = find_repo_root()
    ctx_rel = getattr(args, "context", None) or load_state(root).get("context") or DEFAULT_CONTEXT
    if args.process_cmd == "size":
        result = size_check(root, context_rel=ctx_rel, base_ref=args.base)
        stream = sys.stdout if result["ok"] else sys.stderr
        stream.write(result["message"] + "\n")
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1
    if args.process_cmd == "claim":
        paths = list(args.paths or [])
        result = claim_check(root, paths or ["runtime/agentized/x.py"], context_rel=ctx_rel)
        stream = sys.stdout if result["ok"] else sys.stderr
        if result.get("message"):
            stream.write(result["message"] + "\n")
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1
    print("usage: agentized process size|claim", file=sys.stderr)
    return 2


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
        from agentized.architecture_gate import run_architecture_gate
        from agentized.coverage_check import run_coverage_check
        from agentized.mutation_ast import run_mutation
        from agentized.test_smells import run_test_smells

        # load_quality is imported at module scope; a local import here would
        # make it unbound for quality show (UnboundLocalError).
        cfg = load_quality(root, ctx_rel)
        gate_names = list((cfg.get("gates") or {}).get("ci") or [])
        # Always run coverage (module tests + thresholds) then optional warn gates, then mutation.
        ordered = gate_names or [
            "module_tests",
            "coverage",
            "test_smells",
            "architecture",
            "mutation",
        ]
        # coverage_check already runs module tests; map both names to it.
        ran_coverage = False
        for name in ordered:
            if name in {"mechanical"}:
                continue
            if name in {"module_tests", "coverage"}:
                if ran_coverage:
                    continue
                ran_coverage = True
                cov_rc = run_coverage_check(root, context=ctx_rel)
                if cov_rc != 0:
                    return cov_rc
                continue
            if name == "test_smells":
                smell_rc = run_test_smells(root, context=ctx_rel)
                if smell_rc != 0:
                    return smell_rc
                continue
            if name == "architecture":
                arch_rc = run_architecture_gate(root, context=ctx_rel)
                if arch_rc != 0:
                    return arch_rc
                continue
            if name == "mutation":
                mut_rc = run_mutation(root, context=ctx_rel)
                if mut_rc != 0:
                    return mut_rc
                continue
        if not ran_coverage:
            cov_rc = run_coverage_check(root, context=ctx_rel)
            if cov_rc != 0:
                return cov_rc
        if "mutation" not in ordered:
            return run_mutation(root, context=ctx_rel)
        return 0
    print("неизвестная подкоманда quality", file=sys.stderr)
    return 1


def cmd_new(args: argparse.Namespace) -> int:
    root = find_repo_root()
    ctx = _ctx(root, args, require_ready=True)
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
    print(f"создано: {_display_path(root, path)}")
    print(f"id: {task_id}")
    return 0


def cmd_claim(args: argparse.Namespace) -> int:
    root = find_repo_root()
    ctx = _ctx(root, args, require_ready=True)
    path = ctx / "tasks" / f"{args.task_id}.md"
    if not path.exists():
        print(f"нет задачи {args.task_id}", file=sys.stderr)
        return 1
    text = path.read_text(encoding="utf-8")
    text = set_field(text, "claim", args.owner)
    text = set_field(text, "статус", "in-progress")
    text = append_progress(text, f"claim by {args.owner}")
    path.write_text(text, encoding="utf-8")
    (ctx / "tasks" / "INDEX.md").write_text(rebuild_task_index(ctx / "tasks"), encoding="utf-8")
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
    print(f"progress appended → {_display_path(root, path)}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    root = find_repo_root()
    ctx = _ctx(root, args)
    path = ctx / "tasks" / f"{args.task_id}.md"
    if not path.exists():
        print(f"нет задачи {args.task_id}", file=sys.stderr)
        return 1
    if args.status not in ALL_STATUSES:
        print(
            f"неизвестный статус {args.status}; ожидалось одно из {ALL_STATUSES}", file=sys.stderr
        )
        return 1
    text = set_field(path.read_text(encoding="utf-8"), "статус", args.status)
    # AGE-73: append status stamp; dedupe identical last entry.
    text = append_status_progress(text, args.status)
    path.write_text(text, encoding="utf-8")
    (ctx / "tasks" / "INDEX.md").write_text(rebuild_task_index(ctx / "tasks"), encoding="utf-8")
    print(f"{args.task_id}: статус → {args.status} (файл не перемещался)")
    return 0


def cmd_tasks_validate(args: argparse.Namespace) -> int:
    root = find_repo_root()
    try:
        ref, result = run_tasks_validate(
            _ctx(root, args) / "tasks",
            repo_root=root,
            base_ref=getattr(args, "base", None) or None,
        )
    except RuntimeError as exc:
        print(f"tasks-validate FAIL: {exc}", file=sys.stderr)
        return 1
    if not result.ok:
        print("tasks-validate FAIL", file=sys.stderr)
        print(*(f"  ERROR: {e}" for e in result.errors), sep="\n", file=sys.stderr)
        return 1
    print(f"tasks-validate OK (base={ref})")
    return 0


def cmd_board(args: argparse.Namespace) -> int:
    from agentized.board_html import BoardError, write_board

    root = find_repo_root()
    out = Path(args.output) if args.output else (root / "board.html")
    if not out.is_absolute():
        out = root / out
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if args.stamp else None
    try:
        path = write_board(
            _ctx(root, args) / "tasks",
            out,
            generated_at=stamp,
            title=args.title or "Доска задач Agentized",
            lang=getattr(args, "lang", None) or "ru",
            now=datetime.now(timezone.utc),
        )
    except BoardError as exc:
        print(f"board FAIL: {exc}", file=sys.stderr)
        return 1
    rel = path.relative_to(root) if path.is_relative_to(root) else path
    print(f"board: {rel}")
    return 0


def cmd_index(args: argparse.Namespace) -> int:
    from agentized.autopilot import write_metrics

    root = find_repo_root()
    try:
        ctx = _ctx(root, args)
        ctx_rel = _context_rel(root, args)
        tasks_index_path = path_under(ctx, "tasks", "INDEX.md")
        leases_index_path = path_under(ctx, "leases", "INDEX.md")
        tasks_dir = tasks_index_path.parent
        leases_dir = leases_index_path.parent
        tasks_index = rebuild_task_index(tasks_dir)
        leases_index = rebuild_lease_index(leases_dir)
        tasks_index_path.write_text(tasks_index, encoding="utf-8")
        leases_index_path.write_text(leases_index, encoding="utf-8")
        metrics = write_metrics(root, context_rel=ctx_rel)
    except (OSError, ValueError, TypeError, OverflowError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("пересобраны:")
    print(f"  {_display_path(root, ctx / 'tasks' / 'INDEX.md')}")
    print(f"  {_display_path(root, ctx / 'leases' / 'INDEX.md')}")
    print(f"  {metrics['path']}")

    if args.print:
        print("\n--- tasks/INDEX.md ---\n")
        print(tasks_index)
    return 0


def cmd_autopilot(args: argparse.Namespace) -> int:
    """WIP autopilot + metrics. Does not own ``agentized board`` (HTML renderer)."""
    from agentized.autopilot import (
        load_board,
        load_metrics_file,
        pick_next_task,
        set_wip_limit,
        write_metrics,
    )

    root = find_repo_root()
    try:
        ctx = _ctx(root, args)
        ctx_rel = _context_rel(root, args)
        if args.autopilot_cmd == "show":
            data = load_board(root, ctx_rel)
            print(json.dumps(data, ensure_ascii=False, indent=2))
            return 0
        if args.autopilot_cmd == "set-wip":
            data = set_wip_limit(root, int(args.limit), context_rel=ctx_rel)
            print(f"wip_limit → {data.get('wip_limit')}")
            return 0
        if args.autopilot_cmd == "refresh":
            result = write_metrics(root, context_rel=ctx_rel)
            print(f"metrics → {result['path']}")
            if args.json:
                print(json.dumps(result["metrics"], ensure_ascii=False, indent=2))
            return 0
        if args.autopilot_cmd == "metrics":
            if args.refresh:
                data = write_metrics(root, context_rel=ctx_rel)["metrics"]
            else:
                data = load_metrics_file(root, ctx_rel)
            print(json.dumps(data, ensure_ascii=False, indent=2))
            return 0
        if args.autopilot_cmd == "next":
            cfg = load_board(root, ctx_rel)
            pick = pick_next_task(
                list_tasks(path_under(ctx, "tasks")),
                cfg,
                now=datetime.now(timezone.utc),
            )
            if args.json:
                print(json.dumps(pick, ensure_ascii=False, indent=2))
            elif pick.get("task"):
                task = pick["task"]
                print(
                    f"next: {task['id']} — {task['title']} "
                    f"(WIP {pick['wip_current']}/{pick['wip_limit']})"
                )
            else:
                print(f"next: none ({pick.get('reason')})")
            return 0
    except (OSError, ValueError, TypeError, OverflowError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(
        "usage: agentized autopilot show|set-wip|next|metrics|refresh",
        file=sys.stderr,
    )
    return 2


def cmd_check(args: argparse.Namespace) -> int:
    root = find_repo_root()
    layout = _layout(root, args)
    ctx = layout.registry_root
    code_ctx = layout.code_context
    errors: list[str] = []
    warnings: list[str] = []

    if not (root / "AGENTS.md").exists():
        errors.append("нет AGENTS.md")
    else:
        agents = (root / "AGENTS.md").read_text(encoding="utf-8")
        if "NAV.md" not in agents:
            errors.append("AGENTS.md без указателя на NAV.md — нужен connect")
    if not layout.nav_path().exists():
        errors.append(f"нет NAV.md at {_display_path(root, layout.nav_path())}")
    for required in ("tasks/INDEX.md", "leases/INDEX.md"):
        if not (ctx / required).exists():
            errors.append(f"нет {_display_path(root, ctx / required)}")
    # process-control.json missing is a hard error (fail-closed) — not a soft warning.
    for required in ("skills", "hooks", "quality.json", "process-control.json"):
        if not (code_ctx / required).exists():
            errors.append(f"нет {_display_path(root, code_ctx / required)} (code-repo config)")
    if layout.is_external:
        from agentized.context_layout import external_clone_problems

        for problem in external_clone_problems(layout):
            errors.append(problem)
    if not (code_ctx / "skills" / "quality-gates" / "SKILL.md").exists():
        warnings.append("нет pinned skill quality-gates — запустите connect")

    # live index freshness (soft): statuses in INDEX vs files
    from agentized.task_schema import (
        unknown_depends_on_ids,
        validate_kind_priority,
        validate_task_status,
    )
    from agentized.tasks import dependency_cycles_for_dir

    tasks = list_tasks(ctx / "tasks")
    index_path = ctx / "tasks" / "INDEX.md"
    index_text = index_path.read_text(encoding="utf-8") if index_path.exists() else ""
    for t in tasks:
        for err in validate_task_status(t.status):
            errors.append(f"{t.task_id}: {err}")
        if t.status in ACTIVE_STATUSES and t.task_id not in index_text:
            warnings.append(f"задача {t.task_id} активна, но нет в INDEX — запустите index")
        for err in validate_kind_priority(t.kind, t.priority):
            errors.append(f"{t.task_id}: {err}")
    for cycle in dependency_cycles_for_dir(ctx / "tasks"):
        errors.append("depends_on cycle: " + " → ".join(cycle))
    for tid, dep in unknown_depends_on_ids(tasks):
        errors.append(f"{tid}: unknown depends_on {dep!r}")

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
    print(f"  placement: {layout.placement}")
    print(f"  registry: {_display_path(root, ctx)}")
    print(f"  code config: {_display_path(root, code_ctx)}")
    for w in warnings:
        print(f"  WARN: {w}")
    if args.json:
        print(
            json.dumps(
                {
                    "ok": True,
                    "warnings": warnings,
                    "state": state,
                    "placement": layout.placement,
                    "registry": str(ctx),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
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
            print(
                f"{lease.task_id} owner={lease.owner} paths={', '.join(lease.paths)} expires={lease.expires}"
            )
        return 0

    if args.lease_cmd == "acquire":
        overlaps = find_overlaps(list_leases(leases_dir), args.paths, ignore_task=args.task_id)
        if overlaps:
            print(warn_message(overlaps))
            print("(запись не блокируется)")
        text = render_lease_file(args.task_id, args.owner, args.paths)
        path = leases_dir / f"{args.task_id}.md"
        path.write_text(text, encoding="utf-8")
        (leases_dir / "INDEX.md").write_text(rebuild_lease_index(leases_dir), encoding="utf-8")
        print(f"lease acquired: {_display_path(root, path)}")
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
    layout = _layout(root, args)
    ctx = layout.registry_root
    state = load_state(root)
    tasks = list_tasks(ctx / "tasks")
    active = [t for t in tasks if t.status in ACTIVE_STATUSES]
    leases = list_leases(ctx / "leases")
    print("sync-status")
    print(f"  connected: {'yes' if state else 'no'}")
    print(f"  placement: {layout.placement}")
    print(f"  registry: {_display_path(root, ctx)}/")
    print(f"  code config: {_display_path(root, layout.code_context)}/")
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


def cmd_adr(args: argparse.Namespace) -> int:
    from agentized.adr import create_adr

    root = find_repo_root()
    ctx = _ctx(root, args)
    decisions = ctx / "decisions"
    tasks = [t.strip() for t in (args.tasks or "").split(",") if t.strip()]
    try:
        path = create_adr(decisions, args.title, status=args.status, tasks=tasks)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    try:
        rel = str(path.relative_to(root))
    except ValueError:
        rel = str(path)
    print(f"ADR: {rel}")
    return 0


def cmd_import_orbit(args: argparse.Namespace) -> int:
    from agentized.orbit_import import format_report, import_orbit_tasks

    root = find_repo_root()
    ctx = _ctx(root, args)
    source = Path(args.source)
    if not source.is_absolute():
        source = (root / source).resolve()
    dry_run = not bool(args.write)
    report = import_orbit_tasks(source, ctx / "tasks", dry_run=dry_run)
    print(format_report(report), end="")
    if args.json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    if report.errors:
        return 1
    return 0 if report.would_write else 1


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
    print(f"digest: {_display_path(root, path)}")
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

    rv = sub.add_parser("review", help="Strong reviewer budget + watermark")
    rv_sub = rv.add_subparsers(dest="review_cmd", required=True)
    rvs = rv_sub.add_parser("status", help="Show budget / watermark / model")
    rvs.add_argument("--context", default=None)
    rvs.add_argument(
        "--scope", default=None, help="Task/PR identity (default or AGENTIZED_REVIEW_SCOPE)"
    )
    rva = rv_sub.add_parser("allow", help="May the main agent call the reviewer now?")
    rva.add_argument("--force", action="store_true")
    rva.add_argument("--context", default=None)
    rva.add_argument("--scope", default=None)
    rva.add_argument("--json", action="store_true")
    rvr = rv_sub.add_parser("record", help="Record Reviewed commit watermark")
    rvr.add_argument("--sha", required=True)
    rvr.add_argument("--findings", type=int, default=0)
    rvr.add_argument("--context", default=None)
    rvr.add_argument("--scope", default=None)
    rvr.add_argument("--json", action="store_true")
    rvrst = rv_sub.add_parser("reset", help="Reset budget/watermark for a task/PR scope")
    rvrst.add_argument("--scope", default=None)
    rvrst.add_argument("--json", action="store_true")
    rvset = rv_sub.add_parser("set", help="Override reviewer model/effort/budget in quality.json")
    rvset.add_argument("--model", default=None)
    rvset.add_argument("--effort", default=None)
    rvset.add_argument("--helper-model", dest="helper_model", default=None)
    rvset.add_argument("--budget-max", dest="budget_max", type=int, default=None)
    rvset.add_argument(
        "--harness",
        choices=["cursor", "claude", "codex"],
        default=None,
        help="set model/effort for one harness (cursor/claude/codex)",
    )
    rvset.add_argument("--context", default=None)
    rv.set_defaults(func=cmd_review)

    rp = sub.add_parser("reporting", help="Acceptance handoff level (short|technical)")
    rp_sub = rp.add_subparsers(dest="reporting_cmd", required=True)
    rps = rp_sub.add_parser("show", help="Show context/reporting.json")
    rps.add_argument("--context", default=None)
    rpset = rp_sub.add_parser("set", help="Set reporting level")
    rpset.add_argument("--level", required=True, choices=["short", "technical"])
    rpset.add_argument("--context", default=None)
    rp.set_defaults(func=cmd_reporting)

    pc = sub.add_parser("process", help="Claim-before-edits + reviewable PR size")
    pc_sub = pc.add_subparsers(dest="process_cmd", required=True)
    pcs = pc_sub.add_parser(
        "size", help="Diff insertions vs base (warn ≥warn_at; hard-fail over >limit, inclusive)"
    )
    pcs.add_argument("--base", default=None, help="git base ref (default origin/main)")
    pcs.add_argument("--context", default=None)
    pcs.add_argument("--json", action="store_true")
    pcc = pc_sub.add_parser("claim", help="Require in-progress claim before watched paths")
    pcc.add_argument("paths", nargs="*", help="paths that would be edited")
    pcc.add_argument("--context", default=None)
    pcc.add_argument("--json", action="store_true")
    pc.set_defaults(func=cmd_process)

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

    tv = sub.add_parser("tasks-validate", help="Hard status gates on context/tasks")
    tv.add_argument("--context", default=None)
    tv.add_argument("--base", default=None)
    tv.set_defaults(func=cmd_tasks_validate)

    bd = sub.add_parser("board", help="Render static board.html from context/tasks")
    bd.add_argument("--output", "-o", default="board.html")
    bd.add_argument("--stamp", action="store_true")
    bd.add_argument("--title", default="Доска задач Agentized")
    bd.add_argument("--lang", default="ru", choices=["ru", "en"])
    bd.add_argument("--context", default=None)
    bd.set_defaults(func=cmd_board)

    ix = sub.add_parser("index", help="Пересобрать живые индексы tasks/leases + board metrics")
    ix.add_argument("--context", default=None)
    ix.add_argument("--print", action="store_true")
    ix.set_defaults(func=cmd_index)

    ap = sub.add_parser(
        "autopilot",
        help="WIP autopilot + board metrics (dashboard data; not HTML board render)",
    )
    ap_sub = ap.add_subparsers(dest="autopilot_cmd", required=True)
    aps = ap_sub.add_parser("show", help="Show context/board.json")
    aps.add_argument("--context", default=None)
    apw = ap_sub.add_parser("set-wip", help="Set configurable WIP limit")
    apw.add_argument("limit", type=int)
    apw.add_argument("--context", default=None)
    apn = ap_sub.add_parser("next", help="Recommend next queue/open task under WIP")
    apn.add_argument("--context", default=None)
    apn.add_argument("--json", action="store_true")
    apm = ap_sub.add_parser("metrics", help="Show board/metrics.json (--refresh to recompute)")
    apm.add_argument("--context", default=None)
    apm.add_argument("--refresh", action="store_true")
    apr = ap_sub.add_parser("refresh", help="Write context/board/metrics.json")
    apr.add_argument("--context", default=None)
    apr.add_argument("--json", action="store_true")
    ap.set_defaults(func=cmd_autopilot)

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

    from agentized.adr import ADR_STATUSES

    adr = sub.add_parser("adr", help="Create ADR (YAML front matter)")
    adr.add_argument("--title", required=True)
    adr.add_argument("--status", default="proposed", choices=ADR_STATUSES)
    adr.add_argument("--tasks", default="", help="comma-separated T-YYMMDD-xxxx ids")
    adr.add_argument("--context", default=None)
    adr.set_defaults(func=cmd_adr)

    imp = sub.add_parser(
        "import-orbit",
        help="Import orbit-tasks fixtures (dry-run default)",
    )
    imp.add_argument("--source", required=True, help="fixture path")
    imp.add_argument(
        "--write",
        action="store_true",
        help="write task files",
    )
    imp.add_argument("--context", default=None)
    imp.add_argument("--json", action="store_true")
    imp.set_defaults(func=cmd_import_orbit)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
