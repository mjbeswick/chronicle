"""Thin storage adapter around ItemStore.

Exposes a stable interface (`list_items`, `create_item`, `update_item`,
`delete_item`, `toggle_done`, `update_tags`) so views stay decoupled from
the on-disk format.
"""

from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Protocol

from app.models import Item
from models.storage import ItemStore, UNSET
from platformdirs import user_data_dir


def default_project_root() -> Path:
    configured = os.environ.get("CHRONICLE_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(user_data_dir("chronicle", "mjbeswick")).resolve()


class StorageBackend(Protocol):
    def list_items(self) -> list[Item]: ...

    def create_item(
        self,
        title: str,
        *,
        body: str = "",
        tags: Iterable[str] | None = None,
        parent_id: str | None = None,
        at: datetime | None = None,
        due: date | None = None,
    ) -> Item: ...

    def update_item(
        self,
        item_id: str,
        *,
        title: object = UNSET,
        body: object = UNSET,
        tags: object = UNSET,
        at: object = UNSET,
        due: object = UNSET,
    ) -> Item: ...

    def delete_item(self, item_id: str) -> None: ...

    def toggle_done(self, item_id: str) -> Item: ...

    def update_tags(self, item_id: str, tags: list[str]) -> Item: ...


class ChronicleStorageAdapter(StorageBackend):
    def __init__(self, project_root: str | Path | None = None) -> None:
        root = Path(project_root).expanduser().resolve() if project_root is not None else default_project_root()
        self.backend = ItemStore(project_root=root)

    def list_items(self) -> list[Item]:
        return self.backend.list()

    def create_item(
        self,
        title: str,
        *,
        body: str = "",
        tags: Iterable[str] | None = None,
        parent_id: str | None = None,
        at: datetime | None = None,
        due: date | None = None,
    ) -> Item:
        return self.backend.create(
            title=title,
            body=body,
            tags=tags,
            parent_id=parent_id,
            at=at,
            due=due,
        )

    def update_item(
        self,
        item_id: str,
        *,
        title: object = UNSET,
        body: object = UNSET,
        tags: object = UNSET,
        at: object = UNSET,
        due: object = UNSET,
    ) -> Item:
        return self.backend.update(
            item_id,
            title=title,
            body=body,
            tags=tags,
            at=at,
            due=due,
        )

    def delete_item(self, item_id: str) -> None:
        self.backend.delete(item_id)

    def toggle_done(self, item_id: str) -> Item:
        return self.backend.toggle_done(item_id)

    def update_tags(self, item_id: str, tags: list[str]) -> Item:
        return self.backend.update(item_id, tags=tags)
