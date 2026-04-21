"""Storage layer tests for Chronicle."""

from __future__ import annotations

import json
import shutil
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from models.storage import FileStorage, StorageError, slugify


class FileStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = Path("tests/.workspace") / self._testMethodName
        if self.workspace.exists():
            shutil.rmtree(self.workspace)
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.storage = FileStorage(project_root=self.workspace)

    def tearDown(self) -> None:
        if self.workspace.exists():
            shutil.rmtree(self.workspace)
        workspace_root = Path("tests/.workspace")
        if workspace_root.exists() and not any(workspace_root.iterdir()):
            workspace_root.rmdir()

    def test_journal_entry_round_trip_and_rename(self) -> None:
        created_at = datetime(2026, 4, 21, 8, 30, tzinfo=timezone.utc)
        entry = self.storage.create_entry(
            "Morning Reflection!",
            "# Hello\n\nToday feels focused.",
            tags=[" personal ", "focus"],
            created_at=created_at,
        )

        original_markdown = self.workspace / "data" / "journal" / "2026-04-21_morning-reflection.md"
        original_metadata = original_markdown.with_suffix(".json")
        self.assertTrue(original_markdown.exists())
        self.assertTrue(original_metadata.exists())

        loaded = self.storage.get_journal_entry(entry.id)
        self.assertEqual("Morning Reflection!", loaded.title)
        self.assertEqual(["personal", "focus"], loaded.tags)
        self.assertIn("Today feels focused.", loaded.excerpt())

        updated = self.storage.update_entry(
            entry.id,
            title="Evening Notes",
            content="A quieter close to the day.",
            tags=["evening"],
        )

        renamed_markdown = self.workspace / "data" / "journal" / "2026-04-21_evening-notes.md"
        self.assertEqual("2026-04-21_evening-notes", updated.file_stem)
        self.assertFalse(original_markdown.exists())
        self.assertFalse(original_metadata.exists())
        self.assertTrue(renamed_markdown.exists())
        self.assertEqual("A quieter close to the day.", self.storage.get_journal_entry(entry.id).content)

        self.storage.delete_entry(entry.id)
        self.assertFalse(renamed_markdown.exists())
        self.assertFalse(renamed_markdown.with_suffix(".json").exists())

    def test_todo_history_round_trip_and_toggle(self) -> None:
        created_at = datetime(2026, 4, 21, 9, 0, tzinfo=timezone.utc)
        todo = self.storage.create_todo(
            title="Finish report",
            description="Wrap up the MVP summary.",
            due_date=date(2026, 4, 22),
            created_at=created_at,
        )

        stored = self.storage.get_todo(todo.id)
        self.assertEqual(["created"], [event.action for event in stored.history])
        self.assertEqual(date(2026, 4, 22), stored.due_date)

        updated = self.storage.update_todo(
            todo.id,
            title="Finish project report",
            due_date="2026-04-23",
            description="Wrap up the MVP summary and handoff.",
            occurred_at=datetime(2026, 4, 21, 9, 30, tzinfo=timezone.utc),
        )
        self.assertEqual("finish-project-report", updated.slug)
        self.assertEqual("2026-04-23", updated.due_date.isoformat() if updated.due_date else None)

        completed = self.storage.toggle_todo_completion(
            todo.id,
            True,
            occurred_at=datetime(2026, 4, 21, 10, 0, tzinfo=timezone.utc),
        )
        self.assertTrue(completed.completed)
        reopened = self.storage.toggle_todo_completion(
            todo.id,
            False,
            occurred_at=datetime(2026, 4, 21, 10, 15, tzinfo=timezone.utc),
        )
        self.assertFalse(reopened.completed)

        history_actions = [event.action for event in self.storage.get_todo(todo.id).history]
        self.assertEqual(
            ["created", "title_changed", "description_changed", "due_date_changed", "completed", "reopened"],
            history_actions,
        )

    def test_delete_todo_soft_deletes_but_keeps_history(self) -> None:
        todo = self.storage.create_todo(
            "Archive draft",
            due_date=date(2026, 4, 22),
            created_at=datetime(2026, 4, 21, 11, 0, tzinfo=timezone.utc),
        )

        self.storage.delete_todo(todo.id, occurred_at=datetime(2026, 4, 21, 11, 30, tzinfo=timezone.utc))

        self.assertEqual([], self.storage.list_todos())
        deleted = self.storage.get_todo(todo.id)
        self.assertTrue(deleted.deleted)
        self.assertEqual("deleted", deleted.history[-1].action)

        payload = json.loads((self.workspace / "data" / "todos" / f"{todo.id}.json").read_text(encoding="utf-8"))
        self.assertTrue(payload["deleted"])
        self.assertEqual("deleted", payload["history"][-1]["action"])

        with self.assertRaises(StorageError):
            self.storage.get_todo(todo.id, include_deleted=False)

    def test_timeline_mixes_journal_entries_and_todo_activity(self) -> None:
        self.storage.create_todo(
            "Morning walk",
            created_at=datetime(2026, 4, 21, 8, 0, tzinfo=timezone.utc),
        )
        todo = self.storage.list_todos()[0]
        self.storage.toggle_todo_completion(
            todo.id,
            True,
            occurred_at=datetime(2026, 4, 21, 10, 30, tzinfo=timezone.utc),
        )
        self.storage.create_entry(
            "Afternoon Notes",
            "Checked in after lunch.",
            created_at=datetime(2026, 4, 21, 14, 45, tzinfo=timezone.utc),
        )

        events = self.storage.list_timeline_events()
        self.assertEqual(
            ["journal_entry", "todo_activity", "todo_activity"],
            [event.event_type for event in events],
        )
        self.assertEqual("Afternoon Notes", events[0].title)
        self.assertEqual("TODO completed", events[1].title)
        self.assertEqual("2026-04-21", events[0].date_key)
        grouped = self.storage.timeline_events_grouped_by_date()
        self.assertEqual(1, len(grouped))
        self.assertEqual(date(2026, 4, 21), grouped[0].label)
        self.assertEqual(3, len(grouped[0].events))

    def test_slugify_provides_safe_defaults(self) -> None:
        self.assertEqual("hello-world", slugify(" Hello, World! "))
        self.assertEqual("item", slugify("!!!"))


if __name__ == "__main__":
    unittest.main()
