from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal


TimelineSource = Literal["entry", "todo_activity"]


@dataclass
class JournalEntry:
    id: str
    title: str
    content: str
    created_at: datetime
    updated_at: datetime


@dataclass
class TodoItem:
    id: str
    title: str
    due_date: date | None
    completed: bool
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


@dataclass
class TimelineEvent:
    id: str
    source: TimelineSource
    event_type: str
    occurred_at: datetime
    title: str
    details: str
    entry_id: str | None = None
    todo_id: str | None = None

    @property
    def editable(self) -> bool:
        return self.source == "entry" and self.entry_id is not None


@dataclass
class TimelineDay:
    label: date
    events: list[TimelineEvent]
