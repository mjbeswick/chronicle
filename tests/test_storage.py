from __future__ import annotations

import shutil
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from models import Item, ItemStore, StorageError


class ItemStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = Path(tempfile.mkdtemp(prefix="chronicle-items-"))
        self.store = ItemStore(project_root=self.workspace)

    def tearDown(self) -> None:
        shutil.rmtree(self.workspace)

    def test_create_persists_fields(self) -> None:
        item = self.store.create(
            "Buy milk",
            body="From the corner shop",
            tags=["errand", "food"],
            due=date(2026, 5, 1),
        )
        self.assertTrue(item.id.startswith("item_"))
        self.assertEqual("Buy milk", item.title)
        self.assertEqual(date(2026, 5, 1), item.due)

        loaded = self.store.get(item.id)
        self.assertEqual("Buy milk", loaded.title)
        self.assertEqual(["errand", "food"], loaded.tags)
        self.assertEqual(date(2026, 5, 1), loaded.due)

    def test_list_sorts_newest_first(self) -> None:
        a = self.store.create("first")
        b = self.store.create("second")
        ids = [i.id for i in self.store.list()]
        self.assertEqual(ids[0], b.id)
        self.assertEqual(ids[1], a.id)

    def test_update_changes_only_provided_fields(self) -> None:
        item = self.store.create("original", body="body1", tags=["a"])
        self.store.update(item.id, title="renamed")
        reloaded = self.store.get(item.id)
        self.assertEqual("renamed", reloaded.title)
        self.assertEqual("body1", reloaded.body)
        self.assertEqual(["a"], reloaded.tags)

    def test_delete_removes_file_and_descendants(self) -> None:
        parent = self.store.create("parent")
        child = self.store.create("child", parent_id=parent.id)
        grand = self.store.create("grandchild", parent_id=child.id)
        self.store.delete(parent.id)
        self.assertEqual([], self.store.list())
        for i in (parent, child, grand):
            with self.assertRaises(StorageError):
                self.store.get(i.id)

    def test_toggle_done_marks_and_unmarks(self) -> None:
        item = self.store.create("thing", due=date(2026, 5, 1))
        self.assertIsNone(item.done_at)

        after_done = self.store.toggle_done(item.id)
        self.assertIsNotNone(after_done.done_at)

        after_reopen = self.store.toggle_done(item.id)
        self.assertIsNone(after_reopen.done_at)

    def test_toggle_done_cascades_to_descendants(self) -> None:
        parent = self.store.create("parent", due=date(2026, 5, 1))
        child = self.store.create("child", parent_id=parent.id)
        self.store.toggle_done(parent.id)
        self.assertIsNotNone(self.store.get(child.id).done_at)


class ItemLensTests(unittest.TestCase):
    """Lens-membership predicates — pure functions on Item."""

    def _now(self) -> datetime:
        return datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc)

    def _item(self, **overrides) -> Item:
        from models.item import generate_id
        base = dict(id=generate_id(), title="x")
        base.update(overrides)
        return Item(**base)

    def test_past_anchored_item_is_in_journal(self) -> None:
        now = self._now()
        item = self._item(at=now - timedelta(days=1))
        self.assertTrue(item.in_journal(now))
        self.assertFalse(item.in_todos(now))
        self.assertFalse(item.in_notes())

    def test_future_anchored_item_is_in_todos_and_calendar(self) -> None:
        now = self._now()
        item = self._item(at=now + timedelta(days=1))
        self.assertFalse(item.in_journal(now))
        self.assertTrue(item.in_todos())
        self.assertTrue(item.in_calendar())

    def test_item_with_due_is_in_todos_and_calendar(self) -> None:
        now = self._now()
        item = self._item(due=date(2026, 5, 1))
        self.assertTrue(item.in_todos())
        self.assertTrue(item.in_calendar())
        self.assertFalse(item.in_journal(now))

    def test_done_item_leaves_todos_and_joins_journal(self) -> None:
        now = self._now()
        item = self._item(due=date(2026, 5, 1), done_at=now)
        self.assertFalse(item.in_todos())
        self.assertTrue(item.in_journal(now))

    def test_untimed_body_item_is_a_note(self) -> None:
        item = self._item(body="reference content")
        self.assertTrue(item.in_notes())
        self.assertFalse(item.in_calendar())

    def test_hollow_item_is_a_todo(self) -> None:
        now = self._now()
        item = self._item()  # no body, no dates
        self.assertFalse(item.in_journal(now))
        self.assertTrue(item.in_todos(now))
        self.assertFalse(item.in_calendar())
        self.assertFalse(item.in_notes())


class ItemSerializationTests(unittest.TestCase):
    def test_roundtrip_preserves_fields(self) -> None:
        original = Item(
            id="item_deadbeefcafe",
            title="hello",
            body="body text",
            tags=["a", "b"],
            parent_id="item_parent",
            created_at=datetime(2026, 4, 24, 10, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 4, 24, 11, 0, tzinfo=timezone.utc),
            at=datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc),
            due=date(2026, 5, 2),
            done_at=datetime(2026, 5, 3, 15, 0, tzinfo=timezone.utc),
        )
        round_tripped = Item.from_dict(original.to_dict())
        self.assertEqual(original, round_tripped)


if __name__ == "__main__":
    unittest.main()
