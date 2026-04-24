from __future__ import annotations

import re
from datetime import date, timedelta

from rich.text import Text


def parse_relative_offset(raw: str, *, allow_hours: bool = False) -> timedelta | None:
    """Parse a relative offset string into a timedelta.

    Supported formats:
      -2d  -1w  +3d  +2w  2d  1w   (always supported)
      -3h  +1h  2h                  (only when allow_hours=True)

    Returns a negative timedelta for past offsets, positive for future.
    Returns None if the string doesn't match.
    """
    units = "dwh" if allow_hours else "dw"
    m = re.match(rf"^([+-]?)(\d+)([{units}])$", raw.strip().lower())
    if not m:
        return None
    sign, n, unit = m.groups()
    n = int(n)
    if unit == "d":
        delta = timedelta(days=n)
    elif unit == "w":
        delta = timedelta(weeks=n)
    elif unit == "h":
        delta = timedelta(hours=n)
    else:
        return None
    return -delta if sign == "-" else delta


def format_due_date(d: date, *, completed: bool = False) -> Text:
    """Return a human-friendly, styled Rich Text for a due date."""
    today = date.today()
    delta = (d - today).days

    if completed:
        return Text(d.strftime("%b %-d"), style="dim")
    if delta < 0:
        days_over = -delta
        label = f"{days_over}d overdue" if days_over <= 14 else d.strftime("%b %-d")
        return Text(label, style="bold red")
    if delta == 0:
        return Text("Today", style="bold yellow")
    if delta == 1:
        return Text("Tomorrow", style="green")
    if delta <= 6:
        return Text(d.strftime("%A"), style="")
    return Text(d.strftime("%b %-d"), style="dim")


def parse_due_date(raw: str) -> date | None:
    """Parse a user-supplied due date string.

    Accepts: today, tomorrow, yesterday, in N days, N days, YYYY-MM-DD.
    Returns None on parse failure.
    """
    raw = raw.strip().lower()
    if not raw:
        return None

    today = date.today()

    if raw == "today":
        return today
    if raw in ("tomorrow", "tmr"):
        return today + timedelta(days=1)
    if raw == "yesterday":
        return today - timedelta(days=1)

    m = re.match(r"^in (\d+) days?$", raw)
    if m:
        return today + timedelta(days=int(m.group(1)))

    m = re.match(r"^(\d+) days?$", raw)
    if m:
        return today + timedelta(days=int(m.group(1)))

    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None
