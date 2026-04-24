from __future__ import annotations

from datetime import date

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.message import Message
from textual.widgets import Static, Tree
from textual.widgets.tree import TreeNode

from app.filter import FilterSpec, matches_date, matches_tag, matches_text
from app.models import Item
from app.utils import format_due_date
from app.voice import ViewVoiceHoldHandler


_FILTERS: list[tuple[str, str]] = [
    ("open", "Open"),
    ("overdue", "Overdue"),
    ("today", "Today"),
    ("all", "All"),
    ("done", "Done"),
]


def _todo_label(item: Item) -> Text:
    status = Text("☑ ", style="dim") if item.is_done else Text("☐ ")
    title = Text(item.title, style="dim" if item.is_done else "")
    label = status + title
    if item.due:
        due = format_due_date(item.due, completed=item.is_done)
        label += Text("  ") + due
    return label


def _add_children(
    parent_node: TreeNode,
    parent_id: str,
    children_by_parent: dict[str, list[Item]],
    first_node: list,
) -> None:
    for child in children_by_parent.get(parent_id, []):
        if children_by_parent.get(child.id):
            branch = parent_node.add(_todo_label(child), data=child, expand=True)
            if not first_node:
                first_node.append(branch)
            _add_children(branch, child.id, children_by_parent, first_node)
        else:
            leaf = parent_node.add_leaf(_todo_label(child), data=child)
            if not first_node:
                first_node.append(leaf)


class TodoSidebar(Vertical):
    """Sidebar tree with Due filters and Tags groups."""

    DEFAULT_CSS = """
    TodoSidebar {
        width: 24;
        border-right: tall $primary-darken-3;
        padding: 0;
        overflow-y: auto;
        overflow-x: hidden;
    }
    TodoSidebar #todo-sidebar-tree {
        height: 1fr;
        padding: 0;
    }
    """

    class Changed(Message):
        def __init__(self, filter_id: str, tag: str | None) -> None:
            self.filter_id = filter_id
            self.tag = tag
            super().__init__()

    def __init__(self, active_filter: str = "open", **kwargs) -> None:
        super().__init__(**kwargs)
        self._active_filter = active_filter
        self._active_tag: str | None = None
        self._tags: list[str] = []
        self._filter_nodes: dict[str, TreeNode] = {}
        self._tag_nodes: dict[str, TreeNode] = {}
        self._tags_root: TreeNode | None = None

    def compose(self) -> ComposeResult:
        tree: Tree = Tree("", id="todo-sidebar-tree")
        tree.show_root = False
        tree.show_guides = False
        yield tree

    def on_mount(self) -> None:
        tree = self.query_one("#todo-sidebar-tree", Tree)
        due = tree.root.add("Due", data=None, expand=True)
        for filter_id, label in _FILTERS:
            node = due.add_leaf(self._filter_label(filter_id, label), data=("filter", filter_id))
            self._filter_nodes[filter_id] = node
        self._tags_root = tree.root.add("Tags", data=None, expand=True)
        self._tags_root.add_leaf(Text("(no tags)", style="dim"), data=None)
        active = self._filter_nodes.get(self._active_filter)
        if active is not None:
            tree.select_node(active)

    def _filter_label(self, filter_id: str, label: str) -> Text:
        style = "bold" if filter_id == self._active_filter else ""
        return Text(label, style=style)

    def _tag_label(self, tag: str) -> Text:
        style = "bold" if tag == self._active_tag else ""
        return Text(f"# {tag}", style=style)

    def update_tags(self, tags: list[str]) -> None:
        tags_sorted = sorted(tags)
        if tags_sorted == self._tags:
            return
        self._tags = tags_sorted
        node = self._tags_root
        if node is None:
            return
        node.remove_children()
        self._tag_nodes.clear()
        if not tags_sorted:
            node.add_leaf(Text("(no tags)", style="dim"), data=None)
            return
        for tag in tags_sorted:
            leaf = node.add_leaf(self._tag_label(tag), data=("tag", tag))
            self._tag_nodes[tag] = leaf

    def set_filter(self, filter_id: str) -> None:
        self._active_filter = filter_id
        for fid, label in _FILTERS:
            node = self._filter_nodes.get(fid)
            if node is not None:
                node.set_label(self._filter_label(fid, label))

    def set_tag(self, tag: str | None) -> None:
        self._active_tag = tag
        for t, node in self._tag_nodes.items():
            node.set_label(self._tag_label(t))

    @on(Tree.NodeHighlighted, "#todo-sidebar-tree")
    def _on_sidebar_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        event.stop()
        data = event.node.data
        if not isinstance(data, tuple):
            return
        kind, value = data
        if kind == "filter":
            if value == self._active_filter and self._active_tag is None:
                return
            self.set_filter(value)
            self.set_tag(None)
            self.post_message(self.Changed(value, None))
        elif kind == "tag":
            if value == self._active_tag:
                return
            self.set_tag(value)
            self.post_message(self.Changed(self._active_filter, value))


