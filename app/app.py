from __future__ import annotations

import time
from datetime import date

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import TabbedContent, TabPane

from app.chrome import ChronicleHeader, StatusBar
from app.forms import (
    ConfirmActionScreen,
    FilterScreen,
    HelpScreen,
    ItemDetailScreen,
    ItemFormData,
    ItemFormScreen,
    TagEditScreen,
)
from app.models import Item, utc_now
from app.storage import ChronicleStorageAdapter, StorageBackend
from views.calendar import CalendarView
from views.journal import JournalView
from views.notes import NotesView
from views.todos import TodosView


class ChronicleApp(App[None]):
    CSS = """
    Screen {
        layout: vertical;
        background: $surface;
        color: $text;
        padding: 0;
    }

    #body { height: 1fr; }
    TabbedContent { height: 1fr; }
    TabPane { padding: 0; height: 1fr; }

    JournalView, TodosView, NotesView, CalendarView { height: 1fr; }

    #todo-tree { height: 1fr; }

    ChronicleHeader {
        dock: right;
        width: auto;
        height: 1;
        background: transparent;
        color: $text;
        padding: 0 1;
    }

    StatusBar {
        height: 1;
        padding: 0 1;
        margin: 0;
        dock: bottom;
        background: $panel;
    }

    ItemFormScreen, ItemDetailScreen, ConfirmActionScreen, HelpScreen, TagEditScreen, FilterScreen {
        align: center middle;
        background: $background 60%;
    }

    .modal_window {
        width: 70;
        max-width: 90%;
        height: auto;
        padding: 1 2;
        background: $panel;
        border: heavy $accent;
        align: center middle;
    }

    .modal_title {
        content-align: center middle;
        text-style: bold;
        margin-bottom: 1;
    }

    .modal_actions {
        align-horizontal: right;
        height: auto;
        margin-top: 1;
    }

    .modal_error {
        color: $error;
        height: 1;
        margin-top: 1;
    }

    .detail_window {
        height: auto;
        max-height: 90%;
    }

    .detail_meta, .confirm_text {
        color: $text-muted;
        margin-bottom: 1;
    }

    .detail_markdown {
        height: 16;
        border: round $primary;
        padding: 0 1;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("ctrl+j", "switch_tab('journal')", "Journal"),
        Binding("ctrl+t", "switch_tab('todos')", "Todos"),
        Binding("ctrl+n", "switch_tab('notes')", "Notes"),
        Binding("ctrl+c", "ctrl_c", "Calendar", priority=True),
        Binding("n", "new_item", "New"),
        Binding("N", "new_subtask", "Subtask", show=False),
        Binding("v", "view_selected", "View"),
        Binding("e", "edit_selected", "Edit"),
        Binding("d", "delete_selected", "Delete"),
        Binding("f", "filter", "Filter"),
        Binding("ctrl+f", "clear_filter", "Clear filter", show=False),
        Binding("x", "toggle_todo", "Toggle"),
        Binding("hash", "tag_item", "Tag", show=False),
        Binding("left_square_bracket", "toggle_tree", "Tree", show=False),
        Binding("right_square_bracket", "toggle_content", "Content", show=False),
        Binding("ctrl+l", "cycle_journal_layout", "Layout", show=False),
        Binding("question_mark", "open_help", "Help"),
        Binding("escape", "quit", "Quit", show=False),
        Binding("q", "quit", "Quit"),
    ]

    CTRL_C_DOUBLE_WINDOW = 1.5
    CTRL_HINT_WINDOW = 1.8

    def __init__(self, storage: StorageBackend | None = None) -> None:
        super().__init__()
        self.storage = storage or ChronicleStorageAdapter()
        self.active_tab = "journal"
        self._last_ctrl_c = 0.0

    def compose(self) -> ComposeResult:
        yield StatusBar()
        with TabbedContent(id="body", initial="journal"):
            with TabPane("Journal", id="journal"):
                yield JournalView()
            with TabPane("Todos", id="todos"):
                yield TodosView()
            with TabPane("Notes", id="notes"):
                yield NotesView()
            with TabPane("Calendar", id="calendar"):
                yield CalendarView()

    def on_mount(self) -> None:
        self._status_bar = self.query_one(StatusBar)
        self._ctrl_hint_timer = None
        from textual.widgets import Tabs
        tabs = self.query_one(TabbedContent).query_one(Tabs)
        tabs.mount(ChronicleHeader())
        self.refresh_views()
        import threading
        from app.voice import warmup
        threading.Thread(target=warmup, daemon=True).start()

    def on_key(self, event) -> None:
        if event.key.startswith("ctrl+") and len(self.screen_stack) <= 1:
            self._show_ctrl_hints()

    # ---------------------------------------------------------------- refresh

    def refresh_views(self) -> None:
        items = self.storage.list_items()
        now = utc_now()
        today = date.today()

        journal_items = [i for i in items if i.in_journal(now)]
        todo_items = [i for i in items if i.in_todos(now) or i.is_done]
        note_items = [i for i in items if i.in_notes()]

        entry_dates = {
            i.timeline_at(now).astimezone().date()
            for i in journal_items
        }
        due_dates = {
            i.due for i in items
            if i.due and not i.is_done and i.due >= today
        }
        overdue_dates = {
            i.due for i in items
            if i.due and not i.is_done and i.due < today
        }

        self.query_one(JournalView).refresh_view(journal_items)
        self.query_one(TodosView).refresh_view(todo_items)
        self.query_one(NotesView).refresh_view(note_items)
        self.query_one(CalendarView).refresh_view(entry_dates, due_dates, overdue_dates)

        self._items_total = len(items)
        self._journal_count = len(journal_items)
        self._todo_open = sum(1 for i in todo_items if not i.is_done)
        self._todo_total = len(todo_items)
        self._note_count = len(note_items)
        self._refresh_status()

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        if event.pane is None:
            return
        self.active_tab = event.pane.id
        self._focus_active_view()
        self._refresh_status()

    def _focus_active_view(self) -> None:
        if self.active_tab == "journal":
            self.query_one(JournalView).focus_content()
        elif self.active_tab == "notes":
            self.query_one(NotesView).focus_content()
        elif self.active_tab == "calendar":
            self.query_one(CalendarView).focus()
        else:
            self.query_one(TodosView).focus_content()

    # ---------------------------------------------------------------- voice

    def set_voice_state(self, state: str) -> None:
        """Update the status bar voice indicator. Safe to call from any thread."""
        self._status_bar.voice_state = state

    def voice_create_for_active_tab(self, title: str) -> None:
        title = title.strip()
        if not title:
            return
        preset = self._preset_for_active_tab()
        self.push_screen(
            ItemFormScreen(initial_title=title, **preset),
            self._handle_new_item,
        )

    def _preset_for_active_tab(self) -> dict:
        """Return ItemFormScreen kwargs that make sense for the current tab."""
        if self.active_tab == "journal":
            return {"initial_at": utc_now()}
        if self.active_tab == "notes":
            tag = self.query_one(NotesView).active_tag()
            return {"default_tags": [tag] if tag else []}
        return {}

    # ---------------------------------------------------------------- tabs

    def action_switch_tab(self, tab_name: str) -> None:
        self._switch_to_tab(tab_name)

    def _switch_to_tab(self, tab_name: str) -> None:
        tc = self.query_one(TabbedContent)
        if tc.active == tab_name:
            self._focus_active_view()
            self._refresh_status()
        else:
            tc.active = tab_name

    def action_ctrl_c(self) -> None:
        now = time.monotonic()
        if now - self._last_ctrl_c < self.CTRL_C_DOUBLE_WINDOW:
            self.exit()
            return
        self._last_ctrl_c = now
        if self.screen is self.screen_stack[0]:
            self._switch_to_tab("calendar")
        self.notify("Press ctrl+c again to quit.", timeout=self.CTRL_C_DOUBLE_WINDOW)

    # ---------------------------------------------------------------- new

    def action_new_item(self) -> None:
        preset = self._preset_for_active_tab()
        # Todos tab: parent inheritance from selected item.
        if self.active_tab in ("todos", "calendar"):
            selected = self.query_one(TodosView).selected_todo()
            parent_id = selected.parent_id if selected and selected.parent_id else None
            self.push_screen(
                ItemFormScreen(**preset),
                lambda r, pid=parent_id: self._handle_new_item(r, parent_id=pid),
            )
            return
        self.push_screen(ItemFormScreen(**preset), self._handle_new_item)

    def action_new_subtask(self) -> None:
        if self.active_tab != "todos":
            return
        selected = self.query_one(TodosView).selected_todo()
        if selected is None:
            self.notify("Select a todo to add a subtask to.", severity="warning")
            return
        self.push_screen(
            ItemFormScreen(),
            lambda r, pid=selected.id: self._handle_new_item(r, parent_id=pid),
        )

    def _handle_new_item(self, result: ItemFormData | None, *, parent_id: str | None = None) -> None:
        if not isinstance(result, ItemFormData):
            return
        item = self.storage.create_item(
            title=result.title,
            body=result.body,
            tags=result.tags,
            parent_id=parent_id,
            at=result.at,
            due=result.due,
        )
        if result.done:
            self.storage.toggle_done(item.id)
        self.notify("Item created.")
        self.refresh_views()

    def _handle_new_from_calendar(self, result: ItemFormData | None) -> None:
        self._handle_new_item(result)
        if isinstance(result, ItemFormData):
            self._switch_to_tab("todos")

    # ---------------------------------------------------------------- edit

    def action_edit_selected(self) -> None:
        item = self._selected_item()
        if item is None:
            self.notify("Select an item to edit.", severity="warning")
            return
        self.push_screen(
            ItemFormScreen(item),
            lambda r, iid=item.id: self._handle_updated_item(iid, r),
        )

    def _handle_updated_item(self, item_id: str, result: ItemFormData | None) -> None:
        if not isinstance(result, ItemFormData):
            return
        self.storage.update_item(
            item_id,
            title=result.title,
            body=result.body,
            tags=result.tags,
            at=result.at,
            due=result.due,
        )
        existing = next((i for i in self.storage.list_items() if i.id == item_id), None)
        if existing is not None and existing.is_done != result.done:
            self.storage.toggle_done(item_id)
        self.notify("Item updated.")
        self.refresh_views()

    # ---------------------------------------------------------------- delete

    def action_delete_selected(self) -> None:
        item = self._selected_item()
        if item is None:
            self.notify("Select an item to delete.", severity="warning")
            return
        self.push_screen(
            ConfirmActionScreen(f"Delete '{item.title}'?", confirm_label="Delete"),
            lambda confirmed, iid=item.id: self._handle_delete(iid, confirmed),
        )

    def _handle_delete(self, item_id: str, confirmed: bool) -> None:
        if not confirmed:
            return
        self.storage.delete_item(item_id)
        self.notify("Item deleted.")
        self.refresh_views()

    # ---------------------------------------------------------------- toggle

    def action_toggle_todo(self) -> None:
        # `x` on any view: toggle done state of the selected item, where it makes sense.
        item = self._selected_item()
        if item is None:
            self.notify("Select an item to toggle.", severity="warning")
            return
        updated = self.storage.toggle_done(item.id)
        self.notify("Marked done." if updated.is_done else "Reopened.")
        self.refresh_views()

    # ---------------------------------------------------------------- filter

    def action_filter(self) -> None:
        if self.active_tab == "journal":
            view = self.query_one(JournalView)
            self.push_screen(FilterScreen(view._filter, view.all_tags()), self._handle_filter_journal)
        elif self.active_tab == "notes":
            view = self.query_one(NotesView)
            self.push_screen(FilterScreen(view._filter, view.all_tags()), self._handle_filter_notes)
        elif self.active_tab == "todos":
            view = self.query_one(TodosView)
            self.push_screen(FilterScreen(view._filter, view.all_tags()), self._handle_filter_todos)

    def action_clear_filter(self) -> None:
        from app.filter import FilterSpec
        if self.active_tab == "journal":
            self.query_one(JournalView).apply_filter(FilterSpec())
        elif self.active_tab == "notes":
            self.query_one(NotesView).apply_filter(FilterSpec())
            self._refresh_status()
        elif self.active_tab == "todos":
            self.query_one(TodosView).apply_filter(FilterSpec())

    def _handle_filter_journal(self, spec) -> None:
        if spec is None:
            return
        self.query_one(JournalView).apply_filter(spec)

    def _handle_filter_notes(self, spec) -> None:
        if spec is None:
            return
        self.query_one(NotesView).apply_filter(spec)
        self._refresh_status()

    def _handle_filter_todos(self, spec) -> None:
        if spec is None:
            return
        self.query_one(TodosView).apply_filter(spec)

    # ---------------------------------------------------------------- tags

    def action_tag_item(self) -> None:
        item = self._selected_item()
        if item is None:
            self.notify("Select an item to tag.", severity="warning")
            return
        self.push_screen(
            TagEditScreen(item.tags),
            lambda tags, iid=item.id: self._handle_tags(iid, tags),
        )

    def _handle_tags(self, item_id: str, tags: list[str] | None) -> None:
        if tags is None:
            return
        self.storage.update_tags(item_id, tags)
        self.refresh_views()

    # ---------------------------------------------------------------- layout

    def action_toggle_tree(self) -> None:
        if self.active_tab == "journal":
            self.query_one(JournalView).toggle_tree()

    def action_toggle_content(self) -> None:
        if self.active_tab == "journal":
            self.query_one(JournalView).toggle_content()

    def action_cycle_journal_layout(self) -> None:
        if self.active_tab == "journal":
            self.query_one(JournalView).cycle_layout()

    # ---------------------------------------------------------------- view

    def action_view_selected(self) -> None:
        item = self._selected_item()
        if item is None:
            self.notify("Select an item to view.", severity="warning")
            return
        self.push_screen(ItemDetailScreen(item))

    def action_open_help(self) -> None:
        self.push_screen(HelpScreen())

    # ---------------------------------------------------------------- calendar

    def _goto_journal_for_day(self, target: date) -> None:
        from app.filter import FilterSpec
        spec = FilterSpec(date_from=target, date_to=target)
        self._switch_to_tab("journal")
        self.query_one(JournalView).apply_filter(spec)

    # ---------------------------------------------------------------- messages

    def on_journal_view_selection_changed(self, message: JournalView.SelectionChanged) -> None:
        self._refresh_status(message.item)

    def on_todos_view_selection_changed(self, message: TodosView.SelectionChanged) -> None:
        self._refresh_status(message.item)

    def on_notes_view_selection_changed(self, message: NotesView.SelectionChanged) -> None:
        self._refresh_status(message.item)

    # ---------------------------------------------------------------- helpers

    def _selected_item(self) -> Item | None:
        if self.active_tab == "journal":
            return self.query_one(JournalView).selected_item()
        if self.active_tab == "notes":
            return self.query_one(NotesView).selected_note()
        return self.query_one(TodosView).selected_todo()

    # ---------------------------------------------------------------- status

    def _show_ctrl_hints(self) -> None:
        if not hasattr(self, "_status_bar"):
            return
        self._status_bar.hints = [
            ("^j", "journal"),
            ("^t", "todos"),
            ("^n", "notes"),
            ("^c", "calendar"),
            ("^c ^c", "quit"),
            ("^l", "layout"),
        ]
        self._status_bar.count = ""
        if self._ctrl_hint_timer is not None:
            self._ctrl_hint_timer.stop()
        self._ctrl_hint_timer = self.set_timer(self.CTRL_HINT_WINDOW, self._refresh_status)

    def _refresh_status(self, selected: Item | None = None) -> None:
        if len(self.screen_stack) > 1:
            return
        if self.active_tab == "journal":
            selected_item = selected if isinstance(selected, Item) else self.query_one(JournalView).selected_item()
            hints: list[tuple[str, str]] = [
                ("^t/^n/^c", "tabs"),
                ("n", "new"),
                ("hold space", "voice"),
            ]
            if selected_item is not None:
                hints += [("v", "view"), ("e", "edit"), ("d", "delete"), ("x", "toggle")]
            hints += [("^l", "layout"), ("?", "help"), ("q", "quit")]
            n = self._journal_count
            count = f"{n} journal {'item' if n == 1 else 'items'}"
        elif self.active_tab == "notes":
            view = self.query_one(NotesView)
            hints = [
                ("^j/^t/^c", "tabs"),
                ("n", "new note"),
                ("e", "edit"),
                ("d", "delete"),
                ("#", "tags"),
                ("f", "filter"),
                ("?", "help"),
                ("q", "quit"),
            ]
            total = len(view._notes)
            if view._filter.is_active:
                visible = len(view._visible_notes())
                count = f"Filtered - {view._filter.summary()} - {visible}/{total} notes"
            else:
                count = f"{total} {'note' if total == 1 else 'notes'}"
        elif self.active_tab == "calendar":
            hints = [
                ("^j/^t/^n", "tabs"),
                ("↑↓←→", "nav"),
                ("tab", "month"),
                ("enter", "open"),
                ("shift+←/→", "year"),
                ("y", "jump"),
                ("home", "today"),
                ("?", "help"),
                ("q", "quit"),
            ]
            count = "green=entries  yellow=due  red=overdue"
        else:
            selected_todo = selected if isinstance(selected, Item) else self.query_one(TodosView).selected_todo()
            hints = [
                ("^j/^n/^c", "tabs"),
                ("n", "new todo"),
                ("N", "subtask"),
                ("v", "view"),
                ("e", "edit"),
                ("d", "delete"),
                ("x", "toggle" if selected_todo else "toggle todo"),
                ("?", "help"),
                ("q", "quit"),
            ]
            counts = self.query_one(TodosView).filter_counts()
            parts = []
            if counts["overdue"]:
                parts.append(f"{counts['overdue']} overdue")
            parts.append(f"{counts['open']} open")
            parts.append(f"{counts['all']} total")
            count = " / ".join(parts)
        if not hasattr(self, "_status_bar"):
            return
        self._status_bar.hints = hints
        self._status_bar.count = count


if __name__ == "__main__":
    ChronicleApp().run()
