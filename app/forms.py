from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from datetime import date
from typing import Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Markdown, Static, TextArea

from .models import JournalEntry, TodoItem
from .voice import RELEASE_DELAY, REPEAT_DELAY, VoiceRecorder, is_available, transcribe_file


@dataclass
class EntryFormData:
    title: str
    content: str


@dataclass
class TodoFormData:
    title: str
    due_date: date | None


# ---------------------------------------------------------------------------
# Voice-aware widgets — each is a standalone subclass (no shared mixin)
# to avoid MRO issues with on_key resolution.
# ---------------------------------------------------------------------------

class VoiceTextArea(TextArea):
    """TextArea that starts recording when space is held for ~600 ms."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._vr: VoiceRecorder | None = VoiceRecorder() if is_available() else None
        self._v_pending = False
        self._v_space: tuple[int, int] | None = None  # doc position of pending space
        self._v_recording = False
        self._v_repeat_timer = None
        self._v_release_timer = None

    def on_key(self, event: Key) -> None:
        if self._vr is None:
            return

        if event.key != "space":
            # Any non-space key clears pending hold state
            if self._v_pending:
                self._v_pending = False
                self._v_space = None
                if self._v_repeat_timer:
                    self._v_repeat_timer.stop()
                    self._v_repeat_timer = None
            return

        # TextArea._on_key already inserted the space; cursor is now past it.
        row, col = self.cursor_location

        if self._v_recording:
            # Key-repeat during recording: delete the just-inserted space and reset
            # the release timer so we keep recording while space is held.
            self._v_delete_doc(row, col - 1)
            if self._v_release_timer:
                self._v_release_timer.stop()
            self._v_release_timer = self.set_timer(RELEASE_DELAY, self._v_on_release)
            event.stop()
            return

        if not self._v_pending:
            # First press: verify space is at col-1 and arm repeat timer
            if col > 0:
                line = self.document.get_line(row)
                if col - 1 < len(line) and line[col - 1] == " ":
                    self._v_space = (row, col - 1)
                    self._v_pending = True
                    self._v_repeat_timer = self.set_timer(REPEAT_DELAY, self._v_on_no_repeat)
        else:
            # Auto-repeat within REPEAT_DELAY: hold confirmed!
            self._v_pending = False
            if self._v_repeat_timer:
                self._v_repeat_timer.stop()
                self._v_repeat_timer = None

            # Delete the repeat space (just inserted at col-1).
            # Then delete the original pending space (earlier on same row; unaffected).
            self._v_delete_doc(row, col - 1)
            if self._v_space:
                self._v_delete_doc(*self._v_space)
                self._v_space = None

            if self._vr.start():
                self._v_recording = True
                self.app.set_voice_state("recording")
                self._v_release_timer = self.set_timer(RELEASE_DELAY, self._v_on_release)
            event.stop()

    def _v_delete_doc(self, row: int, col: int) -> None:
        """Delete one character at (row, col) — only if it is a space."""
        if col < 0:
            return
        line = self.document.get_line(row)
        if col < len(line) and line[col] == " ":
            self.delete((row, col), (row, col + 1))

    def _v_on_no_repeat(self) -> None:
        """Timer fired before any auto-repeat: was just a normal space tap."""
        self._v_pending = False
        self._v_space = None
        self._v_repeat_timer = None

    def _v_on_release(self) -> None:
        """No space-repeat within RELEASE_DELAY: key released — stop recording."""
        self._v_release_timer = None
        self._v_recording = False
        wav = self._vr.stop_and_save()
        if wav:
            self.app.set_voice_state("transcribing")
            threading.Thread(target=self._v_transcribe, args=(wav,), daemon=True).start()
        else:
            self.app.set_voice_state("idle")

    def _v_transcribe(self, wav_path: str) -> None:
        """Background thread: transcribe then insert result in the event loop."""
        try:
            text = transcribe_file(wav_path)
        finally:
            try:
                os.unlink(wav_path)
            except OSError:
                pass
        if text:
            self.call_from_thread(self.insert, text)
        self.call_from_thread(self.app.set_voice_state, "idle")


class VoiceInput(Input):
    """Input that starts recording when space is held for ~600 ms."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._vr: VoiceRecorder | None = VoiceRecorder() if is_available() else None
        self._v_pending = False
        self._v_space_idx: int | None = None  # index of pending space in self.value
        self._v_recording = False
        self._v_repeat_timer = None
        self._v_release_timer = None

    def on_key(self, event: Key) -> None:
        if self._vr is None:
            return

        if event.key != "space":
            if self._v_pending:
                self._v_pending = False
                self._v_space_idx = None
                if self._v_repeat_timer:
                    self._v_repeat_timer.stop()
                    self._v_repeat_timer = None
            return

        # Input._on_key already inserted the space; cursor is now past it.
        pos = self.cursor_position  # space is at pos-1

        if self._v_recording:
            self._v_delete_val(pos - 1)
            if self._v_release_timer:
                self._v_release_timer.stop()
            self._v_release_timer = self.set_timer(RELEASE_DELAY, self._v_on_release)
            event.stop()
            return

        if not self._v_pending:
            if pos > 0 and pos - 1 < len(self.value) and self.value[pos - 1] == " ":
                self._v_space_idx = pos - 1
                self._v_pending = True
                self._v_repeat_timer = self.set_timer(REPEAT_DELAY, self._v_on_no_repeat)
        else:
            self._v_pending = False
            if self._v_repeat_timer:
                self._v_repeat_timer.stop()
                self._v_repeat_timer = None

            # Delete repeat space (at pos-1), then pending space (earlier, unaffected).
            self._v_delete_val(pos - 1)
            if self._v_space_idx is not None:
                self._v_delete_val(self._v_space_idx)
                self._v_space_idx = None

            if self._vr.start():
                self._v_recording = True
                self.app.set_voice_state("recording")
                self._v_release_timer = self.set_timer(RELEASE_DELAY, self._v_on_release)
            event.stop()

    def _v_delete_val(self, idx: int) -> None:
        """Delete character at idx in self.value — only if it is a space."""
        if 0 <= idx < len(self.value) and self.value[idx] == " ":
            val = self.value
            self.value = val[:idx] + val[idx + 1:]
            if self.cursor_position > idx:
                self.cursor_position -= 1

    def _v_on_no_repeat(self) -> None:
        self._v_pending = False
        self._v_space_idx = None
        self._v_repeat_timer = None

    def _v_on_release(self) -> None:
        self._v_release_timer = None
        self._v_recording = False
        wav = self._vr.stop_and_save()
        if wav:
            self.app.set_voice_state("transcribing")
            threading.Thread(target=self._v_transcribe, args=(wav,), daemon=True).start()
        else:
            self.app.set_voice_state("idle")

    def _v_transcribe(self, wav_path: str) -> None:
        try:
            text = transcribe_file(wav_path)
        finally:
            try:
                os.unlink(wav_path)
            except OSError:
                pass
        if text:
            self.call_from_thread(self._v_insert_text, text)
        self.call_from_thread(self.app.set_voice_state, "idle")

    def _v_insert_text(self, text: str) -> None:
        pos = self.cursor_position
        self.value = self.value[:pos] + text + self.value[pos:]
        self.cursor_position = pos + len(text)


class EntryFormScreen(ModalScreen[Optional[EntryFormData]]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, entry: JournalEntry | None = None) -> None:
        super().__init__()
        self.entry = entry

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Edit journal entry" if self.entry else "New journal entry", classes="modal_title"),
            VoiceInput(value=self.entry.title if self.entry else "", placeholder="Title", id="entry-title"),
            VoiceTextArea(
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
        self.query_one("#entry-title", VoiceInput).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        self._submit()

    def _submit(self) -> None:
        title = self.query_one("#entry-title", VoiceInput).value.strip()
        content = self.query_one("#entry-content", VoiceTextArea).text.strip()
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
            VoiceInput(value=self.todo.title if self.todo else "", placeholder="Todo title", id="todo-title"),
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
        self.query_one("#todo-title", VoiceInput).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        self._submit()

    def _submit(self) -> None:
        title = self.query_one("#todo-title", VoiceInput).value.strip()
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