class TodosView(Container):
    BINDINGS = [Binding("x", "toggle_selected", show=False, priority=True)]

    DEFAULT_CSS = """
    TodosView {
        layout: horizontal;
    }
    TodosView #todos-main {
        width: 1fr;
        layout: vertical;
    }
    TodosView #todos-filter-banner {
        height: auto;
        padding: 0 1;
        color: $text;
        background: $warning-darken-2;
        display: none;
    }
    TodosView #todos-empty {
        content-align: center middle;
        color: $text-muted;
        height: 1fr;
        display: none;
    }
    TodosView #todo-tree {
        height: 1fr;
    }
    """

    class SelectionChanged(Message):
        def __init__(self, item: Item | None) -> None:
            self.item = item
            super().__init__()

    def __init__(self, *children, **kwargs) -> None:
        super().__init__(*children, **kwargs)
        self._items: list[Item] = []
        self._active_filter: str = "open"
        self._active_tag: str | None = None
        self._filter: FilterSpec = FilterSpec()
        self._voice = ViewVoiceHoldHandler(
            self, on_transcript=self._on_voice_transcript
        )

    def _on_voice_transcript(self, text: str) -> None:
        self.app.voice_create_for_active_tab(text)

    def on_key(self, event) -> None:
        if self._voice.handle_key(event):
            event.stop()
            return
        if event.key in ("left", "right"):
            panels = ["todo-sidebar-tree", "todo-tree"]
            direction = 1 if event.key == "right" else -1
            focused = self.app.focused
            idx = None
            for i, pid in enumerate(panels):
                try:
                    w = self.query_one(f"#{pid}")
                except Exception:
                    continue
                if focused is w or (focused is not None and w in focused.ancestors):
                    idx = i
                    break
            target_idx = (idx + direction) if idx is not None else 0
            if 0 <= target_idx < len(panels):
                try:
                    self.query_one(f"#{panels[target_idx]}").focus()
                    event.stop()
                    event.prevent_default()
                except Exception:
                    pass

    def compose(self) -> ComposeResult:
        yield TodoSidebar(active_filter=self._active_filter, id="todo-sidebar")
        with Container(id="todos-main"):
            yield Static("", id="todos-filter-banner")
            tree: Tree[Item] = Tree("Todos", id="todo-tree")
            tree.show_root = False
            tree.show_guides = True
            yield tree
            yield Static("No todos — press [bold]n[/] to create one", id="todos-empty")

    def refresh_view(self, todos: list[Item]) -> None:
        self._items = todos
        all_tags = sorted({tag for t in todos for tag in t.tags})
        self.query_one(TodoSidebar).update_tags(all_tags)
        self._rebuild_tree()

    def all_tags(self) -> list[str]:
        return sorted({tag for t in self._items for tag in t.tags})

    def apply_filter(self, spec: FilterSpec) -> None:
        self._filter = spec
        banner = self.query_one("#todos-filter-banner", Static)
        if spec.is_active:
            banner.update(Text.assemble(
                ("Filter: ", "bold"),
                (spec.summary(), ""),
                (" - f to change, ^f to clear", "dim"),
            ))
            banner.display = True
        else:
            banner.display = False
        self._rebuild_tree()

    def _filtered_todos(self) -> list[Item]:
        today = date.today()
        items = self._items

        if self._active_filter == "open":
            matched = [t for t in items if not t.is_done]
        elif self._active_filter == "overdue":
            matched = [t for t in items if not t.is_done and t.due and t.due < today]
        elif self._active_filter == "today":
            matched = [t for t in items if not t.is_done and t.due == today]
        elif self._active_filter == "done":
            matched = [t for t in items if t.is_done]
        else:  # "all"
            matched = list(items)

        if self._active_tag:
            matched = [t for t in matched if self._active_tag in t.tags]

        if self._filter.is_active:
            matched = [
                t for t in matched
                if matches_text(self._filter, t.title)
                and matches_tag(self._filter, t.tags)
                and matches_date(self._filter, t.due)
            ]

        # Include ancestors of matched items.
        matched_ids = {t.id for t in matched}
        by_id = {t.id: t for t in items}
        visible_ids: set[str] = set(matched_ids)
        for todo in matched:
            parent_id = todo.parent_id
            while parent_id and parent_id in by_id:
                visible_ids.add(parent_id)
                parent_id = by_id[parent_id].parent_id

        return [t for t in items if t.id in visible_ids]

    def _rebuild_tree(self) -> None:
        tree = self.query_one("#todo-tree", Tree)
        empty = self.query_one("#todos-empty", Static)

        tree.clear()
        items = self._filtered_todos()

        if not items:
            tree.display = False
            empty.display = True
            self.post_message(self.SelectionChanged(None))
            return

        tree.display = True
        empty.display = False

        by_id: dict[str, Item] = {t.id: t for t in items}
        children_by_parent: dict[str, list[Item]] = {}
        for t in items:
            if t.parent_id and t.parent_id in by_id:
                children_by_parent.setdefault(t.parent_id, []).append(t)

        root_items = [t for t in items if not t.parent_id or t.parent_id not in by_id]
        first_node: list = []

        for todo in root_items:
            if children_by_parent.get(todo.id):
                branch = tree.root.add(_todo_label(todo), data=todo, expand=True)
                if not first_node:
                    first_node.append(branch)
                _add_children(branch, todo.id, children_by_parent, first_node)
            else:
                leaf = tree.root.add_leaf(_todo_label(todo), data=todo)
                if not first_node:
                    first_node.append(leaf)

        if first_node:
            tree.move_cursor(first_node[0])
            self.post_message(self.SelectionChanged(first_node[0].data))

    def filter_counts(self) -> dict[str, int]:
        today = date.today()
        items = self._items
        return {
            "open": sum(1 for t in items if not t.is_done),
            "overdue": sum(1 for t in items if not t.is_done and t.due and t.due < today),
            "today": sum(1 for t in items if not t.is_done and t.due == today),
            "all": len(items),
            "done": sum(1 for t in items if t.is_done),
        }

    def selected_todo(self) -> Item | None:
        node = self.query_one("#todo-tree", Tree).cursor_node
        if node is None:
            return None
        return node.data  # type: ignore[return-value]

    def focus_content(self) -> None:
        self.query_one("#todo-tree", Tree).focus()

    def action_toggle_selected(self) -> None:
        self.app.action_toggle_todo()  # type: ignore[attr-defined]

    @on(TodoSidebar.Changed)
    def _on_sidebar_changed(self, event: TodoSidebar.Changed) -> None:
        self._active_filter = event.filter_id
        self._active_tag = event.tag
        self._rebuild_tree()

    @on(Tree.NodeHighlighted, "#todo-tree")
    def _on_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        item: Item | None = event.node.data  # type: ignore[assignment]
        self.post_message(self.SelectionChanged(item))
