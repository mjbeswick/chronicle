"""Notes view for Chronicle."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Label, ListItem, ListView, Markdown, Static

from app.filter import FilterSpec, matches_date, matches_tag, matches_text
from app.models import Item
from app.voice import ViewVoiceHoldHandler


class NotesView(Vertical):
    """Notes lens — untimed items with body content."""

    DEFAULT_CSS = """
    NotesView {
        height: 1fr;
    }

    #notes-filter-banner {
        height: auto;
        padding: 0 1;
        color: $text;
        background: $warning-darken-2;
        display: none;
    }

    #notes-panels {
        height: 1fr;
    }

    #notes-list-panel {
        width: 24;
        border-right: tall $primary-darken-3;
        padding: 0;
    }

    #notes-list {
        width: 1fr;
        height: 1fr;
        padding: 0;
    }

    #notes-content-panel {
        width: 1fr;
        padding: 0 1;
        overflow-y: auto;
    }

    #notes-preview {
        height: 1fr;
    }

    #notes-empty {
        color: $text-muted;
        padding: 1;
    }
    """

    class SelectionChanged(Message):
        def __init__(self, item: Item | None) -> None:
            self.item = item
            super().__init__()

    def __init__(self) -> None:
        super().__init__()
        self._notes: list[Item] = []
        self._filter: FilterSpec = FilterSpec()
        self._voice = ViewVoiceHoldHandler(
            self, on_transcript=lambda t: self.app.voice_create_for_active_tab(t)
        )

    def on_key(self, event) -> None:
        if self._voice.handle_key(event):
            event.stop()
            return
        if event.key in ("left", "right"):
            panels = ["notes-list", "notes-preview"]
            direction = 1 if event.key == "right" else -1
            focused = self.app.focused
            idx = None
            for i, pid in enumerate(panels):
                try:
                    w = self.query_one(f"#{pid}")
                except Exception:
                    continue
                if focused is w or (focused is not None and w in focused.ancestors):
                    idx = i
                    break
            target_idx = (idx + direction) if idx is not None else 0
            if 0 <= target_idx < len(panels):
                try:
                    self.query_one(f"#{panels[target_idx]}").focus()
                    event.stop()
                    event.prevent_default()
                except Exception:
                    pass

    def compose(self) -> ComposeResult:
        yield Static("", id="notes-filter-banner")
        with Horizontal(id="notes-panels"):
            with Vertical(id="notes-list-panel"):
                yield ListView(id="notes-list")
            with Vertical(id="notes-content-panel"):
                yield Static("Select a note to preview its content.", id="notes-empty")
                yield Markdown("", id="notes-preview")

    def refresh_view(self, notes: list[Item]) -> None:
        self._notes = notes
        self._rebuild_list()

    def all_tags(self) -> list[str]:
        return sorted({tag for n in self._notes for tag in n.tags})

    def active_tag(self) -> str | None:
        return self._filter.tag

    def apply_filter(self, spec: FilterSpec) -> None:
        self._filter = spec
        banner = self.query_one("#notes-filter-banner", Static)
        if spec.is_active:
            banner.update(Text.assemble(
                ("Filter: ", "bold"),
                (spec.summary(), ""),
                (" - f to change, ^f to clear", "dim"),
            ))
            banner.display = True
        else:
            banner.display = False
        self._rebuild_list()

    def _visible_notes(self) -> list[Item]:
        if not self._filter.is_active:
            return self._notes
        result = []
        for note in self._notes:
            if not matches_text(self._filter, note.title, note.body):
                continue
            if not matches_tag(self._filter, note.tags):
                continue
            if not matches_date(self._filter, note.updated_at.date()):
                continue
            result.append(note)
        return result

    def _rebuild_list(self) -> None:
        lst = self.query_one("#notes-list", ListView)
        lst.clear()
        visible = self._visible_notes()
        for note in visible:
            lst.append(ListItem(Label(note.title)))
        if visible:
            lst.index = 0
            self._show_note(visible[0])
        else:
            self._clear_preview()

    def _show_note(self, note: Item) -> None:
        empty = self.query_one("#notes-empty", Static)
        preview = self.query_one("#notes-preview", Markdown)
        if note.body.strip():
            empty.display = False
            preview.display = True
            preview.update(note.body)
        else:
            empty.display = True
            empty.update("(empty note)")
            preview.display = False
        self.post_message(self.SelectionChanged(note))

    def _clear_preview(self) -> None:
        self.query_one("#notes-empty", Static).display = True
        self.query_one("#notes-empty", Static).update("Select a note to preview its content.")
        preview = self.query_one("#notes-preview", Markdown)
        preview.display = False
        self.post_message(self.SelectionChanged(None))

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.item is None:
            return
        lst = self.query_one("#notes-list", ListView)
        idx = lst.index
        visible = self._visible_notes()
        if idx is not None and 0 <= idx < len(visible):
            self._show_note(visible[idx])

    def selected_note(self) -> Item | None:
        lst = self.query_one("#notes-list", ListView)
        idx = lst.index
        visible = self._visible_notes()
        if idx is None or not visible or idx >= len(visible):
            return None
        return visible[idx]

    def focus_content(self) -> None:
        self.query_one("#notes-list", ListView).focus()
