"""Journal entry model for Chronicle."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _dump_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


@dataclass
class JournalEntry:
    """A markdown journal entry plus lightweight JSON metadata."""

    id: str
    title: str
    content: str = ""
    slug: str = "entry"
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)
    tags: list[str] = field(default_factory=list)
    metadata_version: int = 1
    file_stem: str | None = None

    def __post_init__(self) -> None:
        self.title = self.title.strip() or "Untitled Entry"
        self.content = self.content or ""
        self.slug = self.slug.strip() or "entry"
        self.created_at = _parse_datetime(self.created_at)
        self.updated_at = _parse_datetime(self.updated_at)
        self.tags = [tag.strip() for tag in self.tags if tag and tag.strip()]

    @property
    def date_key(self) -> str:
        return self.created_at.date().isoformat()

    def excerpt(self, limit: int = 120) -> str:
        """Return a compact single-line summary of the markdown body."""
        compact = " ".join(line.strip() for line in self.content.splitlines() if line.strip())
        if len(compact) <= limit:
            return compact
        return compact[: max(limit - 1, 0)].rstrip() + "…"

    def to_metadata_dict(self) -> dict[str, Any]:
        """Serialize JSON metadata stored alongside the markdown body."""
        return {
            "id": self.id,
            "title": self.title,
            "slug": self.slug,
            "created_at": _dump_datetime(self.created_at),
            "updated_at": _dump_datetime(self.updated_at),
            "tags": list(self.tags),
            "metadata_version": self.metadata_version,
            "file_stem": self.file_stem,
        }

    @classmethod
    def from_storage(cls, metadata: Mapping[str, Any], content: str) -> "JournalEntry":
        """Hydrate an entry from a metadata JSON object and markdown content."""
        return cls(
            id=str(metadata["id"]),
            title=str(metadata.get("title") or "Untitled Entry"),
            content=content,
            slug=str(metadata.get("slug") or "entry"),
            created_at=_parse_datetime(metadata["created_at"]),
            updated_at=_parse_datetime(metadata.get("updated_at", metadata["created_at"])),
            tags=list(metadata.get("tags", [])),
            metadata_version=int(metadata.get("metadata_version", 1)),
            file_stem=metadata.get("file_stem"),
        )
