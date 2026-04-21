"""File-based storage implementation for Chronicle."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from uuid import uuid4

from .journal_entry import JournalEntry
from .todo import UNSET, TodoItem


def utc_now() -> datetime:
    """Return an aware UTC timestamp."""
    return datetime.now(timezone.utc)


def slugify(value: str, default: str = "item") -> str:
    """Create a filesystem-friendly slug."""
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return normalized or default


def generate_id(prefix: str = "item") -> str:
    """Generate a readable unique identifier."""
    return f"{prefix}_{uuid4().hex[:12]}"


class StorageError(RuntimeError):
    """Raised when Chronicle cannot read or write persisted data."""


@dataclass(frozen=True)
class TimelineEvent:
    """A mixed journal/todo event displayed in the journal timeline."""

    id: str
    occurred_at: datetime
    event_type: str
    source_kind: str
    source_id: str
    title: str
    summary: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def date_key(self) -> str:
        return self.occurred_at.date().isoformat()


@dataclass(frozen=True)
class TimelineDay:
    """Timeline events grouped for a calendar day."""

    label: date
    events: list[TimelineEvent]


class FileStorage:
    """Persist Chronicle entries and todos as markdown and JSON files."""

    def __init__(self, project_root: str | Path = ".", data_root: str | Path | None = None) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.data_root = self._resolve_data_root(data_root)
        self.journal_dir = self.data_root / "journal"
        self.todo_dir = self.data_root / "todos"
        self.ensure_directories()

    def _resolve_data_root(self, data_root: str | Path | None) -> Path:
        if data_root is None:
            return (self.project_root / "data").resolve()
        candidate = Path(data_root).expanduser()
        return candidate.resolve() if candidate.is_absolute() else (self.project_root / candidate).resolve()

    def ensure_directories(self) -> None:
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        self.todo_dir.mkdir(parents=True, exist_ok=True)

    def create_journal_entry(
        self,
        title: str = "Untitled Entry",
        content: str = "",
        *,
        tags: Iterable[str] | None = None,
        created_at: datetime | None = None,
    ) -> JournalEntry:
        created = created_at or utc_now()
        entry = JournalEntry(
            id=generate_id("entry"),
            title=title,
            content=content,
            slug=slugify(title, "entry"),
            created_at=created,
            updated_at=created,
            tags=list(tags or []),
        )
        return self.save_journal_entry(entry, touch=False)

    def create_entry(
        self,
        title: str,
        content: str,
        *,
        tags: Iterable[str] | None = None,
        created_at: datetime | None = None,
    ) -> JournalEntry:
        return self.create_journal_entry(title, content, tags=tags, created_at=created_at)

    def save_journal_entry(self, entry: JournalEntry, *, touch: bool = True) -> JournalEntry:
        previous_stem = entry.file_stem
        entry.slug = slugify(entry.title, "entry")
        if touch:
            entry.updated_at = utc_now()
        entry.file_stem = self._journal_file_stem(entry)
        markdown_path, metadata_path = self._journal_paths(entry.file_stem)
        self._write_text(markdown_path, entry.content)
        self._write_json(metadata_path, entry.to_metadata_dict())
        if previous_stem and previous_stem != entry.file_stem:
            old_markdown_path, old_metadata_path = self._journal_paths(previous_stem)
            self._remove_if_exists(old_markdown_path)
            self._remove_if_exists(old_metadata_path)
        return entry

    def update_journal_entry(
        self,
        entry_id: str,
        *,
        title: str | None = None,
        content: str | None = None,
        tags: Iterable[str] | None = None,
        created_at: datetime | None = None,
    ) -> JournalEntry:
        entry = self.get_journal_entry(entry_id)
        if title is not None:
            entry.title = title
        if content is not None:
            entry.content = content
        if tags is not None:
            entry.tags = list(tags)
        if created_at is not None:
            entry.created_at = created_at
        return self.save_journal_entry(entry)

    def update_entry(
        self,
        entry_id: str,
        *,
        title: str | None = None,
        content: str | None = None,
        tags: Iterable[str] | None = None,
        created_at: datetime | None = None,
    ) -> JournalEntry:
        return self.update_journal_entry(entry_id, title=title, content=content, tags=tags, created_at=created_at)

    def get_journal_entry(self, entry_id: str) -> JournalEntry:
        for metadata_path in self._iter_json_files(self.journal_dir):
            metadata = self._read_json(metadata_path)
            if str(metadata.get("id")) != entry_id:
                continue
            markdown_path = metadata_path.with_suffix(".md")
            content = self._read_text(markdown_path)
            return JournalEntry.from_storage(metadata, content)
        raise StorageError(f"Journal entry not found: {entry_id}")

    def list_journal_entries(self) -> list[JournalEntry]:
        entries: list[JournalEntry] = []
        for metadata_path in self._iter_json_files(self.journal_dir):
            metadata = self._read_json(metadata_path)
            markdown_path = metadata_path.with_suffix(".md")
            content = self._read_text(markdown_path)
            entries.append(JournalEntry.from_storage(metadata, content))
        return sorted(entries, key=lambda entry: (entry.created_at, entry.id), reverse=True)

    def delete_journal_entry(self, entry_id: str) -> None:
        entry = self.get_journal_entry(entry_id)
        if not entry.file_stem:
            entry.file_stem = self._journal_file_stem(entry)
        markdown_path, metadata_path = self._journal_paths(entry.file_stem)
        self._remove_if_exists(markdown_path)
        self._remove_if_exists(metadata_path)

    def delete_entry(self, entry_id: str) -> None:
        self.delete_journal_entry(entry_id)

    def create_todo(
        self,
        title: str = "Untitled Todo",
        description: str = "",
        *,
        due_date: date | str | None = None,
        created_at: datetime | None = None,
    ) -> TodoItem:
        created = created_at or utc_now()
        todo = TodoItem(
            id=generate_id("todo"),
            title=title,
            slug=slugify(title, "todo"),
            description=description,
            due_date=due_date,
            created_at=created,
            updated_at=created,
        )
        todo.record_event("created", occurred_at=created, summary="TODO created")
        return self.save_todo(todo, touch=False)

    def save_todo(self, todo: TodoItem, *, touch: bool = True) -> TodoItem:
        todo.slug = slugify(todo.title, "todo")
        if touch:
            todo.updated_at = utc_now()
        self._write_json(self._todo_path(todo.id), todo.to_dict())
        return todo

    def update_todo(
        self,
        todo_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
        due_date: date | str | None | object = UNSET,
        occurred_at: datetime | None = None,
    ) -> TodoItem:
        todo = self.get_todo(todo_id, include_deleted=True)
        todo.apply_updates(title=title, description=description, due_date=due_date, occurred_at=occurred_at)
        return self.save_todo(todo, touch=False)

    def toggle_todo(
        self,
        todo_id: str,
        completed: bool | None = None,
        *,
        occurred_at: datetime | None = None,
    ) -> TodoItem:
        todo = self.get_todo(todo_id, include_deleted=True)
        target = (not todo.completed) if completed is None else completed
        todo.set_completed(target, occurred_at=occurred_at)
        return self.save_todo(todo, touch=False)

    def toggle_todo_completion(
        self,
        todo_id: str,
        completed: bool | None = None,
        *,
        occurred_at: datetime | None = None,
    ) -> TodoItem:
        return self.toggle_todo(todo_id, completed, occurred_at=occurred_at)

    def get_todo(self, todo_id: str, *, include_deleted: bool = True) -> TodoItem:
        path = self._todo_path(todo_id)
        if not path.exists():
            raise StorageError(f"Todo not found: {todo_id}")
        todo = TodoItem.from_dict(self._read_json(path))
        if todo.deleted and not include_deleted:
            raise StorageError(f"Todo not found: {todo_id}")
        return todo

    def list_todos(self, *, include_completed: bool = True, include_deleted: bool = False) -> list[TodoItem]:
        todos: list[TodoItem] = []
        for path in self._iter_json_files(self.todo_dir):
            todo = TodoItem.from_dict(self._read_json(path))
            if not include_deleted and todo.deleted:
                continue
            if include_completed or not todo.completed:
                todos.append(todo)
        return sorted(
            todos,
            key=lambda todo: (
                todo.completed,
                todo.due_date is None,
                todo.due_date or date.max,
                todo.created_at,
                todo.id,
            ),
        )

    def delete_todo(self, todo_id: str, *, occurred_at: datetime | None = None) -> None:
        todo = self.get_todo(todo_id, include_deleted=True)
        if todo.mark_deleted(occurred_at=occurred_at):
            self.save_todo(todo, touch=False)

    def list_timeline_events(self) -> list[TimelineEvent]:
        events: list[TimelineEvent] = []
        for entry in self.list_journal_entries():
            events.append(
                TimelineEvent(
                    id=f"journal:{entry.id}",
                    occurred_at=entry.created_at,
                    event_type="journal_entry",
                    source_kind="journal",
                    source_id=entry.id,
                    title=entry.title,
                    summary=entry.excerpt(),
                    metadata={"slug": entry.slug, "tags": list(entry.tags)},
                )
            )

        for todo in self.list_todos(include_completed=True, include_deleted=True):
            for index, history_event in enumerate(todo.history):
                title, summary = history_event.timeline_label(todo)
                events.append(
                    TimelineEvent(
                        id=f"todo:{todo.id}:{index}",
                        occurred_at=history_event.timestamp,
                        event_type="todo_activity",
                        source_kind="todo",
                        source_id=todo.id,
                        title=title,
                        summary=summary,
                        metadata={
                            "todo_title": todo.title,
                            "todo_completed": todo.completed,
                            "todo_deleted": todo.deleted,
                            "action": history_event.action,
                            "field": history_event.changed_field,
                        },
                    )
                )

        return sorted(events, key=lambda event: (event.occurred_at, event.id), reverse=True)

    def timeline_events_grouped_by_date(self) -> list[TimelineDay]:
        grouped: dict[date, list[TimelineEvent]] = defaultdict(list)
        for event in self.list_timeline_events():
            grouped[event.occurred_at.date()].append(event)
        return [TimelineDay(label=day, events=grouped[day]) for day in sorted(grouped.keys(), reverse=True)]

    def _journal_file_stem(self, entry: JournalEntry) -> str:
        return f"{entry.created_at.date().isoformat()}_{entry.slug}"

    def _journal_paths(self, stem: str) -> tuple[Path, Path]:
        return self.journal_dir / f"{stem}.md", self.journal_dir / f"{stem}.json"

    def _todo_path(self, todo_id: str) -> Path:
        return self.todo_dir / f"{todo_id}.json"

    def _iter_json_files(self, directory: Path) -> Iterable[Path]:
        return sorted(path for path in directory.glob("*.json") if path.is_file())

    def _read_text(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            raise StorageError(f"Unable to read text file: {path}") from exc

    def _read_json(self, path: Path) -> dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise StorageError(f"Invalid JSON in {path}") from exc
        except OSError as exc:
            raise StorageError(f"Unable to read JSON file: {path}") from exc

    def _write_text(self, path: Path, content: str) -> None:
        self._atomic_write(path, content)

    def _write_json(self, path: Path, payload: Mapping[str, Any]) -> None:
        serialized = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
        self._atomic_write(path, serialized + "\n")

    def _atomic_write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            temporary_path.write_text(content, encoding="utf-8")
            temporary_path.replace(path)
        except OSError as exc:
            self._remove_if_exists(temporary_path)
            raise StorageError(f"Unable to write file: {path}") from exc

    def _remove_if_exists(self, path: Path) -> None:
        try:
            if path.exists():
                path.unlink()
        except OSError as exc:
            raise StorageError(f"Unable to remove file: {path}") from exc
