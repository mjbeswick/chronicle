"""Year-view calendar widget for Chronicle."""

from __future__ import annotations

from calendar import monthcalendar, monthrange
from datetime import date, timedelta

from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import Static

from app.voice import ViewVoiceHoldHandler


def _render_month(
    year: int,
    month: int,
    today: date,
    cursor: date | None,
    entry_dates: set[date],
    due_dates: set[date],
    overdue_dates: set[date],
) -> Text:
    text = Text(overflow="fold", no_wrap=True)
    text.append("Mo Tu We Th Fr Sa Su\n", style="dim")

    for week in monthcalendar(year, month):
        for col, day in enumerate(week):
            if day == 0:
                text.append("   ")
            else:
                d = date(year, month, day)
                s = f"{day:2d}"
                is_cursor = cursor is not None and d == cursor
                if d == today and is_cursor:
                    style = "bold reverse on $accent"
                elif is_cursor:
                    style = "bold reverse cyan"
                elif d == today:
                    style = "bold reverse"
                elif d in overdue_dates:
                    style = "bold red"
                elif d in due_dates:
                    style = "bold yellow"
                elif d in entry_dates:
                    style = "bold green"
                else:
                    style = "dim" if col >= 5 else ""
                text.append(s, style=style)
            if col < 6:
                text.append(" ")
        text.append("\n")

    return text


