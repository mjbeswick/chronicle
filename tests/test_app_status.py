from __future__ import annotations

import unittest

from app.app import _notes_status_hints, _todos_status_hints


class StatusHintTests(unittest.TestCase):
    def test_notes_hide_selection_actions_without_selection(self) -> None:
        self.assertEqual(
            _notes_status_hints(False),
            [
                ("^j/^t/^c", "tabs"),
                ("n", "new note"),
                ("f", "filter"),
                ("?", "help"),
                ("q", "quit"),
            ],
        )

    def test_notes_show_selection_actions_with_selection(self) -> None:
        self.assertEqual(
            _notes_status_hints(True),
            [
                ("^j/^t/^c", "tabs"),
                ("n", "new note"),
                ("e", "edit"),
                ("d", "delete"),
                ("#", "tags"),
                ("f", "filter"),
                ("?", "help"),
                ("q", "quit"),
            ],
        )

    def test_todos_hide_selection_actions_without_selection(self) -> None:
        self.assertEqual(
            _todos_status_hints(False),
            [
                ("^j/^n/^c", "tabs"),
                ("n", "new todo"),
                ("?", "help"),
                ("q", "quit"),
            ],
        )

    def test_todos_show_selection_actions_with_selection(self) -> None:
        self.assertEqual(
            _todos_status_hints(True),
            [
                ("^j/^n/^c", "tabs"),
                ("n", "new todo"),
                ("N", "subtask"),
                ("v", "view"),
                ("e", "edit"),
                ("d", "delete"),
                ("x", "toggle"),
                ("?", "help"),
                ("q", "quit"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
