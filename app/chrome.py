from __future__ import annotations

from datetime import datetime

from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static


class ChronicleHeader(Static):
    """Top header: centered clock flanked by horizontal rule lines."""

    def on_mount(self) -> None:
        self._refresh_clock()
        self.set_interval(30, self._refresh_clock)

    def on_resize(self) -> None:
        self._refresh_clock()

    def _refresh_clock(self) -> None:
        now = datetime.now().astimezone()
        clock = f"{now.strftime('%a %b')} {now.day}  {now.strftime('%H:%M')}"
        text = Text(clock, style="bold", justify="right")
        self.update(text)


class StatusBar(Static):
    hints: reactive[list[tuple[str, str]]] = reactive([], layout=False)
    count = reactive("", layout=False)
    voice_state = reactive("idle")  # "idle" | "recording" | "transcribing"

    def render(self) -> Text:
        if self.voice_state == "recording":
            return Text("🎙  Recording… release space to stop", style="bold white on red")
        if self.voice_state == "transcribing":
            return Text("⏳  Transcribing…", style="bold black on yellow")

        text = Text()
        for i, (key, desc) in enumerate(self.hints):
            if i > 0:
                text.append("  ", style="dim")
            text.append(f"{desc}: ", style="dim")
            text.append(f"{key}", style="bold")
        if self.count:
            text.append(" — ", style="dim")
            text.append(self.count, style="dim italic")
        return text
