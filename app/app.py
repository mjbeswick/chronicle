"""Minimal Textual application scaffold for Chronicle."""

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Static


class ChronicleApp(App[None]):
    """Minimal app shell so the storage layer can be imported and wired later."""

    TITLE = "Chronicle"
    SUB_TITLE = "Storage scaffold ready"

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("Chronicle storage layer scaffold", id="placeholder")
        yield Footer()
