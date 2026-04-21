from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding

from app.chrome import ChronicleHeader, StatusBar
from app.forms import (
    ConfirmActionScreen,
    EntryDetailScreen,
    EntryFormData,
    EntryFormScreen,
    HelpScreen,
    TodoDetailScreen,
    TodoFormData,
    TodoFormScreen,
)
from app.models import JournalEntry, TimelineEvent, TodoItem
from app.storage import ChronicleStorageAdapter, StorageBackend
from textual.widgets import ContentSwitcher
from views.journal import JournalView
from views.todos import TodosView


class ChronicleApp(App[None]):
    CSS = """
    Screen {
        layout: vertical;
        background: $surface;
        color: $text;
    }

    #body {
        height: 1fr;
        padding: 0 1;
    }

    ChronicleHeader {
        height: 1;
        padding: 0 1;
        background: $boost;
    }

    JournalView, TodosView {
        height: 1fr;
        margin: 1 0;
    }

    Tree, DataTable {
        height: 1fr;
    }

    StatusBar {
        height: 1;
        padding: 0 1;
        dock: bottom;
    }

    EntryFormScreen, TodoFormScreen, EntryDetailScreen, TodoDetailScreen, ConfirmActionScreen, HelpScreen {
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

    #entry-content {
        height: 8;
    }
    """

    BINDINGS = [
        Binding("j", "switch_tab('journal')", "Journal"),
        Binding("t", "switch_tab('todos')", "Todos"),
        Binding("n", "new_item", "New"),
        Binding("v", "view_selected", "View"),
        Binding("e", "edit_selected", "Edit"),
        Binding("d", "delete_selected", "Delete"),
        Binding("space", "toggle_todo", "Toggle"),
        Binding("question_mark", "open_help", "Help"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, storage: StorageBackend | None = None) -> None:
        super().__init__()
        self.storage = storage or ChronicleStorageAdapter()
        self.active_tab = "journal"

    def compose(self) -> ComposeResult:
        yield ChronicleHeader()
        yield ContentSwitcher(
            JournalView(id="journal-pane"),
            TodosView(id="todo-pane"),
            initial="journal-pane",
            id="body",
        )
        yield StatusBar()

    def on_mount(self) -> None:
        self.refresh_views()
        self._apply_tab_state("journal")
        import threading
        from app.voice import warmup
        threading.Thread(target=warmup, daemon=True).start()

    def set_voice_state(self, state: str) -> None:
        """Update the status bar voice indicator. Safe to call from any thread."""
        self.query_one(StatusBar).voice_state = state

    def refresh_views(self) -> None:
        self.query_one(JournalView).refresh_view(self.storage.timeline_events_grouped_by_date())
        self.query_one(TodosView).refresh_view(self.storage.list_todos())
        self._refresh_status()

    def action_switch_tab(self, tab_name: str) -> None:
        self._apply_tab_state(tab_name)

    def action_new_item(self) -> None:
        if self.active_tab == "journal":
            self.push_screen(EntryFormScreen(), self._handle_new_entry)
        else:
            self.push_screen(TodoFormScreen(), self._handle_new_todo)

    def action_edit_selected(self) -> None:
        if self.active_tab == "journal":
            selected = self.query_one(JournalView).selected_event()
            if not selected or not selected.editable or not selected.entry_id:
                self.notify("Select a journal entry to edit.", severity="warning")
                return
            entry = next(
                (entry for entry in self.storage.list_journal_entries() if entry.id == selected.entry_id),
                None,
            )
            if entry is None:
                self.notify("Entry no longer exists.", severity="warning")
                return
            self.push_screen(
                EntryFormScreen(entry),
                lambda result, entry_id=entry.id: self._handle_updated_entry(entry_id, result),
            )
        else:
            todo = self.query_one(TodosView).selected_todo()
            if todo is None:
                self.notify("Select a todo to edit.", severity="warning")
                return
            self.push_screen(
                TodoFormScreen(todo),
                lambda result, todo_id=todo.id: self._handle_updated_todo(todo_id, result),
            )

    def action_delete_selected(self) -> None:
        if self.active_tab == "journal":
            selected = self.query_one(JournalView).selected_event()
            if not selected or not selected.editable or not selected.entry_id:
                self.notify("Select a journal entry to delete.", severity="warning")
                return
            entry = self._get_entry(selected.entry_id)
            if entry is None:
                self.notify("Entry no longer exists.", severity="warning")
                return
            self.push_screen(
                ConfirmActionScreen(f"Delete journal entry '{entry.title}'?", confirm_label="Delete"),
                lambda confirmed, entry_id=entry.id: self._handle_delete_entry(entry_id, confirmed),
            )
        else:
            todo = self.query_one(TodosView).selected_todo()
            if todo is None:
                self.notify("Select a todo to delete.", severity="warning")
                return
            self.push_screen(
                ConfirmActionScreen(f"Delete todo '{todo.title}'?", confirm_label="Delete"),
                lambda confirmed, todo_id=todo.id: self._handle_delete_todo(todo_id, confirmed),
            )

    def action_toggle_todo(self) -> None:
        if self.active_tab != "todos":
            return
        todo = self.query_one(TodosView).selected_todo()
        if todo is None:
            self.notify("Select a todo to toggle.", severity="warning")
            return
        updated = self.storage.toggle_todo_completion(todo.id)
        self.notify("Todo completed." if updated.completed else "Todo reopened.")
        self.refresh_views()
        self._apply_tab_state("todos")

    def action_open_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_view_selected(self) -> None:
        if self.active_tab == "journal":
            selected = self.query_one(JournalView).selected_event()
            if selected is None:
                self.notify("Select an item to view.", severity="warning")
                return
            if selected.entry_id:
                entry = self._get_entry(selected.entry_id)
                if entry is None:
                    self.notify("Entry no longer exists.", severity="warning")
                    return
                self.push_screen(EntryDetailScreen(entry))
                return
            if selected.todo_id:
                todo = self._get_todo(selected.todo_id)
                if todo is None:
                    self.notify("Todo no longer exists.", severity="warning")
                    return
                self.push_screen(TodoDetailScreen(todo))
                return
            self.notify("Nothing to view for this item.", severity="warning")
            return

        todo = self.query_one(TodosView).selected_todo()
        if todo is None:
            self.notify("Select a todo to view.", severity="warning")
            return
        self.push_screen(TodoDetailScreen(todo))

    def on_journal_view_selection_changed(self, message: JournalView.SelectionChanged) -> None:
        self._refresh_status(message.timeline_event)

    def on_todos_view_selection_changed(self, message: TodosView.SelectionChanged) -> None:
        self._refresh_status(message.todo)

    def _apply_tab_state(self, tab_name: str) -> None:
        self.active_tab = tab_name
        self.query_one(ContentSwitcher).current = "journal-pane" if tab_name == "journal" else "todo-pane"
        header = self.query_one(ChronicleHeader)
        header.active_tab = tab_name
        if tab_name == "journal":
            self.query_one(JournalView).focus_content()
        else:
            self.query_one(TodosView).focus_content()
        self._refresh_status()

    def _refresh_status(self, selected: TimelineEvent | TodoItem | None = None) -> None:
        if self.active_tab == "journal":
            selected_event = (
                selected if isinstance(selected, TimelineEvent) else self.query_one(JournalView).selected_event()
            )
            edit_hint = "e edit" if selected_event and selected_event.editable else "e edit entry"
            message = f"j/t switch tabs  n new entry  v view  {edit_hint}  d delete entry  ? help  q quit"
        else:
            selected_todo = selected if isinstance(selected, TodoItem) else self.query_one(TodosView).selected_todo()
            toggle_hint = "space toggle" if selected_todo else "space toggle todo"
            message = f"j/t switch tabs  n new todo  v view  e edit  d delete  {toggle_hint}  ? help  q quit"
        self.query_one(StatusBar).message = message

    def _handle_new_entry(self, result: EntryFormData | None) -> None:
        if isinstance(result, EntryFormData):
            self.storage.create_entry(result.title, result.content)
            self.notify("Journal entry saved.")
            self.refresh_views()
            self._apply_tab_state("journal")

    def _handle_updated_entry(self, entry_id: str, result: EntryFormData | None) -> None:
        if isinstance(result, EntryFormData):
            self.storage.update_entry(entry_id, title=result.title, content=result.content)
            self.notify("Journal entry updated.")
            self.refresh_views()
            self._apply_tab_state("journal")

    def _handle_new_todo(self, result: TodoFormData | None) -> None:
        if isinstance(result, TodoFormData):
            self.storage.create_todo(result.title, due_date=result.due_date)
            self.notify("Todo created.")
            self.refresh_views()
            self._apply_tab_state("todos")

    def _handle_updated_todo(self, todo_id: str, result: TodoFormData | None) -> None:
        if isinstance(result, TodoFormData):
            self.storage.update_todo(todo_id, title=result.title, due_date=result.due_date)
            self.notify("Todo updated.")
            self.refresh_views()
            self._apply_tab_state("todos")

    def _handle_delete_entry(self, entry_id: str, confirmed: bool) -> None:
        if confirmed:
            self.storage.delete_entry(entry_id)
            self.notify("Journal entry deleted.")
            self.refresh_views()
            self._apply_tab_state("journal")

    def _handle_delete_todo(self, todo_id: str, confirmed: bool) -> None:
        if confirmed:
            self.storage.delete_todo(todo_id)
            self.notify("Todo deleted.")
            self.refresh_views()
            self._apply_tab_state("todos")

    def _get_entry(self, entry_id: str) -> JournalEntry | None:
        return next((entry for entry in self.storage.list_journal_entries() if entry.id == entry_id), None)

    def _get_todo(self, todo_id: str) -> TodoItem | None:
        return next((todo for todo in self.storage.list_todos() if todo.id == todo_id), None)


if __name__ == "__main__":
    ChronicleApp().run()