class CalendarView(Container):
    """Year-view calendar showing 12 months in a 4×3 grid."""

    BINDINGS = [
        Binding("left", "cursor_days(-1)", "Prev day", show=False),
        Binding("right", "cursor_days(1)", "Next day", show=False),
        Binding("up", "cursor_days(-7)", "Prev week", show=False),
        Binding("down", "cursor_days(7)", "Next week", show=False),
        Binding("shift+left", "prev_year", "Prev year", show=False),
        Binding("shift+right", "next_year", "Next year", show=False),
        Binding("tab", "cursor_months(1)", "Next month", show=False),
        Binding("shift+tab", "cursor_months(-1)", "Prev month", show=False),
        Binding("y", "jump_to_year", "Year", show=False),
        Binding("home", "today", show=False),
        Binding("enter", "activate_cursor", "Open", show=False),
    ]

    DEFAULT_CSS = """
    CalendarView {
        height: 1fr;
        overflow-y: auto;
    }

    #calendar-display {
        padding: 1 2;
    }
    """

    can_focus = True

    def __init__(self) -> None:
        super().__init__()
        self._today = date.today()
        self._cursor = self._today
        self._year = self._cursor.year
        self._entry_dates: set[date] = set()
        self._due_dates: set[date] = set()
        self._overdue_dates: set[date] = set()
        self._voice = ViewVoiceHoldHandler(
            self, on_transcript=lambda t: self.app.voice_create_for_active_tab(t)
        )

    def on_key(self, event) -> None:
        if self._voice.handle_key(event):
            event.stop()

    def compose(self) -> ComposeResult:
        yield Static("", id="calendar-display", markup=False)

    def on_mount(self) -> None:
        self._render_calendar()

    def refresh_view(
        self,
        entry_dates: set[date],
        due_dates: set[date],
        overdue_dates: set[date],
    ) -> None:
        self._entry_dates = entry_dates
        self._due_dates = due_dates
        self._overdue_dates = overdue_dates
        self._render_calendar()

    # --------------------------------------------------------------- rendering

    def _render_calendar(self) -> None:
        cursor = self._cursor if self._cursor.year == self._year else None
        table = Table(box=None, padding=(0, 1), show_header=False, expand=True)
        for _ in range(4):
            table.add_column(ratio=1)

        for row_start in range(0, 12, 4):
            panels: list[Panel] = []
            for month in range(row_start + 1, row_start + 5):
                month_name = date(self._year, month, 1).strftime("%B")
                month_text = _render_month(
                    self._year,
                    month,
                    self._today,
                    cursor,
                    self._entry_dates,
                    self._due_dates,
                    self._overdue_dates,
                )
                panels.append(Panel(month_text, title=month_name, title_align="left", padding=(0, 0)))
            table.add_row(*panels)

        year_line = Text(justify="center")
        year_line.append("← ", style="dim")
        year_line.append(str(self._year), style="bold")
        year_line.append(" →", style="dim")

        from rich.console import Group
        renderable = Group(year_line, table)
        self.query_one("#calendar-display", Static).update(renderable)

    # ---------------------------------------------------------------- cursor

    def _move_cursor(self, new_cursor: date) -> None:
        self._cursor = new_cursor
        if new_cursor.year != self._year:
            self._year = new_cursor.year
        self._render_calendar()

    def action_cursor_days(self, days: int) -> None:
        self._move_cursor(self._cursor + timedelta(days=days))

    def action_cursor_months(self, months: int) -> None:
        year = self._cursor.year
        month = self._cursor.month + months
        while month < 1:
            month += 12
            year -= 1
        while month > 12:
            month -= 12
            year += 1
        last_day = monthrange(year, month)[1]
        day = min(self._cursor.day, last_day)
        self._move_cursor(date(year, month, day))

    def action_prev_year(self) -> None:
        self._year -= 1
        # Clamp cursor to same month/day in new year (handles Feb 29 → 28).
        try:
            self._cursor = self._cursor.replace(year=self._year)
        except ValueError:
            self._cursor = self._cursor.replace(year=self._year, day=28)
        self._render_calendar()

    def action_next_year(self) -> None:
        self._year += 1
        try:
            self._cursor = self._cursor.replace(year=self._year)
        except ValueError:
            self._cursor = self._cursor.replace(year=self._year, day=28)
        self._render_calendar()

    def action_today(self) -> None:
        self._today = date.today()
        self._cursor = self._today
        self._year = self._today.year
        self._render_calendar()

    def action_jump_to_year(self) -> None:
        from app.forms import JumpToYearScreen

        def _apply(year: int | None) -> None:
            if year is None:
                return
            self._year = year
            try:
                self._cursor = self._cursor.replace(year=year)
            except ValueError:
                self._cursor = self._cursor.replace(year=year, day=28)
            self._render_calendar()

        self.app.push_screen(JumpToYearScreen(self._year), _apply)

    def set_year(self, year: int) -> None:
        self._year = year
        self._render_calendar()

    # -------------------------------------------------------- activation

    def action_activate_cursor(self) -> None:
        self._activate(self._cursor)

    def _activate(self, target: date) -> None:
        app = self.app
        today = date.today()
        if target > today:
            from app.forms import ItemFormScreen

            app.push_screen(
                ItemFormScreen(initial_due=target),
                lambda result: app._handle_new_from_calendar(result),
            )
        else:
            app._goto_journal_for_day(target)

    # -------------------------------------------------------- mouse click

    def on_click(self, event) -> None:
        target = self._date_at(event.x, event.y)
        if target is None:
            return
        self._move_cursor(target)
        event.stop()
        self._activate(target)

    def _date_at(self, x: int, y: int) -> date | None:
        """Map a click inside #calendar-display to a date.

        Geometry: year-line is row 0 of the display; the month grid below is
        3 rows × 4 columns of Panels (border + header + 6 week rows + border).
        Each week row shows 7 day cells of width 2, separated by single spaces.
        """
        display = self.query_one("#calendar-display", Static)
        inner_w = display.content_size.width
        inner_h = display.content_size.height
        if inner_w <= 0 or inner_h <= 0:
            return None

        # Translate to content coordinates.
        pad_x, pad_y = 2, 1  # matches CSS padding
        lx, ly = x - pad_x, y - pad_y
        if ly < 1:  # year line; ignore
            return None
        ly -= 1  # skip year line

        col_w = inner_w / 4
        month_h = 9  # 1 border + 1 header + 6 weeks + 1 border
        row = ly // month_h
        col = int(lx // col_w)
        inner_row = ly - row * month_h
        if not (0 <= row < 3 and 0 <= col < 4):
            return None
        # Within a month panel: row 0 = top border, 1 = "Mo Tu …", 2-7 = weeks, 8 = bottom border
        if not (2 <= inner_row <= 7):
            return None
        week_idx = inner_row - 2

        # Column within the panel: panel starts at col*col_w; content starts at
        # col_w*col + 1 (left border). Day cells are "dd " patterns = 3 chars each.
        panel_x0 = col * col_w + 1  # +1 for left border
        cell = (lx - panel_x0) // 3
        if not (0 <= cell < 7):
            return None

        month = row * 4 + col + 1
        weeks = monthcalendar(self._year, month)
        if week_idx >= len(weeks):
            return None
        day = weeks[week_idx][int(cell)]
        if day == 0:
            return None
        return date(self._year, month, day)
