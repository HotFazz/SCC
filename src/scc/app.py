from __future__ import annotations

import json
from pathlib import Path
from threading import Event

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.widgets import Footer, Header, ListItem, ListView, Select, Static
from watchfiles import watch

from scc.board_view import SwarmBoard
from scc.domain import GraphSnapshot, TimelineEvent
from scc.loader import ClaudeStateLoader
from scc.view import (
    FocusOption,
    FocusedSnapshot,
    build_focus_options,
    build_transcript_events,
    focus_snapshot,
    pick_default_node,
)


class SCCApp(App[None]):
    TITLE = "SCC"
    SUB_TITLE = "Swarm Central Control"
    CSS = """
    Screen {
      layout: vertical;
    }

    #summary {
      height: 3;
      padding: 0 1;
      background: $panel;
      color: $text;
      border: solid $boost;
    }

    #focus {
      margin: 1 0;
    }

    #main {
      height: 1fr;
    }

    #graph-scroll {
      width: 2fr;
      border: solid $accent;
      padding: 1;
    }

    #board {
      width: auto;
      height: auto;
    }

    #sidebar {
      width: 1fr;
      margin-left: 1;
    }

    #timeline {
      height: 1fr;
      border: solid $success;
    }

    #timeline > ListItem {
      padding: 0 1;
      margin-bottom: 1;
    }

    #inspector {
      height: 16;
      margin-top: 1;
      padding: 1;
      border: solid $warning;
      overflow-y: auto;
    }
    """
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "reload_data", "Reload"),
    ]

    def __init__(self, claude_home: Path | str, workspace: Path | str) -> None:
        super().__init__()
        self.claude_home = Path(claude_home).expanduser()
        self.workspace = Path(workspace).expanduser()
        self.loader = ClaudeStateLoader(self.claude_home)
        self.snapshot = GraphSnapshot()
        self.focused_view = FocusedSnapshot(
            focus=FocusOption(label="All activity", value="all", timestamp=None),
            snapshot=GraphSnapshot(),
            events=[],
        )
        self.selected_node_id: str | None = None
        self.focus_value = "all"
        self.status_line = "Loading Claude state..."
        self._visible_events: list = []
        self._transcript_events: list[TimelineEvent] = []
        self._watch_stop = Event()
        self._updating_focus_select = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Loading Claude state...", id="summary")
        yield Select([("Loading...", "all")], allow_blank=False, value="all", id="focus")
        with Horizontal(id="main"):
            with ScrollableContainer(id="graph-scroll"):
                yield SwarmBoard()
            with Vertical(id="sidebar"):
                yield ListView(id="timeline")
                yield Static("Select a node or event to inspect details.", id="inspector", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#graph-scroll", ScrollableContainer).border_title = "Query Flow"
        self.query_one("#timeline", ListView).border_title = "Claude Transcript"
        self.query_one("#inspector", Static).border_title = "Inspector"
        self.load_snapshot()
        self.watch_claude_state()

    def on_unmount(self) -> None:
        self._watch_stop.set()

    def action_reload_data(self) -> None:
        self.load_snapshot()

    @work(thread=True, exclusive=True, group="reload")
    def load_snapshot(self) -> None:
        snapshot = self.loader.load()
        self.call_from_thread(self._apply_snapshot, snapshot)

    @work(thread=True, exclusive=True, group="watch")
    def watch_claude_state(self) -> None:
        watch_paths = [
            path
            for path in (
                self.claude_home / "projects",
                self.claude_home / "teams",
                self.claude_home / "tasks",
            )
            if path.exists()
        ]
        if not watch_paths:
            return

        for _changes in watch(*watch_paths, stop_event=self._watch_stop, debounce=500):
            self.call_from_thread(self.load_snapshot)

    def _apply_snapshot(self, snapshot: GraphSnapshot) -> None:
        self.snapshot = snapshot
        options = build_focus_options(snapshot)
        select = self.query_one("#focus", Select)
        self._updating_focus_select = True
        try:
            if not options:
                select.set_options([("All activity", "all")])
                self.focus_value = "all"
            else:
                select.set_options([(option.label, option.value) for option in options])
                valid_values = {option.value for option in options}
                if self.focus_value not in valid_values:
                    self.focus_value = options[0].value
            select.value = self.focus_value
        finally:
            self._updating_focus_select = False
        self._refresh_focus()

    def _refresh_focus(self) -> None:
        self.focused_view = focus_snapshot(self.snapshot, self.focus_value)
        self._visible_events = self.focused_view.events
        self._transcript_events = build_transcript_events(self.focused_view)
        if self.selected_node_id not in self.focused_view.snapshot.nodes:
            self.selected_node_id = pick_default_node(self.focused_view.snapshot)
        self._render_graph()
        self._render_timeline()
        self._render_inspector()
        self._render_summary()

    def _render_graph(self) -> None:
        self.query_one(SwarmBoard).update_from_snapshot(
            self.focused_view.snapshot,
            selected_node_id=self.selected_node_id,
        )

    def _render_timeline(self) -> None:
        timeline = self.query_one("#timeline", ListView)
        timeline.clear()
        items = []
        for event in self._transcript_events:
            items.append(ListItem(Static(self._timeline_text(event), markup=False)))
        if items:
            timeline.extend(items)
        else:
            timeline.extend([ListItem(Static(self._empty_timeline_text(), markup=False))])

    def _render_inspector(self) -> None:
        inspector = self.query_one("#inspector", Static)
        if not self.selected_node_id or self.selected_node_id not in self.focused_view.snapshot.nodes:
            inspector.update("Select a node or event to inspect details.")
            return

        node = self.focused_view.snapshot.nodes[self.selected_node_id]
        connected = [
            edge
            for edge in self.focused_view.snapshot.edges
            if edge.source == node.id or edge.target == node.id
        ]
        lines = [
            f"id: {node.id}",
            f"kind: {node.kind.value}",
            f"label: {node.label}",
        ]
        if node.cluster:
            lines.append(f"cluster: {node.cluster}")
        if node.session_id:
            lines.append(f"session: {node.session_id}")
        if node.status:
            lines.append(f"status: {node.status}")
        lines.append(f"edges: {len(connected)}")
        raw_text = str(node.metadata.get("raw_text", "")).strip()
        if raw_text:
            lines.append("")
            lines.append("message:")
            lines.append(raw_text[:1200])
        if node.metadata:
            lines.append("")
            lines.append("metadata:")
            for key, value in sorted(node.metadata.items()):
                if key == "raw_text":
                    continue
                rendered = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
                lines.append(f"  {key}: {rendered[:180]}")
        inspector.update("\n".join(lines))

    def _render_summary(self) -> None:
        summary = self.query_one("#summary", Static)
        lines = [
            f"{self.focused_view.focus.label} | query flow | nodes {len(self.focused_view.snapshot.nodes)} | "
            f"edges {len(self.focused_view.snapshot.edges)} | messages {len(self._transcript_events)}",
            self.status_line,
            f"workspace: {self.workspace}",
        ]
        summary.update("\n".join(lines))

    def on_select_changed(self, event: Select.Changed[str]) -> None:
        if self._updating_focus_select or event.select.id != "focus" or event.value is None:
            return
        self.focus_value = str(event.value)
        self._refresh_focus()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id != "timeline":
            return
        index = event.list_view.index
        if index is None or index < 0 or index >= len(self._transcript_events):
            return
        source_node_id = self._transcript_events[index].source_node_id
        if source_node_id and source_node_id in self.focused_view.snapshot.nodes:
            self.selected_node_id = source_node_id
            self._render_graph()
            self._render_inspector()

    @on(SwarmBoard.CardSelected)
    def handle_board_card_selected(self, message: SwarmBoard.CardSelected) -> None:
        if message.node_id not in self.focused_view.snapshot.nodes:
            return
        self.selected_node_id = message.node_id
        self._render_graph()
        self._render_inspector()

    def _timeline_text(self, event: TimelineEvent) -> str:
        speaker = str(event.metadata.get("speaker") or self._fallback_speaker(event))
        stamp = (event.timestamp or "--------")[11:19] if event.timestamp else "--------"
        detail = (event.detail or event.title).strip()
        return f"{speaker}  {stamp}\n{detail}"

    def _fallback_speaker(self, event: TimelineEvent) -> str:
        if event.kind == "user_turn":
            return "You"
        if event.kind == "assistant_turn":
            return "Claude Code"
        return "Event"

    def _empty_timeline_text(self) -> str:
        if self.focus_value.startswith("team:"):
            return (
                "No primary Claude Code transcript is recorded for this team.\n"
                "Select a Session focus to inspect a worker conversation."
            )
        return "No Claude Code transcript available for the current focus."
