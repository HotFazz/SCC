from __future__ import annotations

import json
from pathlib import Path
from threading import Event

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.widgets import Button, Footer, Header, Input, Label, ListItem, ListView, Select, Static
from watchfiles import watch

from scc.claude_cli import ClaudeCLIClient, ClaudeCommandResult
from scc.domain import GraphSnapshot
from scc.layout import AutoLayoutEngine, LayoutResult
from scc.loader import ClaudeStateLoader
from scc.render import AsciiGraphRenderer
from scc.view import FocusOption, FocusedSnapshot, build_focus_options, focus_snapshot, pick_default_node


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

    #graph {
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

    #inspector {
      height: 16;
      margin-top: 1;
      padding: 1;
      border: solid $warning;
      overflow-y: auto;
    }

    #composer {
      height: 3;
      margin-top: 1;
    }

    #prompt {
      width: 1fr;
      margin-right: 1;
    }

    Button {
      width: 12;
      margin-left: 1;
    }
    """
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "reload_data", "Reload"),
        Binding("ctrl+l", "focus_prompt", "Prompt"),
    ]

    def __init__(self, claude_home: Path | str, workspace: Path | str) -> None:
        super().__init__()
        self.claude_home = Path(claude_home).expanduser()
        self.workspace = Path(workspace).expanduser()
        self.loader = ClaudeStateLoader(self.claude_home)
        self.layout_engine = AutoLayoutEngine()
        self.renderer = AsciiGraphRenderer()
        self.claude = ClaudeCLIClient()
        self.snapshot = GraphSnapshot()
        self.focused_view = FocusedSnapshot(
            focus=FocusOption(label="All activity", value="all", timestamp=None),
            snapshot=GraphSnapshot(),
            events=[],
        )
        self.layout_result = LayoutResult("layered", 0.0, 0.0, {}, {})
        self.selected_node_id: str | None = None
        self.focus_value = "all"
        self.status_line = "Loading Claude state..."
        self.last_command_result: ClaudeCommandResult | None = None
        self._visible_events: list = []
        self._watch_stop = Event()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Loading Claude state...", id="summary")
        yield Select([("Loading...", "all")], allow_blank=False, value="all", id="focus")
        with Horizontal(id="main"):
            with ScrollableContainer(id="graph-scroll"):
                yield Static(id="graph")
            with Vertical(id="sidebar"):
                yield ListView(id="timeline")
                yield Static("Select a node or event to inspect details.", id="inspector")
        with Horizontal(id="composer"):
            yield Input(placeholder="Send a prompt through Claude Code", id="prompt")
            yield Button("Send", id="send")
            yield Button("Reload", id="reload")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#graph-scroll", ScrollableContainer).border_title = "Graph"
        self.query_one("#timeline", ListView).border_title = "Timeline"
        self.query_one("#inspector", Static).border_title = "Inspector"
        self.load_snapshot()
        self.watch_claude_state()

    def on_unmount(self) -> None:
        self._watch_stop.set()

    def action_reload_data(self) -> None:
        self.load_snapshot()

    def action_focus_prompt(self) -> None:
        self.query_one("#prompt", Input).focus()

    @work(thread=True, exclusive=True, group="reload")
    def load_snapshot(self) -> None:
        snapshot = ClaudeStateLoader(self.claude_home).load()
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
        if not options:
            select.set_options([("All activity", "all")])
            self.focus_value = "all"
        else:
            select.set_options([(option.label, option.value) for option in options])
            valid_values = {option.value for option in options}
            if self.focus_value not in valid_values:
                self.focus_value = options[0].value
        select.value = self.focus_value
        self._refresh_focus()

    def _refresh_focus(self) -> None:
        self.focused_view = focus_snapshot(self.snapshot, self.focus_value)
        self._visible_events = self.focused_view.events
        if self.selected_node_id not in self.focused_view.snapshot.nodes:
            self.selected_node_id = pick_default_node(self.focused_view.snapshot)
        self.layout_result = self.layout_engine.layout(self.focused_view.snapshot)
        self._render_graph()
        self._render_timeline()
        self._render_inspector()
        self._render_summary()

    def _render_graph(self) -> None:
        document = self.renderer.render(
            self.focused_view.snapshot,
            self.layout_result,
            selected_node_id=self.selected_node_id,
        )
        self.query_one("#graph", Static).update(document.text)

    def _render_timeline(self) -> None:
        timeline = self.query_one("#timeline", ListView)
        timeline.clear()
        items = []
        for event in self._visible_events:
            stamp = (event.timestamp or "--------")[11:19] if event.timestamp else "--------"
            items.append(ListItem(Label(f"{stamp}  {event.title}")))
        if items:
            timeline.extend(items)

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
        if node.metadata:
            lines.append("")
            lines.append("metadata:")
            for key, value in sorted(node.metadata.items()):
                rendered = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
                lines.append(f"  {key}: {rendered[:180]}")
        inspector.update("\n".join(lines))

    def _render_summary(self) -> None:
        summary = self.query_one("#summary", Static)
        lines = [
            f"{self.focused_view.focus.label} | nodes {len(self.focused_view.snapshot.nodes)} | "
            f"edges {len(self.focused_view.snapshot.edges)} | events {len(self._visible_events)} | "
            f"layout {self.layout_result.engine}",
            self.status_line,
        ]
        if self.last_command_result is not None:
            state = "ok" if self.last_command_result.ok else "error"
            text = self.last_command_result.display_text.replace("\n", " ")
            lines.append(f"last prompt: {state} | {text[:120]}")
        else:
            lines.append(f"workspace: {self.workspace}")
        summary.update("\n".join(lines))

    def on_select_changed(self, event: Select.Changed[str]) -> None:
        if event.select.id != "focus" or event.value is None:
            return
        self.focus_value = str(event.value)
        self._refresh_focus()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id != "timeline":
            return
        index = event.list_view.index
        if index is None or index < 0 or index >= len(self._visible_events):
            return
        source_node_id = self._visible_events[index].source_node_id
        if source_node_id and source_node_id in self.focused_view.snapshot.nodes:
            self.selected_node_id = source_node_id
            self._render_graph()
            self._render_inspector()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "send":
            self._submit_prompt()
        if event.button.id == "reload":
            self.action_reload_data()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "prompt":
            self._submit_prompt()

    def _submit_prompt(self) -> None:
        prompt_widget = self.query_one("#prompt", Input)
        prompt = prompt_widget.value.strip()
        if not prompt:
            self.status_line = "Prompt is empty."
            self._render_summary()
            return

        prompt_widget.disabled = True
        self.query_one("#send", Button).disabled = True
        self.status_line = "Sending prompt to Claude Code..."
        self._render_summary()
        self.send_prompt(prompt, self._resume_session_id())

    def _resume_session_id(self) -> str | None:
        if self.selected_node_id and self.selected_node_id in self.focused_view.snapshot.nodes:
            selected = self.focused_view.snapshot.nodes[self.selected_node_id]
            if selected.session_id:
                return selected.session_id
        if self.focus_value.startswith("session:"):
            return self.focus_value.split(":", 1)[1]
        if self.focus_value.startswith("team:"):
            team_node_id = self.focus_value
            team_node = self.snapshot.nodes.get(team_node_id)
            if team_node and team_node.session_id:
                return team_node.session_id
        return None

    @work(thread=True, exclusive=True, group="claude")
    def send_prompt(self, prompt: str, resume_session_id: str | None) -> None:
        result = self.claude.send_prompt(prompt, workspace=self.workspace, resume_session_id=resume_session_id)
        self.call_from_thread(self._handle_prompt_result, prompt, result)

    def _handle_prompt_result(self, prompt: str, result: ClaudeCommandResult) -> None:
        self.last_command_result = result
        prompt_widget = self.query_one("#prompt", Input)
        prompt_widget.value = ""
        prompt_widget.disabled = False
        prompt_widget.focus()
        self.query_one("#send", Button).disabled = False
        status = "Prompt completed." if result.ok else "Prompt failed."
        session_text = f" session={result.session_id}" if result.session_id else ""
        self.status_line = f"{status}{session_text}"
        self._render_summary()
        self.load_snapshot()
