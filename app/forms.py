from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Markdown, Static, TextArea

from .models import JournalEntry, TodoItem


@dataclass
class EntryFormData:
    title: str
    content: str


@dataclass
class TodoFormData:
    title: str
    due_date: date | None


class EntryFormScreen(ModalScreen[Optional[EntryFormData]]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, entry: JournalEntry | None = None) -> None:
        super().__init__()
        self.entry = entry

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Edit journal entry" if self.entry else "New journal entry", classes="modal_title"),
            Input(value=self.entry.title if self.entry else "", placeholder="Title", id="entry-title"),
            TextArea(
                self.entry.content if self.entry else "",
                id="entry-content",
            ),
            Label("", id="entry-error", classes="modal_error"),
            Horizontal(
                Button("Cancel", id="cancel"),
                Button("Save", id="save", variant="primary"),
                classes="modal_actions",
            ),
            id="modal-body",
            classes="modal_window",
        )

    def on_mount(self) -> None:
        self.query_one("#entry-title", Input).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        self._submit()

    def _submit(self) -> None:
        title = self.query_one("#entry-title", Input).value.strip()
        content = self.query_one("#entry-content", TextArea).text.strip()
        error = self.query_one("#entry-error", Label)
        if not title:
            error.update("Title is required.")
            return
        self.dismiss(EntryFormData(title=title, content=content))


class TodoFormScreen(ModalScreen[Optional[TodoFormData]]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, todo: TodoItem | None = None) -> None:
        super().__init__()
        self.todo = todo

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Edit todo" if self.todo else "New todo", classes="modal_title"),
            Input(value=self.todo.title if self.todo else "", placeholder="Todo title", id="todo-title"),
            Input(
                value=self.todo.due_date.isoformat() if self.todo and self.todo.due_date else "",
                placeholder="Due date (YYYY-MM-DD)",
                id="todo-due-date",
            ),
            Label("", id="todo-error", classes="modal_error"),
            Horizontal(
                Button("Cancel", id="cancel"),
                Button("Save", id="save", variant="primary"),
                classes="modal_actions",
            ),
            id="modal-body",
            classes="modal_window",
        )

    def on_mount(self) -> None:
        self.query_one("#todo-title", Input).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        self._submit()

    def _submit(self) -> None:
        title = self.query_one("#todo-title", Input).value.strip()
        due_raw = self.query_one("#todo-due-date", Input).value.strip()
        error = self.query_one("#todo-error", Label)
        if not title:
            error.update("Title is required.")
            return

        parsed_due_date = None
        if due_raw:
            try:
                parsed_due_date = date.fromisoformat(due_raw)
            except ValueError:
                error.update("Use YYYY-MM-DD for due dates.")
                return

        self.dismiss(TodoFormData(title=title, due_date=parsed_due_date))


class EntryDetailScreen(ModalScreen[None]):
    BINDINGS = [("escape", "close", "Back")]

    def __init__(self, entry: JournalEntry) -> None:
        super().__init__()
        self.entry = entry

    def compose(self) -> ComposeResult:
        created = self.entry.created_at.astimezone().strftime("%Y-%m-%d %H:%M")
        updated = self.entry.updated_at.astimezone().strftime("%Y-%m-%d %H:%M")
        yield Vertical(
            Label(self.entry.title, classes="modal_title"),
            Static(f"Created {created}  Updated {updated}", classes="detail_meta"),
            Markdown(self.entry.content or "_No content yet._", classes="detail_markdown"),
            Horizontal(
                Button("Close", id="close", variant="primary"),
                classes="modal_actions",
            ),
            classes="modal_window detail_window",
        )

    def on_mount(self) -> None:
        self.query_one("#close", Button).focus()

    def action_close(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close":
            self.dismiss(None)


class TodoDetailScreen(ModalScreen[None]):
    BINDINGS = [("escape", "close", "Back")]

    def __init__(self, todo: TodoItem) -> None:
        super().__init__()
        self.todo = todo

    def compose(self) -> ComposeResult:
        due_text = self.todo.due_date.isoformat() if self.todo.due_date else "None"
        status = "Done" if self.todo.completed else "Open"
        yield Vertical(
            Label(self.todo.title, classes="modal_title"),
            Static(f"Status: {status}", classes="detail_meta"),
            Static(f"Due: {due_text}", classes="detail_meta"),
            Horizontal(
                Button("Close", id="close", variant="primary"),
                classes="modal_actions",
            ),
            classes="modal_window detail_window",
        )

    def on_mount(self) -> None:
        self.query_one("#close", Button).focus()

    def action_close(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close":
            self.dismiss(None)


class ConfirmActionScreen(ModalScreen[bool]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, prompt: str, *, confirm_label: str = "Confirm") -> None:
        super().__init__()
        self.prompt = prompt
        self.confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Please confirm", classes="modal_title"),
            Static(self.prompt, classes="confirm_text"),
            Horizontal(
                Button("Cancel", id="cancel"),
                Button(self.confirm_label, id="confirm", variant="error"),
                classes="modal_actions",
            ),
            classes="modal_window",
        )

    def on_mount(self) -> None:
        self.query_one("#cancel", Button).focus()

    def action_cancel(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm":
            self.dismiss(True)
        else:
            self.dismiss(False)


class HelpScreen(ModalScreen[None]):
    BINDINGS = [("escape", "close", "Close")]

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Chronicle shortcuts", classes="modal_title"),
            Static(
                "j/t switch tabs\n"
                "n new item\n"
                "v view selected\n"
                "e edit selected\n"
                "d delete selected\n"
                "space toggle todo\n"
                "? open help\n"
                "q quit"
            ),
            Horizontal(
                Button("Close", id="close", variant="primary"),
                classes="modal_actions",
            ),
            classes="modal_window",
        )

    def on_mount(self) -> None:
        self.query_one("#close", Button).focus()

    def action_close(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close":
            self.dismiss(None)
