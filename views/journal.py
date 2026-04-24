from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from itertools import groupby

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.message import Message
from textual.widgets import DataTable, Markdown, Static, Tree

from app.filter import FilterSpec, matches_date, matches_tag, matches_text
from app.models import Item, utc_now
from app.voice import ViewVoiceHoldHandler


@dataclass
class _Day:
    label: date
    items: list[Item] = field(default_factory=list)


def _group_items_by_day(items: list[Item]) -> list[_Day]:
    """Bucket items by `timeline_at.date()`, newest day first."""
    now = utc_now()
    keyed = sorted(
        items,
        key=lambda i: i.timeline_at(now),
        reverse=True,
    )
    buckets: list[_Day] = []
    for day, group in groupby(keyed, key=lambda i: i.timeline_at(now).astimezone().date()):
        buckets.append(_Day(label=day, items=list(group)))
    return buckets


def _row_title(item: Item, now) -> Text:
    if item.is_done:
        glyph = "☑"
    elif item.at and item.at > now:
        glyph = "●"  # scheduled
    else:
        glyph = "◆"  # recorded
    return Text(f"{glyph} {item.title}")


class JournalSidebar(Vertical):
    """Dates tree for navigating journal items."""

    DEFAULT_CSS = """
    JournalSidebar {
        width: 24;
        border-right: tall $primary-darken-3;
        padding: 0;
        overflow-y: auto;
        overflow-x: hidden;
    }
    JournalSidebar #dates-tree {
        height: 1fr;
        padding: 0;
    }
    """

    class DaySelected(Message):
        def __init__(self, day: _Day) -> None:
            self.day = day
            super().__init__()

    def compose(self) -> ComposeResult:
        tree: Tree[_Day] = Tree("", id="dates-tree")
        tree.show_root = False
        tree.show_guides = False
        yield tree

    def refresh_dates(self, days: list[_Day]) -> None:
        tree = self.query_one("#dates-tree", Tree)
        tree.clear()
        by_year = groupby(days, key=lambda d: d.label.year)
        for year, year_days in by_year:
            by_month = groupby(year_days, key=lambda d: d.label.month)
            for month, month_days in by_month:
                month_label = date(year, month, 1).strftime("%B %Y")
                month_node = tree.root.add(month_label, expand=True, data=None)
                for day in month_days:
                    month_node.add_leaf(day.label.strftime("%A %-d"), data=day)

    def select_first(self) -> None:
        tree = self.query_one("#dates-tree", Tree)
        tree.root.expand_all()
        first_leaf = self._first_leaf(tree.root)
        if first_leaf is not None:
            tree.select_node(first_leaf)
            if isinstance(first_leaf.data, _Day):
                self.post_message(self.DaySelected(first_leaf.data))

    def focus_tree(self) -> None:
        self.query_one("#dates-tree", Tree).focus()

    def _first_leaf(self, node):
        for child in node.children:
            if not child.allow_expand:
                return child
            result = self._first_leaf(child)
            if result is not None:
                return result
        return None

    @on(Tree.NodeHighlighted)
    def _on_tree_highlight(self, event: Tree.NodeHighlighted) -> None:
        if isinstance(event.node.data, _Day):
            self.post_message(self.DaySelected(event.node.data))


