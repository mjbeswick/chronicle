from __future__ import annotations

from datetime import date

from textual import on
from textual.app import ComposeResult
from textual.containers import Container
from textual.message import Message
from textual.widgets import Tree

from app.models import TimelineDay, TimelineEvent


def _format_day(day: date) -> str:
    return day.strftime("%A, %b %-d")


def _format_event_label(event: TimelineEvent) -> str:
    icon = "✎" if event.source == "entry" else "•"
    details = event.details.replace("\n", " ").strip()
    if len(details) > 70:
        details = f"{details[:67]}..."
    return f"{event.occurred_at.strftime('%H:%M')} {icon} {event.title} — {details}"


class JournalView(Container):
    class SelectionChanged(Message):
        def __init__(self, event: TimelineEvent | None) -> None:
            self.timeline_event = event
            super().__init__()

    def compose(self) -> ComposeResult:
        tree = Tree("Journal timeline", id="journal-tree")
        tree.show_root = False
        yield tree

    def refresh_view(self, days: list[TimelineDay]) -> None:
        tree = self.query_one(Tree)
        tree.clear()
        for day in days:
            day_node = tree.root.add(_format_day(day.label), expand=True, data=None)
            for event in day.events:
                day_node.add_leaf(_format_event_label(event), data=event)
        self.call_after_refresh(tree.root.expand_all)
        if tree.root.children:
            tree.select_node(tree.root.children[0])
            first_leaf = next(iter(tree.root.children[0].children), None)
            if first_leaf is not None:
                tree.select_node(first_leaf)
                tree.focus()
                self.post_message(self.SelectionChanged(first_leaf.data))

    def selected_event(self) -> TimelineEvent | None:
        node = self.query_one(Tree).cursor_node
        if node is None:
            return None
        data = getattr(node, "data", None)
        return data if isinstance(data, TimelineEvent) else None

    def focus_content(self) -> None:
        self.query_one(Tree).focus()

    @on(Tree.NodeHighlighted)
    def _on_highlight(self, event: Tree.NodeHighlighted) -> None:
        data = event.node.data if isinstance(event.node.data, TimelineEvent) else None
        self.post_message(self.SelectionChanged(data))
