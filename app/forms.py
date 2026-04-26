from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Markdown, Static, TextArea

from .filter import FilterSpec, parse_filter_date
from .models import Item, utc_now
from .utils import format_due_date, parse_due_date
from .voice import RELEASE_DELAY, REPEAT_DELAY, VoiceRecorder, is_available, transcribe_file


# ---------------------------------------------------------------------------
# Datetime parsing helpers
# ---------------------------------------------------------------------------

def parse_at(raw: str, *, fallback: datetime | None = None) -> datetime | None:
    """Parse a user datetime string into an aware datetime (local tz).

    Accepts: YYYY-MM-DD, YYYY-MM-DD HH:MM, YYYY-MM-DDTHH:MM,
             now, today, yesterday, tomorrow, N days ago.
    Returns None on parse failure.
    """
    raw = raw.strip()
    if not raw:
        return None

    anchor = (fallback or datetime.now()).astimezone()
    local_tz = anchor.tzinfo
    today = anchor.date()

    def _with_date(d: date) -> datetime:
        return anchor.replace(year=d.year, month=d.month, day=d.day)

    low = raw.lower()
    if low == "now":
        return datetime.now().astimezone()
    if low == "today":
        return _with_date(today)
    if low == "yesterday":
        return _with_date(today - timedelta(days=1))
    if low == "tomorrow":
        return _with_date(today + timedelta(days=1))

    m = re.match(r"^(\d+) days? ago$", low)
    if m:
        return _with_date(today - timedelta(days=int(m.group(1))))

    try:
        return _with_date(date.fromisoformat(raw))
    except ValueError:
        pass

    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            naive = datetime.strptime(raw, fmt)
            return naive.replace(tzinfo=local_tz)
        except ValueError:
            continue

    return None


# ---------------------------------------------------------------------------
# Form data container
# ---------------------------------------------------------------------------

@dataclass
class ItemFormData:
    title: str
    body: str
    tags: list[str] = field(default_factory=list)
    at: datetime | None = None
    due: date | None = None
    done: bool = False


# ---------------------------------------------------------------------------
# Voice-aware widgets — hold-space within a text field to record + transcribe.
# ---------------------------------------------------------------------------

