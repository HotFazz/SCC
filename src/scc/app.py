from textual.app import App, ComposeResult
from textual.containers import Center
from textual.widgets import Footer, Header, Static


class SCCApp(App[None]):
    TITLE = "SCC"
    SUB_TITLE = "Swarm Central Control"

    def compose(self) -> ComposeResult:
        yield Header()
        with Center():
            yield Static(
                "SCC scaffold is in place.\n"
                "Graph ingestion and the live monitor land next.",
                id="placeholder",
            )
        yield Footer()

