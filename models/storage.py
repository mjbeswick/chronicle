"""File-based Item storage for Chronicle.

One JSON file per item in `items/`. Atomic writes. No body-markdown split —
body is inline in JSON for the prototype (simple, easy to inspect).
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping
from uuid import uuid4

from .item import Item, generate_id, utc_now


class StorageError(RuntimeError):
    pass


UNSET = object()


class ItemStore:
    """Persistent store for Items."""

    def __init__(self, project_root: str | Path = ".", data_root: str | Path | None = None) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.data_root = self._resolve_data_root(data_root)
        self.items_dir = self.data_root / "items"
        self.ensure_directories()

    def _resolve_data_root(self, data_root: str | Path | None) -> Path:
        if data_root is None:
            return (self.project_root / "data").resolve()
        candidate = Path(data_root).expanduser()
        return candidate.resolve() if candidate.is_absolute() else (self.project_root / candidate).resolve()

    def ensure_directories(self) -> None:
        self.items_dir.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- CRUD

    def create(
        self,
        title: str,
        *,
        body: str = "",
        tags: Iterable[str] | None = None,
        parent_id: str | None = None,
        at: datetime | None = None,
        due: date | None = None,
        done_at: datetime | None = None,
        created_at: datetime | None = None,
    ) -> Item:
        now = created_at or utc_now()
        item = Item(
            id=generate_id(),
            title=title,
            body=body,
            tags=[t.strip() for t in (tags or []) if t.strip()],
            parent_id=parent_id,
            created_at=now,
            updated_at=now,
            at=at,
            due=due,
            done_at=done_at,
        )
        self._save(item, touch=False)
        return item

    def get(self, item_id: str) -> Item:
        path = self._path(item_id)
        if not path.exists():
            raise StorageError(f"Item not found: {item_id}")
        return Item.from_dict(self._read_json(path))

    def list(self) -> list[Item]:
        items: list[Item] = []
        for path in self._iter_json(self.items_dir):
            items.append(Item.from_dict(self._read_json(path)))
        return sorted(items, key=lambda i: (i.created_at, i.id), reverse=True)

    def update(
        self,
        item_id: str,
        *,
        title: object = UNSET,
        body: object = UNSET,
        tags: object = UNSET,
        parent_id: object = UNSET,
        at: object = UNSET,
        due: object = UNSET,
        done_at: object = UNSET,
    ) -> Item:
        item = self.get(item_id)
        if title is not UNSET:
            item.title = title  # type: ignore[assignment]
        if body is not UNSET:
            item.body = body  # type: ignore[assignment]
        if tags is not UNSET:
            item.tags = [t.strip() for t in (tags or []) if t.strip()]  # type: ignore[union-attr]
        if parent_id is not UNSET:
            item.parent_id = parent_id  # type: ignore[assignment]
        if at is not UNSET:
            item.at = at  # type: ignore[assignment]
        if due is not UNSET:
            item.due = due  # type: ignore[assignment]
        if done_at is not UNSET:
            item.done_at = done_at  # type: ignore[assignment]
        self._save(item, touch=True)
        return item

    def delete(self, item_id: str) -> None:
        path = self._path(item_id)
        self._remove_if_exists(path)
        # Cascade-delete descendants.
        for descendant in self._descendants(item_id):
            self._remove_if_exists(self._path(descendant.id))

    def toggle_done(self, item_id: str, *, when: datetime | None = None) -> Item:
        item = self.get(item_id)
        if item.done_at is None:
            done = when or utc_now()
            item.done_at = done
            # Cascade: completing a parent completes open descendants.
            for descendant in self._descendants(item_id):
                if descendant.done_at is None:
                    descendant.done_at = done
                    self._save(descendant)
        else:
            item.done_at = None
        self._save(item)
        return item

    # ---------------------------------------------------------------- helpers

    def _descendants(self, item_id: str) -> list[Item]:
        all_items = self.list()
        result: list[Item] = []
        queue = [item_id]
        while queue:
            current = queue.pop(0)
            children = [i for i in all_items if i.parent_id == current]
            result.extend(children)
            queue.extend(c.id for c in children)
        return result

    def _save(self, item: Item, *, touch: bool = True) -> None:
        if touch:
            item.updated_at = utc_now()
        self._write_json(self._path(item.id), item.to_dict())

    def _path(self, item_id: str) -> Path:
        return self.items_dir / f"{item_id}.json"

    def _iter_json(self, directory: Path) -> Iterable[Path]:
        return sorted(p for p in directory.glob("*.json") if p.is_file())

    def _read_json(self, path: Path) -> dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise StorageError(f"Invalid JSON in {path}") from exc
        except OSError as exc:
            raise StorageError(f"Unable to read JSON file: {path}") from exc

    def _write_json(self, path: Path, payload: Mapping[str, Any]) -> None:
        serialized = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
        self._atomic_write(path, serialized + "\n")

    def _atomic_write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            tmp.write_text(content, encoding="utf-8")
            tmp.replace(path)
        except OSError as exc:
            self._remove_if_exists(tmp)
            raise StorageError(f"Unable to write file: {path}") from exc

    def _remove_if_exists(self, path: Path) -> None:
        try:
            if path.exists():
                path.unlink()
        except OSError as exc:
            raise StorageError(f"Unable to remove file: {path}") from exc