class VoiceTextArea(TextArea):
    """TextArea that starts recording when space is held for ~600 ms."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._vr: VoiceRecorder | None = VoiceRecorder() if is_available() else None
        self._v_pending = False
        self._v_space: tuple[int, int] | None = None
        self._v_recording = False
        self._v_repeat_timer = None
        self._v_release_timer = None

    def on_key(self, event: Key) -> None:
        if self._vr is None:
            return
        if event.key != "space":
            if self._v_pending:
                self._v_pending = False
                self._v_space = None
                if self._v_repeat_timer:
                    self._v_repeat_timer.stop()
                    self._v_repeat_timer = None
            return

        row, col = self.cursor_location
        if self._v_recording:
            self._v_delete_doc(row, col - 1)
            if self._v_release_timer:
                self._v_release_timer.stop()
            self._v_release_timer = self.set_timer(RELEASE_DELAY, self._v_on_release)
            event.stop()
            return

        if not self._v_pending:
            if col > 0:
                line = self.document.get_line(row)
                if col - 1 < len(line) and line[col - 1] == " ":
                    self._v_space = (row, col - 1)
                    self._v_pending = True
                    self._v_repeat_timer = self.set_timer(REPEAT_DELAY, self._v_on_no_repeat)
        else:
            self._v_pending = False
            if self._v_repeat_timer:
                self._v_repeat_timer.stop()
                self._v_repeat_timer = None
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
        if col < 0:
            return
        line = self.document.get_line(row)
        if col < len(line) and line[col] == " ":
            self.delete((row, col), (row, col + 1))

    def _v_on_no_repeat(self) -> None:
        self._v_pending = False
        self._v_space = None
        self._v_repeat_timer = None

    def _v_on_release(self) -> None:
        self._v_release_timer = None
        self._v_recording = False
        wav = self._vr.stop_and_save()
        if wav:
            app = self.app
            app.set_voice_state("transcribing")
            threading.Thread(target=self._v_transcribe, args=(wav, app), daemon=True).start()
        else:
            self.app.set_voice_state("idle")

    def _v_transcribe(self, wav_path: str, app) -> None:
        text = None
        try:
            text = transcribe_file(wav_path)
        except Exception:
            pass
        try:
            os.unlink(wav_path)
        except OSError:
            pass
        try:
            app.call_from_thread(app.set_voice_state, "idle")
        except Exception:
            pass
        try:
            if text:
                app.call_from_thread(self.insert, text)
            else:
                app.call_from_thread(app.notify, "Transcription failed.", severity="warning")
        except Exception:
            pass


class VoiceInput(Input):
    """Input that starts recording when space is held for ~600 ms."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._vr: VoiceRecorder | None = VoiceRecorder() if is_available() else None
        self._v_pending = False
        self._v_space_idx: int | None = None
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

        pos = self.cursor_position
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
            app = self.app
            app.set_voice_state("transcribing")
            threading.Thread(target=self._v_transcribe, args=(wav, app), daemon=True).start()
        else:
            self.app.set_voice_state("idle")

    def _v_transcribe(self, wav_path: str, app) -> None:
        text = None
        try:
            text = transcribe_file(wav_path)
        except Exception:
            pass
        try:
            os.unlink(wav_path)
        except OSError:
            pass
        try:
            app.call_from_thread(app.set_voice_state, "idle")
        except Exception:
            pass
        try:
            if text:
                app.call_from_thread(self._v_insert_text, text)
            else:
                app.call_from_thread(app.notify, "Transcription failed.", severity="warning")
        except Exception:
            pass

    def _v_insert_text(self, text: str) -> None:
        pos = self.cursor_position
        self.value = self.value[:pos] + text + self.value[pos:]
        self.cursor_position = pos + len(text)


# ---------------------------------------------------------------------------
# Unified ItemFormScreen — replaces Entry / Todo / Note form screens.
# ---------------------------------------------------------------------------

