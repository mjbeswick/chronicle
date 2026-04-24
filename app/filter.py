"""Filter spec and helpers used by all Chronicle views."""

from __future__ import annotations

import re
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass
class FilterSpec:
    text: str = ""
    fuzzy: bool = False
    tag: str | None = None
    date_from: date | None = None
    date_to: date | None = None

    @property
    def is_active(self) -> bool:
        return (
            bool(self.text)
            or self.tag is not None
            or self.date_from is not None
            or self.date_to is not None
        )

    def summary(self) -> str:
        parts = []
        if self.text:
            parts.append(f'~"{self.text}"' if self.fuzzy else f'"{self.text}"')
        if self.tag:
            parts.append(f"#{self.tag}")
        if self.date_from and self.date_to:
            parts.append(
                f"{self.date_from.strftime('%-d %b')} – {self.date_to.strftime('%-d %b')}"
            )
        elif self.date_from:
            parts.append(f"from {self.date_from.strftime('%-d %b')}")
        elif self.date_to:
            parts.append(f"until {self.date_to.strftime('%-d %b')}")
        return "  ".join(parts)


def parse_filter_date(raw: str, *, side: str = "from") -> date | None:
    """Parse a filter date string.

    side="from"  → range phrases resolve to the START of the period.
    side="to"    → range phrases resolve to the END of the period.

    Accepted: today, yesterday, this week, last week, this month,
              last month, N days ago, Nd, Nw, YYYY-MM-DD.

    Returns None on parse failure (never silently returns a broader date).
    """
    raw = raw.strip().lower()
    if not raw:
        return None

    today = date.today()

    if raw == "today":
        return today
    if raw == "yesterday":
        return today - timedelta(days=1)

    if raw == "this week":
        monday = today - timedelta(days=today.weekday())
        return monday if side == "from" else monday + timedelta(days=6)

    if raw == "last week":
        monday = today - timedelta(days=today.weekday() + 7)
        return monday if side == "from" else monday + timedelta(days=6)

    if raw == "this month":
        if side == "from":
            return today.replace(day=1)
        _, last_day = monthrange(today.year, today.month)
        return today.replace(day=last_day)

    if raw == "last month":
        first_of_this = today.replace(day=1)
        last_of_last = first_of_this - timedelta(days=1)
        return last_of_last.replace(day=1) if side == "from" else last_of_last

    m = re.match(r"^(\d+) days? ago$", raw)
    if m:
        return today - timedelta(days=int(m.group(1)))

    m = re.match(r"^(\d+)d$", raw)
    if m:
        return today - timedelta(days=int(m.group(1)))

    m = re.match(r"^(\d+)w$", raw)
    if m:
        return today - timedelta(weeks=int(m.group(1)))

    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _fuzzy_match(query: str, text: str) -> bool:
    """True iff every character of query appears in text in order."""
    qi = 0
    for ch in text:
        if qi < len(query) and ch == query[qi]:
            qi += 1
    return qi == len(query)


def matches_text(spec: FilterSpec, *fields: str) -> bool:
    """True if spec has no text filter, or any field satisfies it."""
    if not spec.text:
        return True
    q = spec.text.lower()
    if spec.fuzzy:
        return any(_fuzzy_match(q, f.lower()) for f in fields)
    return any(q in f.lower() for f in fields)


def matches_tag(spec: FilterSpec, tags: list[str]) -> bool:
    """True if spec has no tag filter, or the tag is present."""
    return spec.tag is None or spec.tag in tags


def matches_date(spec: FilterSpec, d: date | None) -> bool:
    """True if d falls within the spec's date range.

    A None date only matches when no date filter is active.
    """
    if d is None:
        return spec.date_from is None and spec.date_to is None
    if spec.date_from and d < spec.date_from:
        return False
    if spec.date_to and d > spec.date_to:
        return False
    return True
