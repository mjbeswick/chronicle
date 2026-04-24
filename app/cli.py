"""Headless CLI for Chronicle.

Thin dispatcher on top of ChronicleStorageAdapter. No Textual import.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from typing import Sequence

from app.filter import FilterSpec, matches_date, matches_tag, matches_text
from app.forms import parse_at
from app.models import Item, utc_now
from app.storage import ChronicleStorageAdapter
from app.utils import parse_due_date


SUBCOMMANDS = {"add", "list", "show", "done", "rm"}


# ---------------------------------------------------------------------- utils


def _die(msg: str, code: int = 2) -> "NoReturn":  # type: ignore[name-defined]
    print(msg, file=sys.stderr)
    sys.exit(code)


def _resolve_item_id(store: ChronicleStorageAdapter, prefix: str) -> str:
    """Return the full item id matching a unique prefix, else exit 2."""
    items = store.list_items()
    candidates = [i for i in items if i.id == prefix or i.id.startswith(prefix)]
    # Also match when user gives just the hex suffix (no "item_" prefix).
    if not candidates:
        candidates = [i for i in items if i.id.endswith(prefix) or i.id[5:].startswith(prefix)]
    if not candidates:
        _die(f"No item matching '{prefix}'.")
    if len(candidates) > 1:
        lines = [f"Ambiguous prefix '{prefix}' — {len(candidates)} matches:"]
        for c in candidates[:10]:
            lines.append(f"  {c.id}  {c.title}")
        _die("\n".join(lines))
    return candidates[0].id


def _short(item_id: str) -> str:
    return item_id.removeprefix("item_")[:8]


def _glyph(item: Item, now: datetime) -> str:
    if item.is_done:
        return "☑"
    if item.at and item.at > now:
        return "●"
    return "◆"


# ---------------------------------------------------------------- formatting


def _format_list_row(item: Item, now: datetime) -> str:
    parts = [_short(item.id), f"{_glyph(item, now)} {item.title}"]
    when: str | None = None
    if item.due:
        when = f"due {item.due.isoformat()}"
    elif item.at:
        when = item.at.astimezone().strftime("%Y-%m-%d %H:%M")
    if when:
        parts.append(when)
    if item.tags:
        parts.append(" ".join(f"#{t}" for t in item.tags))
    return "  ".join(parts)


def _format_show(item: Item) -> str:
    created = item.created_at.astimezone().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"id:      {item.id}",
        f"title:   {item.title}",
        f"created: {created}",
    ]
    if item.at:
        lines.append(f"at:      {item.at.astimezone().strftime('%Y-%m-%d %H:%M')}")
    if item.due:
        lines.append(f"due:     {item.due.isoformat()}")
    if item.done_at:
        lines.append(f"done:    {item.done_at.astimezone().strftime('%Y-%m-%d %H:%M')}")
    if item.parent_id:
        lines.append(f"parent:  {item.parent_id}")
    if item.tags:
        lines.append(f"tags:    {', '.join(item.tags)}")
    lines.append("")
    lines.append(item.body or "(no body)")
    return "\n".join(lines)


# --------------------------------------------------------------- subcommands


def _cmd_add(args: argparse.Namespace, store: ChronicleStorageAdapter) -> int:
    at_val: datetime | None = None
    if args.at:
        at_val = parse_at(args.at)
        if at_val is None:
            _die(f"Unrecognised --at value: {args.at!r}", code=1)

    due_val: date | None = None
    if args.due:
        due_val = parse_due_date(args.due)
        if due_val is None:
            _die(f"Unrecognised --due value: {args.due!r}", code=1)

    tags = [t.strip() for t in (args.tags or "").split(",") if t.strip()]

    parent_id: str | None = None
    if args.parent:
        parent_id = _resolve_item_id(store, args.parent)

    item = store.create_item(
        title=args.title,
        body=args.body or "",
        tags=tags,
        parent_id=parent_id,
        at=at_val,
        due=due_val,
    )
    if args.done:
        store.toggle_done(item.id)
    print(item.id)
    return 0


def _lens_filter(items: list[Item], lens: str) -> list[Item]:
    now = utc_now()
    if lens == "journal":
        return [i for i in items if i.in_journal(now)]
    if lens == "todos":
        return [i for i in items if i.in_todos(now) or i.is_done]
    if lens == "notes":
        return [i for i in items if i.in_notes()]
    if lens == "calendar":
        return [i for i in items if i.in_calendar()]
    return items


def _cmd_list(args: argparse.Namespace, store: ChronicleStorageAdapter) -> int:
    items = _lens_filter(store.list_items(), args.lens)

    if args.done and args.open:
        _die("--done and --open are mutually exclusive.", code=1)
    if args.done:
        items = [i for i in items if i.is_done]
    elif args.open:
        items = [i for i in items if not i.is_done]

    date_from: date | None = None
    date_to: date | None = None
    if args.from_:
        date_from = parse_due_date(args.from_)
        if date_from is None:
            _die(f"Unrecognised --from value: {args.from_!r}", code=1)
    if args.to:
        date_to = parse_due_date(args.to)
        if date_to is None:
            _die(f"Unrecognised --to value: {args.to!r}", code=1)

    spec = FilterSpec(
        text=args.text or "",
        tag=args.tag,
        date_from=date_from,
        date_to=date_to,
    )
    if spec.is_active:
        now = utc_now()
        def _anchor_date(i: Item) -> date | None:
            if i.due:
                return i.due
            if i.at:
                return i.at.astimezone().date()
            return None
        items = [
            i for i in items
            if matches_text(spec, i.title, i.body)
            and matches_tag(spec, i.tags)
            and matches_date(spec, _anchor_date(i))
        ]

    if args.json:
        print(json.dumps([i.to_dict() for i in items], indent=2))
        return 0

    if not items:
        print("(no items)")
        return 0
    now = utc_now()
    for i in items:
        print(_format_list_row(i, now))
    return 0


def _cmd_show(args: argparse.Namespace, store: ChronicleStorageAdapter) -> int:
    item_id = _resolve_item_id(store, args.id)
    item = next(i for i in store.list_items() if i.id == item_id)
    if args.json:
        print(json.dumps(item.to_dict(), indent=2))
    else:
        print(_format_show(item))
    return 0


def _cmd_done(args: argparse.Namespace, store: ChronicleStorageAdapter) -> int:
    item_id = _resolve_item_id(store, args.id)
    updated = store.toggle_done(item_id)
    print(f"{_short(item_id)}  {'done' if updated.is_done else 'reopened'}")
    return 0


def _cmd_rm(args: argparse.Namespace, store: ChronicleStorageAdapter) -> int:
    item_id = _resolve_item_id(store, args.id)
    item = next(i for i in store.list_items() if i.id == item_id)
    if not args.yes:
        resp = input(f"Delete '{item.title}' ({_short(item_id)})? [y/N] ").strip().lower()
        if resp not in ("y", "yes"):
            print("Cancelled.")
            return 0
    store.delete_item(item_id)
    print(f"{_short(item_id)}  deleted")
    return 0


# ------------------------------------------------------------------- parser


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="chronicle",
        description="Chronicle — journal, todos, notes, calendar. Run with no args for the TUI.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="Create a new item.")
    a.add_argument("title")
    a.add_argument("--body", help="Body text.")
    a.add_argument("--at", help="Anchor datetime: now, today, yesterday, YYYY-MM-DD[ HH:MM].")
    a.add_argument("--due", help="Due date: today, tomorrow, in N days, YYYY-MM-DD.")
    a.add_argument("--tags", help="Comma-separated tags.")
    a.add_argument("--parent", help="Parent item id or prefix.")
    a.add_argument("--done", action="store_true", help="Mark done on creation.")

    l = sub.add_parser("list", help="List items.")
    l.add_argument("--lens", choices=["journal", "todos", "notes", "calendar", "all"], default="all")
    l.add_argument("--tag")
    l.add_argument("--text")
    l.add_argument("--from", dest="from_", help="Filter: date lower bound.")
    l.add_argument("--to", help="Filter: date upper bound.")
    l.add_argument("--done", action="store_true")
    l.add_argument("--open", action="store_true")
    l.add_argument("--json", action="store_true")

    s = sub.add_parser("show", help="Show one item by id or prefix.")
    s.add_argument("id")
    s.add_argument("--json", action="store_true")

    d = sub.add_parser("done", help="Toggle done state.")
    d.add_argument("id")

    r = sub.add_parser("rm", help="Delete an item (prompts unless --yes).")
    r.add_argument("id")
    r.add_argument("--yes", action="store_true")

    return p


# --------------------------------------------------------------------- entry


HANDLERS = {
    "add": _cmd_add,
    "list": _cmd_list,
    "show": _cmd_show,
    "done": _cmd_done,
    "rm": _cmd_rm,
}


def run(argv: Sequence[str]) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv))
    store = ChronicleStorageAdapter()
    return HANDLERS[args.cmd](args, store)