class ItemFormScreen(ModalScreen[Optional[ItemFormData]]):
    BINDINGS = [
        ("escape,ctrl+w", "cancel", "Cancel"),
        ("ctrl+enter", "save", "Save"),
    ]

    DEFAULT_CSS = """
    ItemFormScreen .form_row {
        height: auto;
        margin-bottom: 1;
        padding-right: 1;
    }
    ItemFormScreen .form_row Input {
        width: 1fr;
    }
    ItemFormScreen .form_row Input:first-of-type {
        margin-right: 1;
    }
    ItemFormScreen #item-title {
        margin-bottom: 1;
    }
    ItemFormScreen #item-body {
        height: 10;
    }
    ItemFormScreen Checkbox {
        width: auto;
        padding-left: 1;
    }
    """

    def __init__(
        self,
        item: Item | None = None,
        *,
        initial_title: str | None = None,
        initial_at: datetime | None = None,
        initial_due: date | None = None,
        default_tags: list[str] | None = None,
    ) -> None:
        super().__init__()
        self.item = item
        self._initial_title = initial_title or ""
        self._initial_at = initial_at
        self._initial_due = initial_due
        self._default_tags = default_tags or []

    def compose(self) -> ComposeResult:
        if self.item:
            title_val = self.item.title
            body_val = self.item.body
            tags_val = ", ".join(self.item.tags)
            at_val = self.item.at.astimezone().strftime("%Y-%m-%d %H:%M") if self.item.at else ""
            due_val = self.item.due.isoformat() if self.item.due else ""
            done_val = self.item.is_done
        else:
            title_val = self._initial_title
            body_val = ""
            tags_val = ", ".join(self._default_tags)
            at_val = self._initial_at.astimezone().strftime("%Y-%m-%d %H:%M") if self._initial_at else ""
            due_val = self._initial_due.isoformat() if self._initial_due else ""
            done_val = False

        yield Vertical(
            Label("Edit item" if self.item else "New item", classes="modal_title"),
            VoiceInput(value=title_val, placeholder="Title", id="item-title"),
            Horizontal(
                Input(value=at_val, placeholder="When (today, now, YYYY-MM-DD HH:MM…)", id="item-at"),
                Input(value=due_val, placeholder="Due (today, in 3 days, YYYY-MM-DD…)", id="item-due"),
                classes="form_row",
            ),
            Horizontal(
                Input(value=tags_val, placeholder="Tags (comma-separated)", id="item-tags"),
                Checkbox("Done", value=done_val, id="item-done"),
                classes="form_row",
            ),
            VoiceTextArea(body_val, id="item-body"),
            Label("", id="item-error", classes="modal_error"),
            Horizontal(
                Button("Cancel", id="cancel"),
                Button("Save", id="save", variant="primary"),
                classes="modal_actions",
            ),
            id="modal-body",
            classes="modal_window",
        )

    def on_mount(self) -> None:
        self.query_one("#item-title", VoiceInput).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_save(self) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        self._submit()

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        self._submit()

    def _submit(self) -> None:
        title = self.query_one("#item-title", VoiceInput).value.strip()
        body = self.query_one("#item-body", VoiceTextArea).text
        tags_raw = self.query_one("#item-tags", Input).value
        at_raw = self.query_one("#item-at", Input).value.strip()
        due_raw = self.query_one("#item-due", Input).value.strip()
        done = self.query_one("#item-done", Checkbox).value
        error = self.query_one("#item-error", Label)

        if not title:
            error.update("Title is required.")
            return

        at_val: datetime | None = None
        if at_raw:
            at_val = parse_at(at_raw, fallback=self.item.at if self.item else None)
            if at_val is None:
                error.update("Unrecognised 'when' — try YYYY-MM-DD HH:MM, 'now', 'yesterday'.")
                return

        due_val: date | None = None
        if due_raw:
            due_val = parse_due_date(due_raw)
            if due_val is None:
                error.update("Unrecognised due date — try 'today', 'in 3 days', or YYYY-MM-DD.")
                return

        tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
        self.dismiss(
            ItemFormData(
                title=title,
                body=body,
                tags=tags,
                at=at_val,
                due=due_val,
                done=done,
            )
        )


# ---------------------------------------------------------------------------
# Detail view for any Item.
# ---------------------------------------------------------------------------

