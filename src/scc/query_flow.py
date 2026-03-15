from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from scc.board import BoardCard, BoardMilestone
from scc.domain import EdgeKind, GraphNode, GraphSnapshot, NodeKind, TimelineEvent


@dataclass(slots=True)
class WorkerFlow:
    card: BoardCard
    completed: bool = False


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
        request_body = self._request_detail(snapshot, request)
        request_card = self._new_card(
            lane="requests",
            card_id=section_id,
            title="You",
            subtitle=request.timestamp[11:19] if request.timestamp else "request",
            body_lines=[request_body] if request_body else ["User request"],
            node_ids={request.id},
        )
        cards.append(request_card)

        lead_turns = self._lead_turns(snapshot, primary, request.timestamp, window_end) if primary is not None else []
        worker_flows = self._worker_flows(
            snapshot=snapshot,
            request=request,
            window_end=window_end,
            primary=primary,
            cards=cards,
        )
        final_turn = self._final_turn(lead_turns)
        lead_card = None
        if primary is not None:
            has_swarm_activity = bool(worker_flows)
            lead_card = self._new_card(
                lane="lead",
                title=primary.label,
                subtitle=self._agent_subtitle(primary),
                body_lines=self._lead_body_lines(
                    request=request,
                    lead_turns=lead_turns,
                    worker_flows=worker_flows,
                    final_turn=final_turn,
                ),
                node_ids={primary.id} | {turn.id for turn in lead_turns[-self.summary_limit :]},
                max_body_lines=8 if has_swarm_activity else 4,
            )
            cards.append(lead_card)

        final_card = self._final_card(final_turn, cards)
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
            task_title = "Delegated task"
            task_subtitle = "delegated"
            task_node_ids: set[str] = set()
            task_node = tasks_by_worker.get(worker.id)
            if task_node is not None:
                task_title = str(task_node.metadata.get("subject") or task_node.label)
                task_subtitle = task_node.status or "active"
                task_node_ids = {task_node.id}
            elif synthetic_index < len(agent_tasks):
                task_turn = agent_tasks[synthetic_index]
                synthetic_index += 1
                task_title = task_turn.label.split("Agent: ", 1)[1].strip()
                task_subtitle = "delegated"
                task_node_ids = {task_turn.id}

            summary_text = worker_summaries.get(worker.id)
            worker_node_ids = task_node_ids | {worker.id} | self._worker_turn_ids(
                snapshot,
                worker,
                request.timestamp,
                window_end,
            )
            flow_card = self._new_card(
                lane="workers",
                title=task_title,
                subtitle=task_subtitle,
                body_lines=[
                    self._display_worker_label(worker.label, len(flows) + 1),
                    self._agent_subtitle(worker),
                ],
                node_ids=worker_node_ids,
                max_body_lines=2,
                progress_lines=self._worker_progress_lines(
                    snapshot,
                    worker,
                    request.timestamp,
                    window_end,
                    summary_text=summary_text,
                ),
                milestones=self._worker_milestones(
                    snapshot,
                    worker,
                    request.timestamp,
                    window_end,
                    summary_text=summary_text,
                ),
                preferred_node_id=worker.id,
            )
            cards.append(flow_card)

            flows.append(WorkerFlow(card=flow_card, completed=bool(summary_text)))

        while synthetic_index < len(agent_tasks):
            task_turn = agent_tasks[synthetic_index]
            synthetic_index += 1
            flow_card = self._new_card(
                lane="workers",
                title=task_turn.label.split("Agent: ", 1)[1].strip(),
                subtitle="delegated",
                body_lines=["Awaiting worker", "pending"],
                node_ids={task_turn.id},
                max_body_lines=2,
                progress_lines=["Waiting for worker activity."],
            )
            cards.append(flow_card)
            flows.append(WorkerFlow(card=flow_card))

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

        for event in snapshot.sorted_timeline():
            if (
                event.source_node_id not in snapshot.nodes
                or event.kind not in {"agent_progress", "hook_progress"}
                or not self._in_window(event.timestamp, window_start, window_end)
            ):
                continue
            worker = snapshot.nodes[event.source_node_id]
            if worker.kind != NodeKind.AGENT:
                continue
            if primary is not None and worker.id == primary.id:
                continue
            first_seen[worker.id] = min(first_seen.get(worker.id, event.timestamp or "~"), event.timestamp or "~")

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

    def _worker_turn_ids(
        self,
        snapshot: GraphSnapshot,
        worker: GraphNode,
        window_start: str | None,
        window_end: str | None,
    ) -> set[str]:
        node_ids: set[str] = set()
        for edge in snapshot.edges:
            if edge.kind != EdgeKind.PRODUCED or edge.source != worker.id or edge.target not in snapshot.nodes:
                continue
            turn = snapshot.nodes[edge.target]
            if turn.kind == NodeKind.MODEL_TURN and self._in_window(turn.timestamp, window_start, window_end):
                node_ids.add(turn.id)
        return node_ids

    def _worker_progress_lines(
        self,
        snapshot: GraphSnapshot,
        worker: GraphNode,
        window_start: str | None,
        window_end: str | None,
        summary_text: str | None,
        limit: int = 12,
    ) -> list[str]:
        entries: list[tuple[str, str, str]] = []
        for event in snapshot.sorted_timeline():
            if (
                event.source_node_id != worker.id
                or event.kind not in {"agent_progress", "hook_progress", "mailbox_message"}
                or not self._in_window(event.timestamp, window_start, window_end)
            ):
                continue
            detail = self._summarize_text(event.detail or event.title)
            if not detail:
                continue
            stamp = (event.timestamp or "--------")[11:19] if event.timestamp else "--------"
            entries.append((event.timestamp or "", event.id, f"{stamp}  {detail}"))

        for edge in snapshot.edges:
            if edge.kind != EdgeKind.PRODUCED or edge.source != worker.id or edge.target not in snapshot.nodes:
                continue
            turn = snapshot.nodes[edge.target]
            if turn.kind != NodeKind.MODEL_TURN or not self._in_window(turn.timestamp, window_start, window_end):
                continue
            detail = self._summarize_text(str(turn.metadata.get("raw_text") or turn.label).strip())
            if not detail:
                continue
            stamp = (turn.timestamp or "--------")[11:19] if turn.timestamp else "--------"
            entries.append((turn.timestamp or "", turn.id, f"{stamp}  {detail}"))

        entries.sort()
        lines: list[str] = []
        for _timestamp, _key, line in entries:
            if not lines or lines[-1] != line:
                lines.append(line)

        if summary_text:
            summary_line = self._summarize_text(summary_text)
            if summary_line:
                done_line = f"done  {summary_line}"
                if (not lines or lines[-1] != done_line) and (
                    not lines or not lines[-1].endswith(summary_line)
                ):
                    lines.append(done_line)

        return lines[-limit:] or ["Waiting for worker activity."]

    def _worker_milestones(
        self,
        snapshot: GraphSnapshot,
        worker: GraphNode,
        window_start: str | None,
        window_end: str | None,
        summary_text: str | None,
        limit: int = 4,
    ) -> list[BoardMilestone]:
        milestones: list[tuple[str, str, BoardMilestone]] = []
        for event in snapshot.sorted_timeline():
            if (
                event.source_node_id != worker.id
                or event.kind not in {"agent_progress", "hook_progress", "mailbox_message"}
                or not self._in_window(event.timestamp, window_start, window_end)
            ):
                continue
            milestone = self._milestone_for_event(event)
            if milestone is None:
                continue
            sort_key = event.timestamp or ""
            dedupe_key = "|".join(
                [
                    milestone.kind,
                    milestone.title,
                    milestone.subtitle or "",
                    milestone.timestamp or "",
                ]
            )
            milestones.append((sort_key, dedupe_key, milestone))

        if summary_text:
            summary = self._summarize_text(summary_text)
            if summary:
                milestones.append(
                    (
                        "~",
                        f"complete|{summary}",
                        BoardMilestone(
                            kind="complete",
                            title="Summary delivered",
                            subtitle=summary,
                            timestamp="done",
                        ),
                    )
                )

        milestones.sort(key=lambda item: item[0])
        selected: list[BoardMilestone] = []
        seen: set[str] = set()
        for _sort_key, dedupe_key, milestone in milestones:
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            selected.append(milestone)

        return selected[-limit:]

    def _milestone_for_event(self, event: TimelineEvent) -> BoardMilestone | None:
        stamp = (event.timestamp or "--------")[11:19] if event.timestamp else None
        detail = self._summarize_text(event.detail or event.title)
        if event.kind == "mailbox_message":
            return BoardMilestone(
                kind="report",
                title="Reported to lead",
                subtitle=detail or None,
                timestamp=stamp,
            )
        if event.kind == "hook_progress" and detail:
            return BoardMilestone(
                kind="hook",
                title=detail,
                timestamp=stamp,
            )
        if event.kind != "agent_progress":
            return None

        message_type = str(event.metadata.get("progress_message_type") or "").strip()
        if message_type == "user":
            return BoardMilestone(
                kind="assignment",
                title="Task received",
                timestamp=stamp,
            )
        if detail:
            return BoardMilestone(
                kind="progress",
                title=detail,
                timestamp=stamp,
            )
        return None

    def _final_turn(self, lead_turns: list[GraphNode]) -> GraphNode | None:
        visible = [turn for turn in lead_turns if not turn.label.startswith("Agent: ")]
        return visible[-1] if visible else None

    def _final_card(
        self,
        final_turn: GraphNode | None,
        cards: list[BoardCard],
    ) -> BoardCard | None:
        if final_turn is None:
            return None
        card = self._new_card(
            lane="final",
            title="Claude Code",
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
        max_body_lines: int = 5,
        progress_lines: list[str] | None = None,
        preferred_node_id: str | None = None,
        milestones: list[BoardMilestone] | None = None,
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
            max_body_lines=max_body_lines,
            progress_lines=list(progress_lines or []),
            preferred_node_id=preferred_node_id,
            milestones=list(milestones or []),
        )

    def _agent_subtitle(self, agent: GraphNode) -> str:
        parts = []
        if agent.status:
            parts.append(agent.status)
        model = str(agent.metadata.get("model", "")).strip()
        if model:
            parts.append(model)
        return " | ".join(parts) if parts else "agent"

    def _lead_body_lines(
        self,
        request: GraphNode,
        lead_turns: list[GraphNode],
        worker_flows: list[WorkerFlow],
        final_turn: GraphNode | None,
    ) -> list[str]:
        lines = [f"window: {request.timestamp[11:19] if request.timestamp else '---'}"]
        delegated = len(worker_flows)
        if delegated:
            noun = "worker" if delegated == 1 else "workers"
            lines.append(f"delegated to {delegated} {noun}")
            completed = sum(1 for flow in worker_flows if flow.completed)
            lines.append(f"reports: {completed}/{delegated}")
            lines.extend(self._lead_activity_lines(lead_turns, final_turn, max_items=3))
        else:
            lines.append("working directly on this request")

        visible_turns = [turn for turn in lead_turns if not turn.label.startswith("Agent: ")]
        if final_turn is not None and len(visible_turns) > 1 and not delegated:
            lines.append(visible_turns[-2].label)
        elif final_turn is not None:
            lines.append("response delivered")
        elif visible_turns and not delegated:
            lines.append(visible_turns[-1].label)
        elif any(turn.label.startswith("Agent: ") for turn in lead_turns) and not delegated:
            lines.append("delegated work launched")
        elif not delegated:
            lines.append("awaiting activity")
        return lines

    def _lead_activity_lines(
        self,
        lead_turns: list[GraphNode],
        final_turn: GraphNode | None,
        max_items: int,
    ) -> list[str]:
        activity: list[str] = []
        for turn in lead_turns:
            if final_turn is not None and turn.id == final_turn.id:
                continue
            if turn.label.startswith("Agent: "):
                activity.append(f"spawned {turn.label.split('Agent: ', 1)[1].strip()}")
                continue

            detail = str(turn.metadata.get("raw_text") or turn.label).strip()
            if not detail:
                continue
            summary = self._summarize_text(detail)
            if summary and summary not in activity:
                activity.append(summary)

        return activity[-max_items:]

    def _summarize_text(self, text: str, fallback: str = "") -> str:
        normalized = " ".join(text.split()).strip()
        if not normalized:
            return fallback
        if normalized in {"Read", "Bash", "Glob", "Task", "TaskList", "Assistant response"}:
            return fallback
        if len(normalized) <= 72:
            return normalized
        return normalized[:69].rstrip() + "..."

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
