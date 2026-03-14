from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from scc.board import BoardCard
from scc.domain import EdgeKind, GraphNode, GraphSnapshot, NodeKind, TimelineEvent


@dataclass(slots=True)
class WorkerFlow:
    task_card: BoardCard | None = None
    worker_card: BoardCard | None = None
    summary_card: BoardCard | None = None


@dataclass(slots=True)
class QuerySection:
    section_id: str
    request_card: BoardCard
    lead_card: BoardCard | None
    worker_flows: list[WorkerFlow] = field(default_factory=list)
    final_card: BoardCard | None = None


@dataclass(slots=True)
class QueryFlowModel:
    title: str
    sections: list[QuerySection]
    selected_card_id: str | None


class QueryFlowBuilder:
    def __init__(self, request_limit: int = 10, summary_limit: int = 3) -> None:
        self.request_limit = request_limit
        self.summary_limit = summary_limit
        self._counters: dict[str, int] = defaultdict(int)

    def build(
        self,
        snapshot: GraphSnapshot,
        selected_node_id: str | None = None,
    ) -> QueryFlowModel:
        self._counters.clear()
        requests = self._section_requests(snapshot)
        primary = self._primary_agent(snapshot)
        all_cards: list[BoardCard] = []

        if not requests:
            section = self._fallback_section(snapshot, primary, all_cards)
            return QueryFlowModel(
                title=self._title(snapshot),
                sections=[section] if section else [],
                selected_card_id=self._selected_card_id(all_cards, selected_node_id),
            )

        sections: list[QuerySection] = []
        for index, request in enumerate(requests):
            next_request = requests[index + 1] if index + 1 < len(requests) else None
            section = self._build_section(
                snapshot=snapshot,
                section_index=index + 1,
                request=request,
                primary=primary,
                window_end=next_request.timestamp if next_request else None,
                cards=all_cards,
            )
            sections.append(section)

        return QueryFlowModel(
            title=self._title(snapshot),
            sections=sections,
            selected_card_id=self._selected_card_id(all_cards, selected_node_id),
        )

    def _section_requests(self, snapshot: GraphSnapshot) -> list[GraphNode]:
        requests = [
            node
            for node in snapshot.nodes.values()
            if node.kind == NodeKind.USER_REQUEST
        ]
        primary = [
            node
            for node in requests
            if not node.metadata.get("is_sidechain")
            and str(node.metadata.get("speaker") or "You") == "You"
        ]
        visible = primary or [
            node
            for node in requests
            if not node.metadata.get("is_sidechain")
        ] or requests
        return sorted(visible, key=self._node_sort_key)[-self.request_limit :]

    def _build_section(
        self,
        snapshot: GraphSnapshot,
        section_index: int,
        request: GraphNode,
        primary: GraphNode | None,
        window_end: str | None,
        cards: list[BoardCard],
    ) -> QuerySection:
        section_id = f"Q{section_index}"
        request_card = self._new_card(
            lane="requests",
            card_id=section_id,
            title=request.label,
            subtitle=request.timestamp[11:19] if request.timestamp else "request",
            body_lines=[self._request_detail(snapshot, request)],
            node_ids={request.id},
        )
        cards.append(request_card)

        lead_card = None
        if primary is not None:
            lead_turns = self._lead_turns(snapshot, primary, request.timestamp, window_end)
            lead_card = self._new_card(
                lane="lead",
                title=primary.label,
                subtitle=self._agent_subtitle(primary),
                body_lines=[
                    f"window: {request.timestamp[11:19] if request.timestamp else '---'}",
                    self._summarize_turns(lead_turns),
                ],
                node_ids={primary.id} | {turn.id for turn in lead_turns[-self.summary_limit :]},
            )
            cards.append(lead_card)

        worker_flows = self._worker_flows(
            snapshot=snapshot,
            request=request,
            window_end=window_end,
            primary=primary,
            cards=cards,
        )
        final_card = self._final_card(snapshot, request, window_end, primary, cards)
        return QuerySection(
            section_id=section_id,
            request_card=request_card,
            lead_card=lead_card,
            worker_flows=worker_flows,
            final_card=final_card,
        )

    def _fallback_section(
        self,
        snapshot: GraphSnapshot,
        primary: GraphNode | None,
        cards: list[BoardCard],
    ) -> QuerySection | None:
        if primary is None:
            return None
        request_card = self._new_card(
            lane="requests",
            card_id="Q1",
            title="Current swarm",
            subtitle="live state",
            body_lines=["No user request is available in the current focus."],
            node_ids=set(),
        )
        cards.append(request_card)
        lead_card = self._new_card(
            lane="lead",
            title=primary.label,
            subtitle=self._agent_subtitle(primary),
            body_lines=["Current visible state"],
            node_ids={primary.id},
        )
        cards.append(lead_card)
        return QuerySection(section_id="Q1", request_card=request_card, lead_card=lead_card)

    def _worker_flows(
        self,
        snapshot: GraphSnapshot,
        request: GraphNode,
        window_end: str | None,
        primary: GraphNode | None,
        cards: list[BoardCard],
    ) -> list[WorkerFlow]:
        agent_tasks = self._synthetic_agent_tasks(snapshot, request.timestamp, window_end)
        workers = self._active_workers(snapshot, request.timestamp, window_end, primary)
        tasks_by_worker = self._real_tasks_by_worker(snapshot, workers, request.timestamp, window_end)
        worker_summaries = self._worker_summaries(snapshot, workers, request.timestamp, window_end)

        flows: list[WorkerFlow] = []
        synthetic_index = 0
        for worker in workers:
            task_card = None
            task_node = tasks_by_worker.get(worker.id)
            if task_node is not None:
                task_card = self._new_card(
                    lane="tasks",
                    title=str(task_node.metadata.get("subject") or task_node.label),
                    subtitle=task_node.status or "active",
                    body_lines=[str(task_node.metadata.get("description") or "Assigned task")],
                    node_ids={task_node.id},
                )
                cards.append(task_card)
            elif synthetic_index < len(agent_tasks):
                task_turn = agent_tasks[synthetic_index]
                synthetic_index += 1
                task_card = self._new_card(
                    lane="tasks",
                    title=task_turn.label.split("Agent: ", 1)[1].strip(),
                    subtitle="delegated",
                    body_lines=["Spawned from this request"],
                    node_ids={task_turn.id},
                )
                cards.append(task_card)

            worker_card = self._new_card(
                lane="workers",
                title=self._display_worker_label(worker.label, len(flows) + 1),
                subtitle=self._agent_subtitle(worker),
                body_lines=[worker_summaries.get(worker.id, "Waiting for progress.")],
                node_ids={worker.id},
            )
            cards.append(worker_card)

            summary_card = None
            summary_text = worker_summaries.get(worker.id)
            if summary_text:
                summary_card = self._new_card(
                    lane="summaries",
                    title="Progress",
                    subtitle="latest worker output",
                    body_lines=[summary_text],
                    node_ids={worker.id},
                )
                cards.append(summary_card)

            flows.append(WorkerFlow(task_card=task_card, worker_card=worker_card, summary_card=summary_card))

        while synthetic_index < len(agent_tasks):
            task_turn = agent_tasks[synthetic_index]
            synthetic_index += 1
            task_card = self._new_card(
                lane="tasks",
                title=task_turn.label.split("Agent: ", 1)[1].strip(),
                subtitle="delegated",
                body_lines=["Spawned from this request"],
                node_ids={task_turn.id},
            )
            cards.append(task_card)
            flows.append(WorkerFlow(task_card=task_card))

        return flows

    def _lead_turns(
        self,
        snapshot: GraphSnapshot,
        primary: GraphNode,
        window_start: str | None,
        window_end: str | None,
    ) -> list[GraphNode]:
        produced = [
            snapshot.nodes[edge.target]
            for edge in snapshot.edges
            if edge.kind == EdgeKind.PRODUCED
            and edge.source == primary.id
            and edge.target in snapshot.nodes
            and snapshot.nodes[edge.target].kind == NodeKind.MODEL_TURN
            and self._in_window(snapshot.nodes[edge.target].timestamp, window_start, window_end)
        ]
        return sorted(produced, key=self._node_sort_key)

    def _synthetic_agent_tasks(
        self,
        snapshot: GraphSnapshot,
        window_start: str | None,
        window_end: str | None,
    ) -> list[GraphNode]:
        tasks = [
            node
            for node in snapshot.nodes.values()
            if node.kind == NodeKind.MODEL_TURN
            and node.label.startswith("Agent: ")
            and self._in_window(node.timestamp, window_start, window_end)
        ]
        return sorted(tasks, key=self._node_sort_key)

    def _active_workers(
        self,
        snapshot: GraphSnapshot,
        window_start: str | None,
        window_end: str | None,
        primary: GraphNode | None,
    ) -> list[GraphNode]:
        first_seen: dict[str, str] = {}
        for edge in snapshot.edges:
            if edge.kind != EdgeKind.PRODUCED or edge.source not in snapshot.nodes or edge.target not in snapshot.nodes:
                continue
            worker = snapshot.nodes[edge.source]
            turn = snapshot.nodes[edge.target]
            if worker.kind != NodeKind.AGENT or turn.kind != NodeKind.MODEL_TURN:
                continue
            if primary is not None and worker.id == primary.id:
                continue
            if not self._in_window(turn.timestamp, window_start, window_end):
                continue
            first_seen[worker.id] = min(first_seen.get(worker.id, turn.timestamp or "~"), turn.timestamp or "~")

        ordered_ids = sorted(first_seen, key=lambda node_id: (first_seen[node_id], snapshot.nodes[node_id].label))
        return [snapshot.nodes[node_id] for node_id in ordered_ids]

    def _real_tasks_by_worker(
        self,
        snapshot: GraphSnapshot,
        workers: list[GraphNode],
        window_start: str | None,
        window_end: str | None,
    ) -> dict[str, GraphNode]:
        active_workers = {worker.id for worker in workers}
        events_by_worker = {
            event.source_node_id
            for event in snapshot.timeline
            if event.kind == "task_assignment"
            and event.source_node_id in active_workers
            and self._in_window(event.timestamp, window_start, window_end)
        }
        tasks_by_worker: dict[str, GraphNode] = {}
        for edge in snapshot.edges:
            if edge.kind != EdgeKind.ASSIGNED or edge.source not in snapshot.nodes or edge.target not in snapshot.nodes:
                continue
            if edge.target not in active_workers:
                continue
            task = snapshot.nodes[edge.source]
            if task.kind != NodeKind.TASK:
                continue
            if events_by_worker and edge.target not in events_by_worker:
                continue
            tasks_by_worker.setdefault(edge.target, task)
        return tasks_by_worker

    def _worker_summaries(
        self,
        snapshot: GraphSnapshot,
        workers: list[GraphNode],
        window_start: str | None,
        window_end: str | None,
    ) -> dict[str, str]:
        summaries: dict[str, str] = {}
        for worker in workers:
            latest_turn = None
            for edge in snapshot.edges:
                if edge.kind != EdgeKind.PRODUCED or edge.source != worker.id or edge.target not in snapshot.nodes:
                    continue
                turn = snapshot.nodes[edge.target]
                if turn.kind != NodeKind.MODEL_TURN or not self._in_window(turn.timestamp, window_start, window_end):
                    continue
                latest_turn = turn
            if latest_turn is not None:
                summaries[worker.id] = latest_turn.label
                continue

            mailbox = [
                event.detail or event.title
                for event in snapshot.timeline
                if event.kind == "mailbox_message"
                and event.source_node_id == worker.id
                and self._in_window(event.timestamp, window_start, window_end)
            ]
            if mailbox:
                summaries[worker.id] = mailbox[-1]
        return summaries

    def _final_card(
        self,
        snapshot: GraphSnapshot,
        request: GraphNode,
        window_end: str | None,
        primary: GraphNode | None,
        cards: list[BoardCard],
    ) -> BoardCard | None:
        if primary is None:
            return None
        lead_turns = [
            turn
            for turn in self._lead_turns(snapshot, primary, request.timestamp, window_end)
            if not turn.label.startswith("Agent: ")
        ]
        if not lead_turns:
            return None
        final_turn = lead_turns[-1]
        card = self._new_card(
            lane="final",
            title="Final response",
            subtitle=final_turn.timestamp[11:19] if final_turn.timestamp else "response",
            body_lines=[str(final_turn.metadata.get("raw_text") or final_turn.label)],
            node_ids={final_turn.id},
        )
        cards.append(card)
        return card

    def _primary_agent(self, snapshot: GraphSnapshot) -> GraphNode | None:
        teams = sorted(
            (node for node in snapshot.nodes.values() if node.kind == NodeKind.TEAM),
            key=lambda item: item.label,
        )
        if teams:
            team = teams[0]
            agents = [
                node
                for node in snapshot.nodes.values()
                if node.kind == NodeKind.AGENT and node.cluster == team.label
            ]
            lead = next((agent for agent in agents if agent.label == "team-lead" or agent.metadata.get("agent_type") == "team-lead"), None)
            return lead or (sorted(agents, key=lambda item: item.label)[0] if agents else None)

        session_ids = sorted({node.session_id for node in snapshot.nodes.values() if node.session_id})
        if not session_ids:
            return None
        session_id = session_ids[0]
        preferred_id = f"agent:session:{session_id}"
        if preferred_id in snapshot.nodes:
            return snapshot.nodes[preferred_id]
        agents = [
            node
            for node in snapshot.nodes.values()
            if node.kind == NodeKind.AGENT and node.session_id == session_id
        ]
        return sorted(agents, key=lambda item: item.label)[0] if agents else None

    def _request_detail(self, snapshot: GraphSnapshot, request: GraphNode) -> str:
        return str(request.metadata.get("raw_text") or request.label)

    def _title(self, snapshot: GraphSnapshot) -> str:
        teams = sorted(
            (node for node in snapshot.nodes.values() if node.kind == NodeKind.TEAM),
            key=lambda item: item.label,
        )
        if teams:
            return f"{teams[0].label} query flow"
        session_ids = sorted({node.session_id for node in snapshot.nodes.values() if node.session_id})
        if session_ids:
            return f"session {session_ids[0][:8]} query flow"
        return "query flow"

    def _selected_card_id(self, cards: list[BoardCard], selected_node_id: str | None) -> str | None:
        if not selected_node_id:
            return None
        for card in cards:
            if selected_node_id in card.node_ids:
                return card.card_id
        return None

    def _new_card(
        self,
        lane: str,
        title: str,
        subtitle: str | None,
        body_lines: list[str],
        node_ids: set[str],
        card_id: str | None = None,
    ) -> BoardCard:
        if card_id is None:
            prefix = {
                "requests": "Q",
                "lead": "L",
                "tasks": "T",
                "workers": "W",
                "summaries": "S",
                "final": "F",
            }.get(lane, "C")
            self._counters[prefix] += 1
            card_id = f"{prefix}{self._counters[prefix]}"
        return BoardCard(
            card_id=card_id,
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

    def _summarize_turns(self, turns: list[GraphNode]) -> str:
        visible = [turn.label for turn in turns if not turn.label.startswith("Agent: ")]
        return visible[-1] if visible else "Delegating work"

    def _display_worker_label(self, label: str, index: int) -> str:
        if label.startswith("a") and label[1:].isalnum():
            return f"Worker {index}"
        return label

    def _in_window(
        self,
        timestamp: str | None,
        window_start: str | None,
        window_end: str | None,
    ) -> bool:
        if timestamp is None:
            return False
        if window_start is not None and timestamp < window_start:
            return False
        if window_end is not None and timestamp >= window_end:
            return False
        return True

    def _node_sort_key(self, node: GraphNode) -> tuple[str, str]:
        return (node.timestamp or "", node.id)