class ItemDetailScreen(ModalScreen[None]):
    BINDINGS = [("escape,ctrl+w", "close", "Close")]

    def __init__(self, item: Item) -> None:
        super().__init__()
        self.item = item

    def compose(self) -> ComposeResult:
        created = self.item.created_at.astimezone().strftime("%Y-%m-%d %H:%M")
        meta_parts = [f"Created {created}"]
        if self.item.at:
            anchor = self.item.at.astimezone().strftime("%Y-%m-%d %H:%M")
            meta_parts.append(f"At {anchor}")
        if self.item.due:
            meta_parts.append(f"Due {self.item.due.isoformat()}")
        if self.item.done_at:
            done = self.item.done_at.astimezone().strftime("%Y-%m-%d %H:%M")
            meta_parts.append(f"Done {done}")
        meta = "  ·  ".join(meta_parts)

        if self.item.due and not self.item.is_done:
            due_line = format_due_date(self.item.due, completed=False)
        else:
            due_line = Text("")

        yield Vertical(
            Label(self.item.title, classes="modal_title"),
            Static(meta, classes="detail_meta"),
            Static(due_line, classes="detail_meta"),
            Markdown(self.item.body or "_No body._", classes="detail_markdown"),
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


# ---------------------------------------------------------------------------
# Confirm, Help, TagEdit, JumpToYear, Filter modals — unchanged
# ---------------------------------------------------------------------------

class ConfirmActionScreen(ModalScreen[bool]):
    BINDINGS = [
        ("escape,ctrl+w", "cancel", "Cancel"),
        ("ctrl+enter", "confirm", "Confirm"),
    ]

    def __init__(self, prompt: str, *, confirm_label: str = "Confirm") -> None:
        super().__init__()
        self.prompt = prompt
        self.confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        title = f"Confirm {self.confirm_label.lower()}"
        yield Vertical(
            Label(title, classes="modal_title"),
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

    def action_confirm(self) -> None:
        self.dismiss(True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm":
            self.dismiss(True)
        else:
            self.dismiss(False)


def _help_shortcuts() -> Text:
    bindings = [
        ("ctrl+j/t/n/s/c", "switch tabs (journal/todos/notes/schedule/calendar)"),
        ("n", "new item"),
        ("hold space", "voice-create new item"),
        ("v", "view selected"),
        ("e", "edit selected"),
        ("d", "delete selected"),
        ("x", "toggle done / open"),
        ("#", "edit tags"),
        ("ctrl+l", "cycle journal layout"),
        ("ctrl+enter", "save (in forms)"),
        ("?", "open help"),
        ("ctrl+q", "quit"),
    ]
    text = Text()
    for key, desc in bindings:
        text.append(f"  {key}", style="bold")
        text.append(f"  {desc}\n", style="dim")
    return text


class HelpScreen(ModalScreen[None]):
    BINDINGS = [("escape,ctrl+w", "close", "Close")]

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Chronicle shortcuts", classes="modal_title"),
            Static(_help_shortcuts()),
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


class TagEditScreen(ModalScreen["list[str] | None"]):
    BINDINGS = [
        ("escape,ctrl+w", "action_cancel", "Cancel"),
        ("ctrl+enter", "action_save", "Save"),
    ]

    def __init__(self, current_tags: list[str]) -> None:
        super().__init__()
        self._current_tags = current_tags

    def compose(self) -> ComposeResult:
        current = ", ".join(self._current_tags)
        yield Vertical(
            Label("Edit tags", classes="modal_title"),
            Input(value=current, placeholder="work, personal, …", id="tags-input"),
            Horizontal(
                Button("Cancel", id="cancel"),
                Button("Save", id="save", variant="primary"),
                classes="modal_actions",
            ),
            classes="modal_window",
        )

    def on_mount(self) -> None:
        self.query_one("#tags-input", Input).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_save(self) -> None:
        raw = self.query_one("#tags-input", Input).value
        tags = [t.strip() for t in raw.split(",") if t.strip()]
        self.dismiss(tags)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self.action_save()
        else:
            self.dismiss(None)

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        self.action_save()


class JumpToYearScreen(ModalScreen["int | None"]):
    BINDINGS = [
        ("escape,ctrl+w", "action_cancel", "Cancel"),
        ("ctrl+enter", "action_go", "Go"),
    ]

    def __init__(self, current_year: int) -> None:
        super().__init__()
        self._current_year = current_year

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Jump to year", classes="modal_title"),
            Input(value=str(self._current_year), placeholder="e.g. 2024", id="year-input"),
            Label("", id="year-error", classes="modal_error"),
            Horizontal(
                Button("Cancel", id="cancel"),
                Button("Go", id="save", variant="primary"),
                classes="modal_actions",
            ),
            classes="modal_window",
        )

    def on_mount(self) -> None:
        inp = self.query_one("#year-input", Input)
        inp.focus()
        inp.cursor_position = len(inp.value)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_go(self) -> None:
        self._submit()

    def _submit(self) -> None:
        raw = self.query_one("#year-input", Input).value.strip()
        error = self.query_one("#year-error", Label)
        try:
            year = int(raw)
        except ValueError:
            error.update("Enter a year like 2024.")
            return
        if not (1 <= year <= 9999):
            error.update("Year must be between 1 and 9999.")
            return
        self.dismiss(year)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        else:
            self._submit()

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        self._submit()


class FilterScreen(ModalScreen["FilterSpec | None"]):
    """Unified filter modal."""

    DEFAULT_CSS = """
    FilterScreen .filter_row {
        height: auto;
        margin-bottom: 1;
        padding-right: 1;
    }
    FilterScreen .filter_row Input {
        width: 1fr;
    }
    FilterScreen .filter_row Checkbox {
        width: auto;
        padding-left: 1;
        margin-right: 1;
    }
    FilterScreen .filter_label {
        width: 9;
        content-align: right middle;
        padding-right: 1;
        height: 3;
    }
    FilterScreen .filter_date_sep {
        width: auto;
        content-align: center middle;
        padding: 0 1;
        height: 3;
    }
    """

    BINDINGS = [
        ("escape,ctrl+w", "cancel", "Cancel"),
        ("ctrl+k", "clear", "Clear"),
        ("ctrl+enter", "apply", "Apply"),
    ]

    def __init__(self, spec: FilterSpec, all_tags: list[str]) -> None:
        super().__init__()
        self._spec = spec
        self._all_tags = all_tags

    def compose(self) -> ComposeResult:
        tag_hint = f"e.g. {self._all_tags[0]}" if self._all_tags else "tag name"
        yield Vertical(
            Label("Filter", classes="modal_title"),
            Horizontal(
                Label("Search", classes="filter_label"),
                Input(value=self._spec.text, placeholder="text to match", id="filter-text"),
                Checkbox("Fuzzy", value=self._spec.fuzzy, id="filter-fuzzy"),
                classes="filter_row",
            ),
            Horizontal(
                Label("Tag", classes="filter_label"),
                Input(value=self._spec.tag or "", placeholder=tag_hint, id="filter-tag"),
                classes="filter_row",
            ),
            Horizontal(
                Label("Date", classes="filter_label"),
                Input(
                    value=self._spec.date_from.isoformat() if self._spec.date_from else "",
                    placeholder="from…",
                    id="filter-from",
                ),
                Label("→", classes="filter_date_sep"),
                Input(
                    value=self._spec.date_to.isoformat() if self._spec.date_to else "",
                    placeholder="to…",
                    id="filter-to",
                ),
                classes="filter_row",
            ),
            Label("", id="filter-error", classes="modal_error"),
            Horizontal(
                Button("Clear", id="clear"),
                Button("Cancel", id="cancel"),
                Button("Apply", id="apply", variant="primary"),
                classes="modal_actions",
            ),
            classes="modal_window",
        )

    def on_mount(self) -> None:
        self.query_one("#filter-text", Input).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_clear(self) -> None:
        self.dismiss(FilterSpec())

    def action_apply(self) -> None:
        self._apply()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "clear":
            self.action_clear()
        elif event.button.id == "cancel":
            self.dismiss(None)
        else:
            self._apply()

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        self._apply()

    def _apply(self) -> None:
        text = self.query_one("#filter-text", Input).value.strip()
        fuzzy = self.query_one("#filter-fuzzy", Checkbox).value
        tag_raw = self.query_one("#filter-tag", Input).value.strip()
        from_raw = self.query_one("#filter-from", Input).value.strip()
        to_raw = self.query_one("#filter-to", Input).value.strip()
        error = self.query_one("#filter-error", Label)

        date_from = None
        date_to = None
        if from_raw:
            date_from = parse_filter_date(from_raw, side="from")
            if date_from is None:
                error.update("Unrecognised 'from' date.")
                return
        if to_raw:
            date_to = parse_filter_date(to_raw, side="to")
            if date_to is None:
                error.update("Unrecognised 'to' date.")
                return
        if date_from and date_to and date_from > date_to:
            error.update("'From' must be before 'To'.")
            return
        self.dismiss(
            FilterSpec(text=text, fuzzy=fuzzy, tag=tag_raw or None, date_from=date_from, date_to=date_to)
        )
