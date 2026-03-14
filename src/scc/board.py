from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from scc.domain import EdgeKind, GraphEdge, GraphNode, GraphSnapshot, NodeKind, TimelineEvent

LANE_ORDER = ("requests", "lead", "tasks", "workers", "summaries")
LANE_TITLES = {
    "requests": "Requests",
    "lead": "Lead",
    "tasks": "Tasks",
    "workers": "Workers",
    "summaries": "Summaries",
}
LANE_PREFIXES = {
    "requests": "R",
    "lead": "L",
    "tasks": "T",
    "workers": "W",
    "summaries": "S",
}


@dataclass(slots=True)
class BoardCard:
    card_id: str
    lane: str
    title: str
    subtitle: str | None = None
    body_lines: list[str] = field(default_factory=list)
    node_ids: set[str] = field(default_factory=set)


@dataclass(slots=True)
class BoardRow:
    cells: dict[str, BoardCard] = field(default_factory=dict)


@dataclass(slots=True)
class BoardConnection:
    source_id: str
    target_id: str
    kind: str
    label: str


@dataclass(slots=True)
class BoardModel:
    title: str
    rows: list[BoardRow]
    connections: list[BoardConnection]
    selected_card_id: str | None


class BoardBuilder:
    def __init__(self, request_limit: int = 3, summary_limit: int = 3) -> None:
        self.request_limit = request_limit
        self.summary_limit = summary_limit
        self._counters: dict[str, int] = defaultdict(int)

    def build(self, snapshot: GraphSnapshot, selected_node_id: str | None = None) -> BoardModel:
        self._counters.clear()
        teams = sorted(
            (node for node in snapshot.nodes.values() if node.kind == NodeKind.TEAM),
            key=lambda item: item.label,
        )
        if teams:
            return self._build_team_board(snapshot, teams[0], selected_node_id)

        session_ids = sorted({node.session_id for node in snapshot.nodes.values() if node.session_id})
        if session_ids:
            return self._build_session_board(snapshot, session_ids[0], selected_node_id)

        return BoardModel(title="No focus", rows=[], connections=[], selected_card_id=None)

    def _build_team_board(
        self,
        snapshot: GraphSnapshot,
        team: GraphNode,
        selected_node_id: str | None,
    ) -> BoardModel:
        produced_by_agent, requests_by_agent, assigned_by_task, blockers_by_task = self._edge_maps(snapshot)
        timeline_by_source = self._timeline_by_source(snapshot.timeline)
        agents = self._team_agents(snapshot, team.label)
        lead = next((agent for agent in agents if self._is_lead(agent)), agents[0] if agents else None)
        workers = [agent for agent in agents if lead is None or agent.id != lead.id]
        tasks = self._team_tasks(snapshot, team.label)
        rows: list[BoardRow] = []
        connections: list[BoardConnection] = []
        cards: list[BoardCard] = []

        request_card = self._request_card(
            snapshot,
            team.label,
            requests_by_agent.get(lead.id if lead else "", []),
            cards,
        )
        lead_card = self._lead_card(lead, produced_by_agent.get(lead.id if lead else "", []), tasks, workers, cards)
        if request_card or lead_card:
            row = BoardRow()
            if request_card:
                row.cells["requests"] = request_card
            if lead_card:
                row.cells["lead"] = lead_card
            rows.append(row)
            if request_card and lead_card:
                connections.append(
                    BoardConnection(request_card.card_id, lead_card.card_id, "request", "routes")
                )

        worker_cards: dict[str, BoardCard] = {}
        summary_cards: dict[str, BoardCard] = {}
        for worker in workers:
            worker_cards[worker.id] = self._worker_card(worker, produced_by_agent.get(worker.id, []), cards)
            summary_cards[worker.id] = self._summary_card(
                worker,
                produced_by_agent.get(worker.id, []),
                timeline_by_source.get(worker.id, []),
                cards,
            )

        for task in tasks:
            assignees = [snapshot.nodes[node_id] for node_id in assigned_by_task.get(task.id, []) if node_id in snapshot.nodes]
            primary_assignee = assignees[0] if assignees else None
            task_card = self._task_card(task, assignees, blockers_by_task.get(task.id, []), snapshot, cards)
            row = BoardRow(cells={"tasks": task_card})
            if primary_assignee and primary_assignee.id in worker_cards:
                row.cells["workers"] = worker_cards[primary_assignee.id]
                connections.append(
                    BoardConnection(task_card.card_id, worker_cards[primary_assignee.id].card_id, "assignment", "owned by")
                )
                summary_card = summary_cards.get(primary_assignee.id)
                if summary_card:
                    row.cells["summaries"] = summary_card
                    connections.append(
                        BoardConnection(worker_cards[primary_assignee.id].card_id, summary_card.card_id, "summary", "latest")
                    )
                    if lead_card:
                        connections.append(
                            BoardConnection(summary_card.card_id, lead_card.card_id, "report", "reports")
                        )
            elif lead_card:
                connections.append(
                    BoardConnection(lead_card.card_id, task_card.card_id, "dispatch", "dispatches")
                )
            rows.append(row)
            if lead_card:
                connections.append(
                    BoardConnection(lead_card.card_id, task_card.card_id, "dispatch", "dispatches")
                )

        dangling_workers = [
            worker for worker in workers if worker.id not in {self._first_assignee_id(task.id, assigned_by_task) for task in tasks}
        ]
        for worker in dangling_workers:
            row = BoardRow(cells={"workers": worker_cards[worker.id]})
            summary_card = summary_cards.get(worker.id)
            if summary_card:
                row.cells["summaries"] = summary_card
                connections.append(BoardConnection(worker_cards[worker.id].card_id, summary_card.card_id, "summary", "latest"))
                if lead_card:
                    connections.append(BoardConnection(summary_card.card_id, lead_card.card_id, "report", "reports"))
            rows.append(row)

        task_cards_by_node = {
            next(iter(card.node_ids)): card
            for card in cards
            if card.lane == "tasks" and card.node_ids
        }
        for edge in snapshot.edges:
            if edge.kind != EdgeKind.BLOCKED_BY:
                continue
            source_card = task_cards_by_node.get(edge.source)
            target_card = task_cards_by_node.get(edge.target)
            if source_card and target_card:
                connections.append(BoardConnection(source_card.card_id, target_card.card_id, "blocked", "blocks"))

        selected_card_id = self._selected_card(cards, selected_node_id)
        return BoardModel(
            title=f"{team.label} board",
            rows=rows,
            connections=self._dedupe_connections(connections),
            selected_card_id=selected_card_id,
        )

    def _build_session_board(
        self,
        snapshot: GraphSnapshot,
        session_id: str,
        selected_node_id: str | None,
    ) -> BoardModel:
        cards: list[BoardCard] = []
        rows: list[BoardRow] = []
        connections: list[BoardConnection] = []
        produced_by_agent, requests_by_agent, _, _ = self._edge_maps(snapshot)

        agents = sorted(
            (
                node
                for node in snapshot.nodes.values()
                if node.kind == NodeKind.AGENT and node.session_id == session_id
            ),
            key=lambda item: item.label,
        )
        primary = agents[0] if agents else None
        requests = sorted(
            (
                node
                for node in snapshot.nodes.values()
                if node.kind == NodeKind.USER_REQUEST and node.session_id == session_id
            ),
            key=self._node_sort_key,
        )[-self.request_limit :]
        request_card = self._new_card(
            lane="requests",
            title="Recent user requests",
            subtitle=f"{len(requests)} visible" if requests else "No requests",
            body_lines=[node.label for node in requests] or ["No user turns captured."],
            node_ids={node.id for node in requests},
        )
        cards.append(request_card)

        if primary:
            lead_card = self._new_card(
                lane="lead",
                title=primary.label,
                subtitle=self._agent_subtitle(primary),
                body_lines=["Main session agent"],
                node_ids={primary.id},
            )
            cards.append(lead_card)
            rows.append(BoardRow(cells={"requests": request_card, "lead": lead_card}))
            connections.append(BoardConnection(request_card.card_id, lead_card.card_id, "request", "routes"))

            summaries = produced_by_agent.get(primary.id, [])
            summary_card = self._new_card(
                lane="summaries",
                title="Recent assistant output",
                subtitle=f"{len(summaries[-self.summary_limit:])} visible",
                body_lines=[node.label for node in summaries[-self.summary_limit :]] or ["No assistant turns captured."],
                node_ids={node.id for node in summaries[-self.summary_limit :]},
            )
            cards.append(summary_card)
            rows[0].cells["summaries"] = summary_card
            connections.append(BoardConnection(lead_card.card_id, summary_card.card_id, "summary", "produces"))
        else:
            rows.append(BoardRow(cells={"requests": request_card}))

        return BoardModel(
            title=f"session {session_id[:8]} board",
            rows=rows,
            connections=self._dedupe_connections(connections),
            selected_card_id=self._selected_card(cards, selected_node_id),
        )

    def _edge_maps(
        self,
        snapshot: GraphSnapshot,
    ) -> tuple[dict[str, list[GraphNode]], dict[str, list[GraphNode]], dict[str, list[str]], dict[str, list[str]]]:
        produced_by_agent: dict[str, list[GraphNode]] = defaultdict(list)
        requests_by_agent: dict[str, list[GraphNode]] = defaultdict(list)
        assigned_by_task: dict[str, list[str]] = defaultdict(list)
        blockers_by_task: dict[str, list[str]] = defaultdict(list)
        for edge in snapshot.edges:
            if edge.kind == EdgeKind.PRODUCED and edge.source in snapshot.nodes and edge.target in snapshot.nodes:
                produced_by_agent[edge.source].append(snapshot.nodes[edge.target])
            if edge.kind == EdgeKind.ROUTED_TO and edge.source in snapshot.nodes and edge.target in snapshot.nodes:
                requests_by_agent[edge.target].append(snapshot.nodes[edge.source])
            if edge.kind == EdgeKind.ASSIGNED:
                assigned_by_task[edge.source].append(edge.target)
            if edge.kind == EdgeKind.BLOCKED_BY:
                blockers_by_task[edge.target].append(edge.source)
        for mapping in (produced_by_agent, requests_by_agent):
            for key, nodes in mapping.items():
                mapping[key] = sorted(nodes, key=self._node_sort_key)
        return produced_by_agent, requests_by_agent, assigned_by_task, blockers_by_task

    def _timeline_by_source(self, events: list[TimelineEvent]) -> dict[str, list[TimelineEvent]]:
        grouped: dict[str, list[TimelineEvent]] = defaultdict(list)
        for event in events:
            if event.source_node_id:
                grouped[event.source_node_id].append(event)
        for key, items in grouped.items():
            grouped[key] = sorted(items, key=lambda item: (item.timestamp or "", item.id))
        return grouped

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
        status_order = {"in_progress": 0, "pending": 1, "configured": 2, "completed": 3}
        return sorted(
            (
                node
                for node in snapshot.nodes.values()
                if node.kind == NodeKind.TASK and node.cluster == team_name
            ),
            key=lambda item: (status_order.get(item.status or "", 99), item.label),
        )

    def _request_card(
        self,
        snapshot: GraphSnapshot,
        team_name: str,
        lead_requests: list[GraphNode],
        cards: list[BoardCard],
    ) -> BoardCard | None:
        team_requests = sorted(
            (
                node
                for node in snapshot.nodes.values()
                if node.kind == NodeKind.USER_REQUEST and node.cluster == team_name
            ),
            key=self._node_sort_key,
        )
        visible = team_requests[-self.request_limit :]
        if not visible:
            visible = lead_requests[-self.request_limit :]
        if not visible:
            return None
        card = self._new_card(
            lane="requests",
            title="Recent user requests",
            subtitle=f"{len(visible)} visible",
            body_lines=[node.label for node in visible],
            node_ids={node.id for node in visible},
        )
        cards.append(card)
        return card

    def _lead_card(
        self,
        lead: GraphNode | None,
        lead_turns: list[GraphNode],
        tasks: list[GraphNode],
        workers: list[GraphNode],
        cards: list[BoardCard],
    ) -> BoardCard | None:
        if lead is None:
            return None
        active_tasks = sum(1 for task in tasks if task.status in {"pending", "in_progress"})
        recent_turn = lead_turns[-1].label if lead_turns else "No recent lead output."
        card = self._new_card(
            lane="lead",
            title=lead.label,
            subtitle=self._agent_subtitle(lead),
            body_lines=[
                f"workers: {len(workers)}",
                f"active tasks: {active_tasks}",
                recent_turn,
            ],
            node_ids={lead.id} | {turn.id for turn in lead_turns[-self.summary_limit :]},
        )
        cards.append(card)
        return card

    def _worker_card(self, worker: GraphNode, turns: list[GraphNode], cards: list[BoardCard]) -> BoardCard:
        recent = turns[-1].label if turns else "Waiting for activity."
        card = self._new_card(
            lane="workers",
            title=worker.label,
            subtitle=self._agent_subtitle(worker),
            body_lines=[recent],
            node_ids={worker.id},
        )
        cards.append(card)
        return card

    def _summary_card(
        self,
        worker: GraphNode,
        turns: list[GraphNode],
        events: list[TimelineEvent],
        cards: list[BoardCard],
    ) -> BoardCard | None:
        detail = None
        detail_node_ids: set[str] = set()
        mailbox_events = [event for event in events if event.kind == "mailbox_message"]
        if mailbox_events:
            latest = mailbox_events[-1]
            detail = latest.detail or latest.title
            if latest.source_node_id:
                detail_node_ids.add(latest.source_node_id)
        elif turns:
            detail = turns[-1].label
            detail_node_ids.add(turns[-1].id)

        if not detail:
            return None

        card = self._new_card(
            lane="summaries",
            title=f"Latest from {worker.label}",
            subtitle="report",
            body_lines=[detail],
            node_ids=detail_node_ids,
        )
        cards.append(card)
        return card

    def _task_card(
        self,
        task: GraphNode,
        assignees: list[GraphNode],
        blocker_ids: list[str],
        snapshot: GraphSnapshot,
        cards: list[BoardCard],
    ) -> BoardCard:
        blockers = [
            snapshot.nodes[node_id].label
            for node_id in blocker_ids
            if node_id in snapshot.nodes
        ]
        assignee_names = [agent.label for agent in assignees]
        body_lines = []
        if assignee_names:
            body_lines.append("assignee: " + ", ".join(sorted(assignee_names)))
        if blockers:
            body_lines.append("blocked by: " + ", ".join(sorted(blockers)))
        description = str(task.metadata.get("description", "")).strip()
        if description:
            body_lines.append(description)
        card = self._new_card(
            lane="tasks",
            title=str(task.metadata.get("subject") or task.label),
            subtitle=task.status or "unknown",
            body_lines=body_lines or ["No task details."],
            node_ids={task.id},
        )
        cards.append(card)
        return card

    def _new_card(
        self,
        lane: str,
        title: str,
        subtitle: str | None,
        body_lines: list[str],
        node_ids: set[str],
    ) -> BoardCard:
        prefix = LANE_PREFIXES[lane]
        self._counters[prefix] += 1
        return BoardCard(
            card_id=f"{prefix}{self._counters[prefix]}",
            lane=lane,
            title=title,
            subtitle=subtitle,
            body_lines=body_lines,
            node_ids=node_ids,
        )

    def _agent_subtitle(self, agent: GraphNode) -> str:
        parts = []
        if agent.status:
            parts.append(agent.status)
        model = str(agent.metadata.get("model", "")).strip()
        if model:
            parts.append(model)
        return " | ".join(parts) if parts else "agent"

    def _selected_card(self, cards: list[BoardCard], selected_node_id: str | None) -> str | None:
        if not selected_node_id:
            return None
        for card in cards:
            if selected_node_id in card.node_ids:
                return card.card_id
        return None

    def _dedupe_connections(self, connections: list[BoardConnection]) -> list[BoardConnection]:
        seen: set[tuple[str, str, str, str]] = set()
        unique: list[BoardConnection] = []
        for connection in connections:
            key = (connection.source_id, connection.target_id, connection.kind, connection.label)
            if key in seen:
                continue
            seen.add(key)
            unique.append(connection)
        return unique

    def _is_lead(self, agent: GraphNode) -> bool:
        return agent.label == "team-lead" or agent.metadata.get("agent_type") == "team-lead"

    def _node_sort_key(self, node: GraphNode) -> tuple[str, str]:
        return (node.timestamp or "", node.id)

    def _first_assignee_id(self, task_id: str, assigned_by_task: dict[str, list[str]]) -> str | None:
        assignees = assigned_by_task.get(task_id, [])
        return assignees[0] if assignees else None
