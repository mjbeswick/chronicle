"""Todo model and history primitives for Chronicle."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Mapping


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def dump_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def parse_date(value: str | date | None) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(value)


def dump_date(value: date | None) -> str | None:
    return value.isoformat() if value else None


def slugify_todo(value: str) -> str:
    sanitized = "".join(char.lower() if char.isalnum() else "-" for char in value)
    while "--" in sanitized:
        sanitized = sanitized.replace("--", "-")
    return sanitized.strip("-") or "todo"


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return dump_datetime(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return value


@dataclass
class TodoHistoryEvent:
    """A single change in a todo's lifecycle."""

    action: str
    timestamp: datetime = field(default_factory=utc_now)
    changed_field: str | None = None
    before: Any = None
    after: Any = None
    summary: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.timestamp = parse_datetime(self.timestamp)
        self.metadata = dict(self.metadata)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "timestamp": dump_datetime(self.timestamp),
            "changed_field": self.changed_field,
            "before": _json_safe(self.before),
            "after": _json_safe(self.after),
            "summary": self.summary,
            "metadata": _json_safe(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TodoHistoryEvent":
        return cls(
            action=str(payload["action"]),
            timestamp=parse_datetime(payload["timestamp"]),
            changed_field=payload.get("changed_field", payload.get("field")),
            before=payload.get("before"),
            after=payload.get("after"),
            summary=payload.get("summary"),
            metadata=dict(payload.get("metadata", {})),
        )

    def timeline_label(self, todo: "TodoItem") -> tuple[str, str]:
        action = self.action
        if action == "created":
            return "TODO created", todo.title
        if action == "completed":
            return "TODO completed", todo.title
        if action == "reopened":
            return "TODO reopened", todo.title
        if action == "deleted":
            return "TODO deleted", todo.title
        if action == "due_date_changed":
            previous = self.before or "none"
            current = self.after or "none"
            return "TODO due date changed", f"{todo.title} ({previous} → {current})"
        if action == "title_changed":
            return "TODO renamed", f"{self.before or 'Untitled'} → {self.after or todo.title}"
        if action == "description_changed":
            return "TODO details updated", todo.title
        return self.summary or "TODO updated", todo.title


UNSET = object()


@dataclass
class TodoItem:
    """A persisted todo item with append-only change history."""

    id: str
    title: str
    slug: str = "todo"
    description: str = ""
    due_date: date | None = None
    completed: bool = False
    deleted: bool = False
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    completed_at: datetime | None = None
    deleted_at: datetime | None = None
    history: list[TodoHistoryEvent] = field(default_factory=list)
    data_version: int = 1

    def __post_init__(self) -> None:
        self.title = self.title.strip() or "Untitled Todo"
        self.slug = self.slug.strip() or slugify_todo(self.title)
        self.description = self.description or ""
        self.due_date = parse_date(self.due_date)
        self.created_at = parse_datetime(self.created_at)
        self.updated_at = parse_datetime(self.updated_at)
        self.completed_at = parse_datetime(self.completed_at) if self.completed_at else None
        self.deleted_at = parse_datetime(self.deleted_at) if self.deleted_at else None
        self.history = [
            event if isinstance(event, TodoHistoryEvent) else TodoHistoryEvent.from_dict(event)
            for event in self.history
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "slug": self.slug,
            "description": self.description,
            "due_date": dump_date(self.due_date),
            "completed": self.completed,
            "deleted": self.deleted,
            "created_at": dump_datetime(self.created_at),
            "updated_at": dump_datetime(self.updated_at),
            "completed_at": dump_datetime(self.completed_at) if self.completed_at else None,
            "deleted_at": dump_datetime(self.deleted_at) if self.deleted_at else None,
            "history": [event.to_dict() for event in self.history],
            "data_version": self.data_version,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TodoItem":
        return cls(
            id=str(payload["id"]),
            title=str(payload.get("title") or "Untitled Todo"),
            slug=str(payload.get("slug") or slugify_todo(str(payload.get("title") or "todo"))),
            description=str(payload.get("description") or ""),
            due_date=parse_date(payload.get("due_date")),
            completed=bool(payload.get("completed", False)),
            deleted=bool(payload.get("deleted", False)),
            created_at=parse_datetime(payload["created_at"]),
            updated_at=parse_datetime(payload.get("updated_at", payload["created_at"])),
            completed_at=parse_datetime(payload["completed_at"]) if payload.get("completed_at") else None,
            deleted_at=parse_datetime(payload["deleted_at"]) if payload.get("deleted_at") else None,
            history=[TodoHistoryEvent.from_dict(event) for event in payload.get("history", [])],
            data_version=int(payload.get("data_version", 1)),
        )

    def record_event(
        self,
        action: str,
        *,
        field: str | None = None,
        before: Any = None,
        after: Any = None,
        summary: str | None = None,
        occurred_at: datetime | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> TodoHistoryEvent:
        event = TodoHistoryEvent(
            action=action,
            timestamp=occurred_at or utc_now(),
            changed_field=field,
            before=before,
            after=after,
            summary=summary,
            metadata=dict(metadata or {}),
        )
        self.history.append(event)
        self.updated_at = event.timestamp
        return event

    def apply_updates(
        self,
        *,
        title: str | None = None,
        description: str | None = None,
        due_date: date | str | None | object = UNSET,
        occurred_at: datetime | None = None,
    ) -> bool:
        changed = False
        when = occurred_at or utc_now()

        if title is not None:
            normalized_title = title.strip() or "Untitled Todo"
            if normalized_title != self.title:
                previous = self.title
                self.title = normalized_title
                self.slug = slugify_todo(normalized_title)
                self.record_event("title_changed", field="title", before=previous, after=normalized_title, occurred_at=when)
                changed = True

        if description is not None and description != self.description:
            previous = self.description
            self.description = description
            self.record_event(
                "description_changed",
                field="description",
                before=previous,
                after=description,
                occurred_at=when,
            )
            changed = True

        if due_date is not UNSET:
            normalized_due_date = parse_date(due_date if due_date is not UNSET else None)
            if normalized_due_date != self.due_date:
                previous = dump_date(self.due_date)
                self.due_date = normalized_due_date
                self.record_event(
                    "due_date_changed",
                    field="due_date",
                    before=previous,
                    after=dump_date(normalized_due_date),
                    occurred_at=when,
                )
                changed = True

        return changed

    def set_completed(self, completed: bool, *, occurred_at: datetime | None = None) -> bool:
        if completed == self.completed:
            return False
        when = occurred_at or utc_now()
        self.completed = completed
        self.completed_at = when if completed else None
        self.record_event("completed" if completed else "reopened", field="completed", after=completed, occurred_at=when)
        return True

    def mark_deleted(self, *, occurred_at: datetime | None = None) -> bool:
        if self.deleted:
            return False
        when = occurred_at or utc_now()
        self.deleted = True
        self.deleted_at = when
        self.record_event("deleted", field="deleted", after=True, occurred_at=when)
        return True
