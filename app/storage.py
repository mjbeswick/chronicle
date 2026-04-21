from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
import os
from pathlib import Path
from typing import Protocol

from app.models import JournalEntry, TimelineDay, TimelineEvent, TodoItem
from models.storage import FileStorage
from platformdirs import user_data_dir

UNSET = object()


def default_project_root() -> Path:
    configured_home = os.environ.get("CHRONICLE_HOME")
    if configured_home:
        return Path(configured_home).expanduser().resolve()
    return Path(user_data_dir("chronicle", "mjbeswick")).resolve()


class StorageBackend(Protocol):
    def list_journal_entries(self) -> list[JournalEntry]:
        ...

    def list_todos(self) -> list[TodoItem]:
        ...

    def timeline_events_grouped_by_date(self) -> list[TimelineDay]:
        ...

    def create_entry(self, title: str, content: str) -> JournalEntry:
        ...

    def update_entry(self, entry_id: str, *, title: str, content: str, created_at: datetime | None = None) -> JournalEntry:
        ...

    def delete_entry(self, entry_id: str) -> None:
        ...
    def create_todo(self, title: str, due_date: date | None = None) -> TodoItem:
        ...

    def update_todo(
        self,
        todo_id: str,
        *,
        title: str,
        due_date: date | None | object = UNSET,
    ) -> TodoItem:
        ...

    def delete_todo(self, todo_id: str) -> None:
        ...

    def toggle_todo_completion(self, todo_id: str) -> TodoItem:
        ...


class ChronicleStorageAdapter(StorageBackend):
    def __init__(self, project_root: str | Path | None = None) -> None:
        root = Path(project_root).expanduser().resolve() if project_root is not None else default_project_root()
        self.backend = FileStorage(project_root=root)

    def list_journal_entries(self) -> list[JournalEntry]:
        return [self._map_entry(entry) for entry in self.backend.list_journal_entries()]

    def list_todos(self) -> list[TodoItem]:
        return [self._map_todo(todo) for todo in self.backend.list_todos(include_completed=True)]

    def timeline_events_grouped_by_date(self) -> list[TimelineDay]:
        grouped: dict[date, list[TimelineEvent]] = defaultdict(list)
        for event in self.backend.list_timeline_events():
            mapped = self._map_event(event)
            grouped[mapped.occurred_at.date()].append(mapped)
        return [
            TimelineDay(label=day, events=grouped[day])
            for day in sorted(grouped.keys(), reverse=True)
        ]

    def create_entry(self, title: str, content: str) -> JournalEntry:
        return self._map_entry(self.backend.create_journal_entry(title=title, content=content))

    def update_entry(self, entry_id: str, *, title: str, content: str, created_at: datetime | None = None) -> JournalEntry:
        return self._map_entry(self.backend.update_journal_entry(entry_id, title=title, content=content, created_at=created_at))

    def delete_entry(self, entry_id: str) -> None:
        self.backend.delete_journal_entry(entry_id)

    def create_todo(self, title: str, due_date: date | None = None) -> TodoItem:
        return self._map_todo(self.backend.create_todo(title=title, due_date=due_date))

    def update_todo(
        self,
        todo_id: str,
        *,
        title: str,
        due_date: date | None | object = UNSET,
    ) -> TodoItem:
        kwargs: dict[str, object] = {"title": title}
        if due_date is not UNSET:
            kwargs["due_date"] = due_date
        return self._map_todo(self.backend.update_todo(todo_id, **kwargs))

    def delete_todo(self, todo_id: str) -> None:
        self.backend.delete_todo(todo_id)

    def toggle_todo_completion(self, todo_id: str) -> TodoItem:
        return self._map_todo(self.backend.toggle_todo(todo_id))

    @staticmethod
    def _map_entry(entry) -> JournalEntry:
        return JournalEntry(
            id=entry.id,
            title=entry.title,
            content=entry.content,
            created_at=entry.created_at.astimezone(),
            updated_at=entry.updated_at.astimezone(),
        )

    @staticmethod
    def _map_todo(todo) -> TodoItem:
        completed_at = todo.completed_at.astimezone() if todo.completed_at else None
        return TodoItem(
            id=todo.id,
            title=todo.title,
            due_date=todo.due_date,
            completed=todo.completed,
            created_at=todo.created_at.astimezone(),
            updated_at=todo.updated_at.astimezone(),
            completed_at=completed_at,
        )

    @staticmethod
    def _map_event(event) -> TimelineEvent:
        source = "entry" if event.source_kind == "journal" else "todo_activity"
        return TimelineEvent(
            id=event.id,
            source=source,
            event_type=event.event_type,
            occurred_at=event.occurred_at.astimezone(),
            title=event.title,
            details=event.summary,
            entry_id=event.source_id if source == "entry" else None,
            todo_id=event.source_id if source == "todo_activity" else None,
        )
