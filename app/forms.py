from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static, TextArea

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


class HelpScreen(ModalScreen[None]):
    BINDINGS = [("escape", "close", "Close")]

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Chronicle shortcuts", classes="modal_title"),
            Static("j/t switch tabs\nn new item\ne edit selected\nd delete selected\nspace toggle todo\n? open help\nq quit"),
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
