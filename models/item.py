"""Unified Item model for Chronicle.

One entity with optional time coordinates. Lens membership (Journal / Todos /
Notes / Calendar) is derived from which fields are set. See CLAUDE.md and
PLAN.md for the rationale.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any
from uuid import uuid4


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_id() -> str:
    return f"item_{uuid4().hex[:12]}"


def _parse_dt(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def _parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(value)


@dataclass
class Item:
    """A single thing. Time fields are optional and determine lens membership.

    - `at`: the item's anchor moment. Past → recorded / occurred.
      Future → scheduled / event.
    - `due`: deadline (day-precision).
    - `done_at`: marked complete. None = open.
    """

    id: str
    title: str
    body: str = ""
    tags: list[str] = field(default_factory=list)
    parent_id: str | None = None

    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    at: datetime | None = None
    due: date | None = None
    done_at: datetime | None = None

    # ----------------------------------------------------------- derived state

    @property
    def is_done(self) -> bool:
        return self.done_at is not None

    def in_journal(self, now: datetime | None = None) -> bool:
        """Past-anchored items + anything completed."""
        ref = now or utc_now()
        if self.at is not None and self.at <= ref:
            return True
        if self.done_at is not None:
            return True
        return False

    def in_todos(self, now: datetime | None = None) -> bool:
        """Open actionable items — everything open that isn't already a
        journal entry (past-anchored) or a pure note (untimed body)."""
        if self.done_at is not None:
            return False
        ref = now or utc_now()
        if self.at is not None and self.at <= ref:
            return False
        if self.in_notes():
            return False
        return True

    def in_calendar(self) -> bool:
        """Anything with a date coordinate."""
        return self.at is not None or self.due is not None

    def in_notes(self) -> bool:
        """Untimed items with body content — reference material."""
        return (
            self.at is None
            and self.due is None
            and self.done_at is None
            and bool(self.body.strip())
        )

    def timeline_at(self, now: datetime | None = None) -> datetime:
        """Best single anchor for chronological rendering."""
        if self.at is not None:
            return self.at
        if self.done_at is not None:
            return self.done_at
        return self.created_at

    # ---------------------------------------------------------- serialization

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "body": self.body,
            "tags": list(self.tags),
            "parent_id": self.parent_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "at": self.at.isoformat() if self.at else None,
            "due": self.due.isoformat() if self.due else None,
            "done_at": self.done_at.isoformat() if self.done_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Item":
        return cls(
            id=data["id"],
            title=data.get("title", ""),
            body=data.get("body", ""),
            tags=list(data.get("tags", [])),
            parent_id=data.get("parent_id"),
            created_at=_parse_dt(data.get("created_at")) or utc_now(),
            updated_at=_parse_dt(data.get("updated_at")) or utc_now(),
            at=_parse_dt(data.get("at")),
            due=_parse_date(data.get("due")),
            done_at=_parse_dt(data.get("done_at")),
        )