class JournalView(Container):
    DEFAULT_CSS = """
    JournalView {
        layout: vertical;
    }
    JournalView #journal-filter-banner {
        height: auto;
        padding: 0 1;
        color: $text;
        background: $warning-darken-2;
        display: none;
    }
    JournalView #journal-body {
        height: 1fr;
        layout: horizontal;
    }
    JournalView #journal-right {
        width: 1fr;
        height: 1fr;
        layout: vertical;
    }
    JournalView #journal-table {
        width: 1fr;
        height: 1fr;
        overflow-x: hidden;
    }
    JournalView #journal-content-pane {
        width: 1fr;
        height: 1fr;
        layout: vertical;
    }
    JournalView.-layout-dates_table_content #journal-content-pane {
        border-top: tall $primary-darken-3;
    }
    JournalView.-layout-three_col #journal-content-pane {
        border-left: tall $primary-darken-3;
    }
    JournalView.-layout-three_col #journal-right {
        layout: horizontal;
    }
    JournalView.-layout-dates_table_content #journal-table {
        height: 40%;
    }
    JournalView #journal-content {
        height: 1fr;
        padding: 0 1;
    }
    JournalView #journal-tags-display {
        height: auto;
        padding: 0 1 1 1;
        color: $text-muted;
    }
    JournalView #journal-empty {
        content-align: center middle;
        color: $text-muted;
        width: 1fr;
        height: 1fr;
        display: none;
    }
    """

    _LAYOUTS = ("dates_table_content", "dates_table", "three_col", "table_only")
    _LAYOUT_LABELS = {
        "dates_table_content": "Dates | Table / Content",
        "dates_table": "Dates | Table",
        "three_col": "Dates | Table | Content",
        "table_only": "Table only",
    }

    class SelectionChanged(Message):
        def __init__(self, item: Item | None) -> None:
            self.item = item
            super().__init__()

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._items: list[Item] = []
        self._days: list[_Day] = []
        self._selected_day: _Day | None = None
        self._tree_visible = True
        self._content_visible = True
        self._layout_mode = "dates_table_content"
        self._filter: FilterSpec = FilterSpec()
        self._voice = ViewVoiceHoldHandler(
            self, on_transcript=lambda t: self.app.voice_create_for_active_tab(t)
        )
        self.add_class(f"-layout-{self._layout_mode}")

    def cycle_layout(self) -> None:
        idx = self._LAYOUTS.index(self._layout_mode)
        self._layout_mode = self._LAYOUTS[(idx + 1) % len(self._LAYOUTS)]
        self._apply_layout_mode()
        try:
            self.app.notify(f"Layout: {self._LAYOUT_LABELS[self._layout_mode]}", timeout=1.2)
        except Exception:
            pass

    def _apply_layout_mode(self) -> None:
        try:
            sidebar = self.query_one(JournalSidebar)
            content_pane = self.query_one("#journal-content-pane", Vertical)
        except Exception:
            return

        mode = self._layout_mode
        sidebar.display = mode != "table_only"
        content_pane.display = mode in ("dates_table_content", "three_col")

        for cls in list(self.classes):
            if cls.startswith("-layout-"):
                self.remove_class(cls)
        self.add_class(f"-layout-{mode}")

    def on_key(self, event) -> None:
        if self._voice.handle_key(event):
            event.stop()
            return
        if event.key in ("left", "right"):
            if self._move_panel_focus(1 if event.key == "right" else -1):
                event.stop()
                event.prevent_default()

    def _panel_focus_order(self) -> list:
        ids = ["dates-tree", "journal-table"]
        if self._layout_mode in ("dates_table_content", "three_col"):
            ids.append("journal-content")
        widgets = []
        for wid in ids:
            try:
                widgets.append(self.query_one(f"#{wid}"))
            except Exception:
                continue
        return widgets

    def _move_panel_focus(self, direction: int) -> bool:
        panels = self._panel_focus_order()
        if len(panels) < 2:
            return False
        focused = self.app.focused
        idx = None
        for i, w in enumerate(panels):
            if focused is w or (focused is not None and w in focused.ancestors):
                idx = i
                break
        if idx is None:
            panels[0].focus()
            return True
        next_idx = idx + direction
        if 0 <= next_idx < len(panels):
            panels[next_idx].focus()
            return True
        return False

    def compose(self) -> ComposeResult:
        yield Static("", id="journal-filter-banner")
        with Horizontal(id="journal-body"):
            yield JournalSidebar()
            with Container(id="journal-right"):
                table = DataTable(id="journal-table", cursor_type="row", zebra_stripes=True)
                table.add_column("Time", width=5)
                table.add_column("Title")
                yield table
                with Vertical(id="journal-content-pane"):
                    yield Markdown("", id="journal-content")
                    yield Static("", id="journal-tags-display")
        yield Static("No entries yet — press [bold]n[/] to create one", id="journal-empty")

    def refresh_view(self, items: list[Item]) -> None:
        self._items = items
        self._apply_view()

    def all_tags(self) -> list[str]:
        return sorted({tag for i in self._items for tag in i.tags})

    def apply_filter(self, spec: FilterSpec) -> None:
        self._filter = spec
        banner = self.query_one("#journal-filter-banner", Static)
        if spec.is_active:
            banner.update(Text.assemble(
                ("Filter: ", "bold"),
                (spec.summary(), ""),
                (" - f to change, ^f to clear", "dim"),
            ))
            banner.display = True
        else:
            banner.display = False
        self._apply_view()

    def _filtered_items(self) -> list[Item]:
        if not self._filter.is_active:
            return self._items
        now = utc_now()
        result = []
        for item in self._items:
            if not matches_text(self._filter, item.title, item.body):
                continue
            if not matches_tag(self._filter, item.tags):
                continue
            if not matches_date(self._filter, item.timeline_at(now).astimezone().date()):
                continue
            result.append(item)
        return result

    def _apply_view(self) -> None:
        filtered = self._filtered_items()
        self._days = _group_items_by_day(filtered)

        sidebar = self.query_one(JournalSidebar)
        body = self.query_one("#journal-body", Horizontal)
        empty = self.query_one("#journal-empty", Static)

        if not self._days:
            body.display = False
            empty.display = True
            self.post_message(self.SelectionChanged(None))
            sidebar.refresh_dates([])
            return

        body.display = True
        empty.display = False
        sidebar.refresh_dates(self._days)
        self._apply_layout_mode()
        self.call_after_refresh(sidebar.select_first)

    def _populate_table(self, day: _Day | None) -> None:
        self._selected_day = day
        table = self.query_one("#journal-table", DataTable)
        table.clear()

        if day is None or not day.items:
            self.post_message(self.SelectionChanged(None))
            self._show_content(None)
            return

        now = utc_now()
        for item in day.items:
            time_str = item.timeline_at(now).astimezone().strftime("%H:%M")
            time_cell = Text(time_str, style="" if not item.is_done else "dim")
            title_cell = _row_title(item, now)
            if item.is_done:
                title_cell.stylize("dim")
            table.add_row(time_cell, title_cell)

        table.move_cursor(row=0)
        self.post_message(self.SelectionChanged(day.items[0]))
        self._show_content(day.items[0])

    def _show_content(self, item: Item | None) -> None:
        markdown = self.query_one("#journal-content", Markdown)
        tags_display = self.query_one("#journal-tags-display", Static)
        if item is None:
            markdown.update("")
            tags_display.update("")
            return
        markdown.update(item.body or "_No body._")
        if item.tags:
            tag_text = Text()
            for i, tag in enumerate(item.tags):
                if i > 0:
                    tag_text.append("  ")
                tag_text.append(f"#{tag}", style="bold $accent")
            tags_display.update(tag_text)
        else:
            tags_display.update("")

    def selected_item(self) -> Item | None:
        if self._selected_day is None:
            return None
        table = self.query_one("#journal-table", DataTable)
        row = table.cursor_row
        items = self._selected_day.items
        if not items or row is None or row >= len(items):
            return None
        return items[row]

    def focus_content(self) -> None:
        self.query_one(JournalSidebar).focus_tree()

    def toggle_tree(self) -> None:
        self._tree_visible = not self._tree_visible
        self.query_one(JournalSidebar).display = self._tree_visible

    def toggle_content(self) -> None:
        self._content_visible = not self._content_visible
        content = self.query_one("#journal-content", Markdown)
        content.display = self._content_visible
        table = self.query_one("#journal-table", DataTable)
        table.styles.height = "40%" if self._content_visible else "1fr"

    def show_content(self) -> None:
        if not self._content_visible:
            self.toggle_content()

    def on_resize(self, event) -> None:
        self._fit_title_column()

    def _fit_title_column(self) -> None:
        try:
            table = self.query_one("#journal-table", DataTable)
        except Exception:
            return
        cols = list(table.columns.values())
        if len(cols) < 2:
            return
        time_col, title_col = cols[0], cols[1]
        avail = table.size.width - time_col.width - 3
        if avail <= 0:
            return
        title_col.auto_width = False
        title_col.width = avail
        table.refresh()

    @on(JournalSidebar.DaySelected)
    def _on_day_selected(self, event: JournalSidebar.DaySelected) -> None:
        self._populate_table(event.day)

    @on(DataTable.RowHighlighted, "#journal-table")
    def _on_row_highlight(self, event: DataTable.RowHighlighted) -> None:
        if self._selected_day is None:
            return
        items = self._selected_day.items
        row = event.cursor_row
        selected = items[row] if items and row is not None and row < len(items) else None
        self.post_message(self.SelectionChanged(selected))
        self._show_content(selected)
