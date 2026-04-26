"""Schedule view — chronological agenda for upcoming items."""

from __future__ import annotations

from datetime import date, timedelta

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.widgets import Static

from app.models import Item, utc_now
from app.utils import format_due_date
from app.voice import ViewVoiceHoldHandler


def _format_time(item: Item) -> str:
    """Format the time portion of an item's 'at' field."""
    if item.at:
        local = item.at.astimezone()
        return local.strftime("%I:%M %p").lstrip("0")
    return ""


def _date_header_text(d: date, today: date) -> str:
    """Format a date as a section header."""
    delta = (d - today).days
    if delta == 0:
        return "Today"
    elif delta == 1:
        return "Tomorrow"
    else:
        return d.strftime("%a %b %-d")


def _render_schedule_items(items: list[Item], today: date) -> Text:
    """Render items grouped by date."""
    if not items:
        text = Text("No items scheduled in the next 7 days.\n", style="dim italic")
        text.append("\nPress ", style="dim")
        text.append("n", style="bold")
        text.append(" to create a new item.", style="dim")
        return text

    # Group items by their display date
    by_date: dict[date, list[Item]] = {}
    for item in items:
        display_date = item.at.astimezone().date() if item.at else item.due
        if display_date is None:
            continue
        if display_date not in by_date:
            by_date[display_date] = []
        by_date[display_date].append(item)

    # Sort dates
    sorted_dates = sorted(by_date.keys())

    text = Text(overflow="fold")
    for i, d in enumerate(sorted_dates):
        if i > 0:
            text.append("\n")
        
        # Date header
        header = _date_header_text(d, today)
        text.append(f"{header}\n", style="bold cyan")
        
        # Items for this date
        for item in sorted(by_date[d], key=lambda it: it.at if it.at else it.created_at):
            # Checkbox
            if item.is_done:
                text.append("  ☑ ", style="dim")
            else:
                text.append("  ☐ ")
            
            # Time if available
            time_str = _format_time(item)
            if time_str:
                text.append(f"{time_str}  ", style="yellow")
            
            # Title
            title_style = "dim" if item.is_done else ""
            text.append(item.title, style=title_style)
            
            # Due date indicator if different from display date
            if item.due and item.due != d:
                due = format_due_date(item.due, completed=item.is_done)
                text.append("  ")
                text.append(due)
            
            text.append("\n")
    
    return text


class ScheduleView(Container):
    """Timeline view showing upcoming items for the next 7 days."""

    BINDINGS = [
        Binding("n", "new_item", "New", show=False),
        Binding("e", "edit_selected", "Edit", show=False),
        Binding("d", "delete_selected", "Delete", show=False),
        Binding("v", "view_selected", "View", show=False),
        Binding("x", "toggle_todo", "Toggle", show=False, priority=True),
        Binding("hash", "tag_item", "Tag", show=False),
        Binding("question_mark", "open_help", "Help", show=False),
    ]

    DEFAULT_CSS = """
    ScheduleView {
        height: 1fr;
        overflow-y: auto;
    }

    #schedule-display {
        padding: 1 2;
    }
    """

    can_focus = True

    def __init__(self) -> None:
        super().__init__()
        self._items: list[Item] = []
        self._voice = ViewVoiceHoldHandler(
            self, on_transcript=lambda t: self.app.voice_create_for_active_tab(t)
        )

    def on_key(self, event) -> None:
        if self._voice.handle_key(event):
            event.stop()

    def compose(self) -> ComposeResult:
        yield Static("", id="schedule-display", markup=False)

    def on_mount(self) -> None:
        self._render()

    def refresh_view(self, items: list[Item]) -> None:
        """Update with new items."""
        self._items = items
        self._render()

    def _render(self) -> None:
        today = date.today()
        content = _render_schedule_items(self._items, today)
        self.query_one("#schedule-display", Static).update(content)

    def focus_content(self) -> None:
        """Focus this view (called by app when switching tabs)."""
        self.focus()

    def selected_item(self) -> Item | None:
        """Return the currently selected item (for edit/delete/view actions)."""
        # For now, no selection model — future enhancement could add cursor navigation
        return None
