from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Container
from textual.message import Message
from textual.widgets import DataTable

from app.models import TodoItem


class TodosView(Container):
    class SelectionChanged(Message):
        def __init__(self, todo: TodoItem | None) -> None:
            self.todo = todo
            super().__init__()

    def __init__(self, *children, **kwargs) -> None:
        super().__init__(*children, **kwargs)
        self._todos: list[TodoItem] = []

    def compose(self) -> ComposeResult:
        table = DataTable(id="todo-table")
        table.cursor_type = "row"
        table.zebra_stripes = True
        table.add_columns("Done", "Todo", "Due")
        yield table

    def refresh_view(self, todos: list[TodoItem]) -> None:
        self._todos = todos
        table = self.query_one(DataTable)
        table.clear()
        for todo in todos:
            table.add_row(
                "☑" if todo.completed else "☐",
                todo.title,
                todo.due_date.isoformat() if todo.due_date else "—",
            )
        if todos:
            table.move_cursor(row=0, column=0)
            table.focus()
            self.post_message(self.SelectionChanged(todos[0]))

    def selected_todo(self) -> TodoItem | None:
        table = self.query_one(DataTable)
        row_index = table.cursor_row
        if row_index is None or row_index < 0 or row_index >= len(self._todos):
            return None
        return self._todos[row_index]

    def focus_content(self) -> None:
        self.query_one(DataTable).focus()

    @on(DataTable.RowHighlighted)
    def _on_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        row = event.cursor_row
        todo = self._todos[row] if 0 <= row < len(self._todos) else None
        self.post_message(self.SelectionChanged(todo))
