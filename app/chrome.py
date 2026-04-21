from __future__ import annotations

from datetime import datetime

from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static


class ChronicleHeader(Static):
    active_tab = reactive("journal")

    def render(self) -> Text:
        now = datetime.now().astimezone()
        today = f"{now.strftime('%a %b')} {now.day}"
        tabs = Text()
        tabs.append(" Journal ", style="reverse" if self.active_tab == "journal" else "bold")
        tabs.append(" ")
        tabs.append(" Todos ", style="reverse" if self.active_tab == "todos" else "bold")

        header = Text.assemble(
            (" Chronicle ", "bold black on cyan"),
            ("  ", ""),
            tabs,
            ("  ", ""),
            (today, "bold magenta"),
            ("  ", ""),
            ("? help", "dim"),
        )
        return header


class StatusBar(Static):
    message = reactive("")

    def render(self) -> Text:
        return Text(self.message, style="black on white")
