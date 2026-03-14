from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from scc.domain import EdgeKind, GraphNode, GraphSnapshot, NodeKind
from scc.layout import LayoutResult


@dataclass(slots=True)
class GraphDocument:
    text: str
    width: int
    height: int
    boxes: dict[str, tuple[int, int, int, int]] = field(default_factory=dict)


@dataclass(slots=True)
class FlowEntry:
    label: str
    node_id: str | None = None
    children: list["FlowEntry"] = field(default_factory=list)


class AsciiGraphRenderer:
    def __init__(self, max_line_length: int = 92, recent_turn_limit: int = 6) -> None:
        self.max_line_length = max_line_length
        self.recent_turn_limit = recent_turn_limit

    def render(
        self,
        snapshot: GraphSnapshot,
        layout: LayoutResult,
        selected_node_id: str | None = None,
    ) -> GraphDocument:
        if not snapshot.nodes:
            return GraphDocument("No graph data available for the current focus.", 44, 1)

        entries = self._build_entries(snapshot, selected_node_id)
        if not entries:
            return GraphDocument("No graph data available for the current focus.", 44, 1)

        lines = ["Flow view: recent swarm activity grouped by team and agent.", ""]
        for index, entry in enumerate(entries):
            self._append_entry(lines, entry, prefixes=[], is_last=index == len(entries) - 1, selected_node_id=selected_node_id)
            if index != len(entries) - 1:
                lines.append("")

        width = max(len(line) for line in lines) if lines else 0
        return GraphDocument("\n".join(lines), width=width, height=len(lines))

    def _build_entries(self, snapshot: GraphSnapshot, selected_node_id: str | None) -> list[FlowEntry]:
        turns_by_agent: dict[str, list[GraphNode]] = defaultdict(list)
        assignees_by_task: dict[str, list[str]] = defaultdict(list)
        blockers_by_task: dict[str, list[str]] = defaultdict(list)

        for edge in snapshot.edges:
            if edge.kind == EdgeKind.ROUTED_TO and edge.target in snapshot.nodes and edge.source in snapshot.nodes:
                if snapshot.nodes[edge.source].kind == NodeKind.USER_REQUEST and snapshot.nodes[edge.target].kind == NodeKind.AGENT:
                    turns_by_agent[edge.target].append(snapshot.nodes[edge.source])
            if edge.kind == EdgeKind.PRODUCED and edge.source in snapshot.nodes and edge.target in snapshot.nodes:
                if snapshot.nodes[edge.source].kind == NodeKind.AGENT and snapshot.nodes[edge.target].kind == NodeKind.MODEL_TURN:
                    turns_by_agent[edge.source].append(snapshot.nodes[edge.target])
            if edge.kind == EdgeKind.ASSIGNED and edge.source in snapshot.nodes and edge.target in snapshot.nodes:
                if snapshot.nodes[edge.source].kind == NodeKind.TASK and snapshot.nodes[edge.target].kind == NodeKind.AGENT:
                    assignees_by_task[edge.source].append(edge.target)
            if edge.kind == EdgeKind.BLOCKED_BY:
                blockers_by_task[edge.target].append(edge.source)

        teams = sorted(
            (node for node in snapshot.nodes.values() if node.kind == NodeKind.TEAM),
            key=lambda item: item.label,
        )
        if teams:
            return [
                self._render_team(snapshot, team, turns_by_agent, assignees_by_task, blockers_by_task, selected_node_id)
                for team in teams
            ]

        sessions = sorted({node.session_id for node in snapshot.nodes.values() if node.session_id})
        if sessions:
            return [
                self._render_session(snapshot, session_id, turns_by_agent, selected_node_id)
                for session_id in sessions
            ]

        agents = sorted(
            (node for node in snapshot.nodes.values() if node.kind == NodeKind.AGENT),
            key=lambda item: item.label,
        )
        return [
            self._render_agent(snapshot, agent, turns_by_agent, selected_node_id)
            for agent in agents
        ]

    def _render_team(
        self,
        snapshot: GraphSnapshot,
        team: GraphNode,
        turns_by_agent: dict[str, list[GraphNode]],
        assignees_by_task: dict[str, list[str]],
        blockers_by_task: dict[str, list[str]],
        selected_node_id: str | None,
    ) -> FlowEntry:
        root = FlowEntry(label=f"[T] {team.label}", node_id=team.id)
        agents = self._team_agents(snapshot, team.label)
        lead = next((agent for agent in agents if self._is_lead(agent)), None)
        workers = [agent for agent in agents if agent.id != getattr(lead, "id", None)]
        tasks = self._team_tasks(snapshot, team.label)

        if lead is not None:
            lead_entry = self._render_agent(snapshot, lead, turns_by_agent, selected_node_id)
            lead_entry.children.extend(
                self._render_task(snapshot, task, assignees_by_task, blockers_by_task)
                for task in tasks
            )
            lead_entry.children.extend(
                self._render_agent(snapshot, worker, turns_by_agent, selected_node_id)
                for worker in workers
            )
            root.children.append(lead_entry)
        else:
            root.children.extend(
                self._render_agent(snapshot, agent, turns_by_agent, selected_node_id)
                for agent in agents
            )
            root.children.extend(
                self._render_task(snapshot, task, assignees_by_task, blockers_by_task)
                for task in tasks
            )

        if not root.children:
            root.children.append(FlowEntry(label="(no visible agents or tasks)"))
        return root

    def _render_session(
        self,
        snapshot: GraphSnapshot,
        session_id: str,
        turns_by_agent: dict[str, list[GraphNode]],
        selected_node_id: str | None,
    ) -> FlowEntry:
        root = FlowEntry(label=f"[S] session {session_id[:8]}", node_id=None)
        agents = sorted(
            (
                node
                for node in snapshot.nodes.values()
                if node.kind == NodeKind.AGENT and node.session_id == session_id
            ),
            key=lambda item: item.label,
        )
        root.children.extend(
            self._render_agent(snapshot, agent, turns_by_agent, selected_node_id)
            for agent in agents
        )
        if not root.children:
            loose_turns = sorted(
                (
                    node
                    for node in snapshot.nodes.values()
                    if node.session_id == session_id and node.kind in {NodeKind.USER_REQUEST, NodeKind.MODEL_TURN}
                ),
                key=self._node_sort_key,
            )[-self.recent_turn_limit :]
            root.children.extend(self._render_turn(node) for node in loose_turns)
        return root

    def _render_agent(
        self,
        snapshot: GraphSnapshot,
        agent: GraphNode,
        turns_by_agent: dict[str, list[GraphNode]],
        selected_node_id: str | None,
    ) -> FlowEntry:
        suffix = []
        if agent.status:
            suffix.append(agent.status)
        model = str(agent.metadata.get("model", "")).strip()
        if model and model not in {"None", ""}:
            suffix.append(model)
        label = f"[A] {agent.label}"
        if suffix:
            label += f" [{' | '.join(suffix)}]"

        entry = FlowEntry(label=label, node_id=agent.id)
        turns = sorted(
            {turn.id: turn for turn in turns_by_agent.get(agent.id, [])}.values(),
            key=self._node_sort_key,
        )

        if turns:
            visible = self._visible_turns(turns, selected_node_id)
            hidden_count = max(0, len(turns) - len(visible))
            if hidden_count:
                entry.children.append(FlowEntry(label=f"... {hidden_count} earlier turns hidden"))
            entry.children.extend(self._render_turn(turn) for turn in visible)
        else:
            entry.children.append(FlowEntry(label="(no recent turns)"))
        return entry

    def _render_task(
        self,
        snapshot: GraphSnapshot,
        task: GraphNode,
        assignees_by_task: dict[str, list[str]],
        blockers_by_task: dict[str, list[str]],
    ) -> FlowEntry:
        status = task.status or "unknown"
        assignee_labels = [
            snapshot.nodes[agent_id].label
            for agent_id in assignees_by_task.get(task.id, [])
            if agent_id in snapshot.nodes
        ]
        label = f"[K] {task.label} [{status}]"
        if assignee_labels:
            label += f" -> {', '.join(sorted(assignee_labels))}"
        entry = FlowEntry(label=label, node_id=task.id)

        blocker_labels = [
            snapshot.nodes[task_id].label
            for task_id in blockers_by_task.get(task.id, [])
            if task_id in snapshot.nodes
        ]
        if blocker_labels:
            entry.children.append(
                FlowEntry(label=f"blocked by: {', '.join(sorted(blocker_labels))}")
            )
        return entry

    def _render_turn(self, node: GraphNode) -> FlowEntry:
        prefix = "[U]" if node.kind == NodeKind.USER_REQUEST else "[M]"
        return FlowEntry(label=f"{prefix} {node.label}", node_id=node.id)

    def _visible_turns(self, turns: list[GraphNode], selected_node_id: str | None) -> list[GraphNode]:
        if len(turns) <= self.recent_turn_limit:
            return turns

        visible = turns[-self.recent_turn_limit :]
        if selected_node_id:
            selected = next((turn for turn in turns if turn.id == selected_node_id), None)
            if selected and all(turn.id != selected.id for turn in visible):
                visible = visible[1:] + [selected]
                visible = sorted(visible, key=self._node_sort_key)
        return visible

    def _append_entry(
        self,
        lines: list[str],
        entry: FlowEntry,
        prefixes: list[bool],
        is_last: bool,
        selected_node_id: str | None,
    ) -> None:
        marker = "* " if entry.node_id == selected_node_id else "  "
        if prefixes:
            branch = "".join("|  " if has_more else "   " for has_more in prefixes[:-1])
            connector = "`- " if is_last else "|- "
            raw = f"{branch}{connector}{marker}{entry.label}"
        else:
            raw = f"{marker}{entry.label}"
        lines.append(self._shorten(raw))

        for index, child in enumerate(entry.children):
            self._append_entry(
                lines,
                child,
                prefixes + [not is_last],
                is_last=index == len(entry.children) - 1,
                selected_node_id=selected_node_id,
            )

    def _team_agents(self, snapshot: GraphSnapshot, team_name: str) -> list[GraphNode]:
        return sorted(
            (
                node
                for node in snapshot.nodes.values()
                if node.kind == NodeKind.AGENT and node.cluster == team_name
            ),
            key=lambda item: (not self._is_lead(item), item.label),
        )

    def _team_tasks(self, snapshot: GraphSnapshot, team_name: str) -> list[GraphNode]:
        return sorted(
            (
                node
                for node in snapshot.nodes.values()
                if node.kind == NodeKind.TASK and node.cluster == team_name
            ),
            key=lambda item: (item.status == "completed", item.label),
        )

    def _is_lead(self, agent: GraphNode) -> bool:
        return agent.label == "team-lead" or agent.metadata.get("agent_type") == "team-lead"

    def _node_sort_key(self, node: GraphNode) -> tuple[str, str]:
        return (node.timestamp or "", node.id)

    def _shorten(self, text: str) -> str:
        if len(text) <= self.max_line_length:
            return text
        if self.max_line_length <= 3:
            return text[: self.max_line_length]
        return text[: self.max_line_length - 3].rstrip() + "..."
