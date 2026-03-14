from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from scc.domain import EdgeKind, GraphEdge, GraphNode, GraphSnapshot, NodeKind, TimelineEvent

LOCAL_COMMAND_MARKERS = (
    "<local-command-caveat>",
    "<command-name>",
    "<local-command-stdout>",
)


@dataclass(slots=True)
class TeamContext:
    name: str
    node_id: str
    lead_session_id: str | None = None
    member_nodes: dict[str, str] = field(default_factory=dict)
    member_ids: dict[str, str] = field(default_factory=dict)
    assignments_by_task: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))


class ClaudeStateLoader:
    def __init__(self, claude_home: Path) -> None:
        self.claude_home = claude_home.expanduser()
        self._teams: dict[str, TeamContext] = {}
        self._session_agents: dict[str, str] = {}

    def load(self) -> GraphSnapshot:
        snapshot = GraphSnapshot()
        self._load_teams(snapshot)
        self._load_inboxes(snapshot)
        self._load_tasks(snapshot)
        self._load_projects(snapshot)
        return snapshot

    def _load_teams(self, snapshot: GraphSnapshot) -> None:
        teams_dir = self.claude_home / "teams"
        for config_path in sorted(teams_dir.glob("*/config.json")):
            team_name = config_path.parent.name
            try:
                payload = json.loads(config_path.read_text())
            except (OSError, json.JSONDecodeError) as error:
                snapshot.warnings.append(f"failed to read {config_path}: {error}")
                continue

            team = self._ensure_team(
                snapshot,
                team_name=team_name,
                session_id=payload.get("leadSessionId"),
                metadata={
                    "description": payload.get("description"),
                    "created_at": payload.get("createdAt"),
                    "lead_agent_id": payload.get("leadAgentId"),
                },
            )
            team.lead_session_id = payload.get("leadSessionId")

            for member in payload.get("members", []):
                member_name = member.get("name") or str(member.get("agentId", "agent")).split("@")[0]
                agent_node_id = self._ensure_named_agent(
                    snapshot,
                    team_name=team_name,
                    agent_name=member_name,
                    agent_id=member.get("agentId"),
                    label=member_name,
                    status="configured",
                    metadata={
                        "agent_type": member.get("agentType"),
                        "model": member.get("model"),
                        "backend_type": member.get("backendType"),
                        "cwd": member.get("cwd"),
                        "tmux_pane_id": member.get("tmuxPaneId"),
                    },
                )
                snapshot.add_edge(
                    GraphEdge(
                        source=team.node_id,
                        target=agent_node_id,
                        kind=EdgeKind.CONTAINS,
                    )
                )

    def _load_inboxes(self, snapshot: GraphSnapshot) -> None:
        for inbox_path in sorted(self.claude_home.glob("teams/*/inboxes/*.json")):
            team_name = inbox_path.parent.parent.name
            agent_name = inbox_path.stem
            agent_node_id = self._ensure_named_agent(
                snapshot,
                team_name=team_name,
                agent_name=agent_name,
                label=agent_name,
            )
            try:
                messages = json.loads(inbox_path.read_text())
            except (OSError, json.JSONDecodeError) as error:
                snapshot.warnings.append(f"failed to read {inbox_path}: {error}")
                continue

            for index, item in enumerate(messages):
                payload = self._parse_json_text(item.get("text", ""))
                timestamp = item.get("timestamp")
                sender_name = item.get("from")
                sender_node_id = None
                if sender_name:
                    sender_node_id = self._ensure_named_agent(
                        snapshot,
                        team_name=team_name,
                        agent_name=sender_name,
                        label=sender_name,
                    )

                if payload and payload.get("type") == "task_assignment":
                    task_id = str(payload.get("taskId"))
                    self._ensure_team(snapshot, team_name=team_name)
                    self._teams[team_name].assignments_by_task[task_id].add(agent_name)
                    task_node_id = f"task:{team_name}:{task_id}"
                    snapshot.upsert_node(
                        GraphNode(
                            id=task_node_id,
                            kind=NodeKind.TASK,
                            label=f"#{task_id} {payload.get('subject', 'Assigned task')}",
                            cluster=team_name,
                            status="assigned",
                        )
                    )
                    if sender_node_id:
                        snapshot.add_edge(
                            GraphEdge(
                                source=sender_node_id,
                                target=task_node_id,
                                kind=EdgeKind.DISPATCHED,
                            )
                        )
                    snapshot.add_edge(
                        GraphEdge(
                            source=task_node_id,
                            target=agent_node_id,
                            kind=EdgeKind.ASSIGNED,
                        )
                    )
                    snapshot.add_event(
                        TimelineEvent(
                            id=f"inbox:{team_name}:{agent_name}:{index}",
                            timestamp=timestamp,
                            kind="task_assignment",
                            title=f"Task #{task_id} assigned to {agent_name}",
                            detail=payload.get("subject"),
                            source_node_id=agent_node_id,
                            team=team_name,
                            metadata=payload,
                        )
                    )
                    continue

                if payload and payload.get("type") == "idle_notification":
                    snapshot.upsert_node(
                        GraphNode(
                            id=agent_node_id,
                            kind=NodeKind.AGENT,
                            label=agent_name,
                            cluster=team_name,
                            status=payload.get("idleReason", "idle"),
                            metadata={"idle_timestamp": payload.get("timestamp")},
                        )
                    )
                    snapshot.add_event(
                        TimelineEvent(
                            id=f"inbox:{team_name}:{agent_name}:{index}",
                            timestamp=timestamp,
                            kind="idle_notification",
                            title=f"{agent_name} became available",
                            source_node_id=agent_node_id,
                            team=team_name,
                            metadata=payload,
                        )
                    )
                    continue

                detail = self._summarize_text(item.get("text", ""))
                snapshot.add_event(
                    TimelineEvent(
                        id=f"inbox:{team_name}:{agent_name}:{index}",
                        timestamp=timestamp,
                        kind="mailbox_message",
                        title=f"{sender_name or 'unknown'} -> {agent_name}",
                        detail=detail,
                        source_node_id=sender_node_id or agent_node_id,
                        team=team_name,
                        metadata={"raw_text": item.get("text", "")},
                    )
                )
                if sender_node_id and sender_name != "team-lead":
                    lead_node_id = self._ensure_named_agent(
                        snapshot,
                        team_name=team_name,
                        agent_name="team-lead",
                        label="team-lead",
                    )
                    snapshot.add_edge(
                        GraphEdge(
                            source=sender_node_id,
                            target=lead_node_id,
                            kind=EdgeKind.SUMMARIZED_TO,
                        )
                    )

    def _load_tasks(self, snapshot: GraphSnapshot) -> None:
        for task_path in sorted(self.claude_home.glob("tasks/*/*.json")):
            team_name = task_path.parent.name
            task_id = task_path.stem
            self._ensure_team(snapshot, team_name=team_name)
            try:
                task = json.loads(task_path.read_text())
            except (OSError, json.JSONDecodeError) as error:
                snapshot.warnings.append(f"failed to read {task_path}: {error}")
                continue

            node_id = f"task:{team_name}:{task_id}"
            snapshot.upsert_node(
                GraphNode(
                    id=node_id,
                    kind=NodeKind.TASK,
                    label=f"#{task_id} {task.get('subject', 'Untitled task')}",
                    cluster=team_name,
                    status=task.get("status"),
                    metadata={
                        "subject": task.get("subject"),
                        "description": task.get("description"),
                        "owner": task.get("owner"),
                    },
                )
            )
            team_node = self._teams.get(team_name)
            snapshot.add_edge(
                GraphEdge(source=team_node.node_id, target=node_id, kind=EdgeKind.CONTAINS)
            )

            owner = task.get("owner")
            if owner:
                owner_node = self._ensure_named_agent(
                    snapshot,
                    team_name=team_name,
                    agent_name=owner,
                    label=owner,
                )
                snapshot.add_edge(
                    GraphEdge(source=node_id, target=owner_node, kind=EdgeKind.ASSIGNED)
                )

            for dependency in task.get("blockedBy", []):
                snapshot.add_edge(
                    GraphEdge(
                        source=f"task:{team_name}:{dependency}",
                        target=node_id,
                        kind=EdgeKind.BLOCKED_BY,
                    )
                )

    def _load_projects(self, snapshot: GraphSnapshot) -> None:
        for project_path in sorted(self.claude_home.glob("projects/**/*.jsonl")):
            if project_path.parent.name == "subagents":
                self._load_subagent_transcript(snapshot, project_path)
            else:
                self._load_main_transcript(snapshot, project_path)

    def _load_main_transcript(self, snapshot: GraphSnapshot, transcript_path: Path) -> None:
        for record in self._iter_jsonl(transcript_path):
            record_type = record.get("type")
            if record_type not in {"user", "assistant"}:
                continue

            if record_type == "user" and self._should_skip_user_record(record):
                continue

            session_id = record.get("sessionId")
            team_name = record.get("teamName")
            agent_node_id = self._agent_for_record(snapshot, record, team_hint=team_name)
            if record_type == "user":
                detail = self._detail_for_user_record(record)
                speaker = self._speaker_for_record(
                    snapshot,
                    record=record,
                    kind=NodeKind.USER_REQUEST,
                    agent_node_id=agent_node_id,
                )
                node_id = self._add_turn_node(
                    snapshot,
                    record=record,
                    kind=NodeKind.USER_REQUEST,
                    label=self._label_for_user_record(record),
                    agent_node_id=agent_node_id,
                    raw_text=detail,
                    speaker=speaker,
                )
                if agent_node_id:
                    snapshot.add_edge(
                        GraphEdge(
                            source=node_id,
                            target=agent_node_id,
                            kind=EdgeKind.ROUTED_TO,
                        )
                    )
                snapshot.add_event(
                    TimelineEvent(
                        id=f"turn:{node_id}",
                        timestamp=record.get("timestamp"),
                        kind="user_turn",
                        title=self._label_for_user_record(record),
                        detail=detail,
                        source_node_id=node_id,
                        team=team_name,
                        session_id=session_id,
                        metadata={
                            "speaker": speaker,
                            "is_sidechain": bool(record.get("isSidechain")),
                        },
                    )
                )
                continue

            label = self._label_for_assistant_record(record)
            detail = self._detail_for_assistant_record(record)
            speaker = self._speaker_for_record(
                snapshot,
                record=record,
                kind=NodeKind.MODEL_TURN,
                agent_node_id=agent_node_id,
            )
            node_id = self._add_turn_node(
                snapshot,
                record=record,
                kind=NodeKind.MODEL_TURN,
                label=label,
                agent_node_id=agent_node_id,
                raw_text=detail,
                speaker=speaker,
            )
            if agent_node_id:
                snapshot.add_edge(
                    GraphEdge(
                        source=agent_node_id,
                        target=node_id,
                        kind=EdgeKind.PRODUCED,
                    )
                )
                snapshot.add_event(
                    TimelineEvent(
                        id=f"turn:{node_id}",
                        timestamp=record.get("timestamp"),
                        kind="assistant_turn",
                        title=label,
                        detail=detail,
                        source_node_id=node_id,
                        team=team_name,
                        session_id=session_id,
                        metadata={
                            "speaker": speaker,
                            "is_sidechain": bool(record.get("isSidechain")),
                        },
                    )
                )

    def _load_subagent_transcript(self, snapshot: GraphSnapshot, transcript_path: Path) -> None:
        records = list(self._iter_jsonl(transcript_path))
        if not records:
            return

        first_record = records[0]
        team_name = self._extract_team_name(self._raw_message_text(first_record.get("message")))
        task_id = self._extract_assigned_task_id(self._raw_message_text(first_record.get("message")))
        runtime_agent_id = first_record.get("agentId")
        mapped_node_id = None
        if team_name and task_id:
            assignees = self._ensure_team(snapshot, team_name=team_name).assignments_by_task.get(
                task_id,
                set(),
            )
            if len(assignees) == 1:
                assignee = next(iter(assignees))
                mapped_node_id = self._ensure_named_agent(
                    snapshot,
                    team_name=team_name,
                    agent_name=assignee,
                    label=assignee,
                )

        if runtime_agent_id and not mapped_node_id:
            mapped_node_id = self._ensure_runtime_agent(
                snapshot,
                team_name=team_name,
                runtime_agent_id=runtime_agent_id,
                session_id=first_record.get("sessionId"),
                label=runtime_agent_id,
            )

        for record in records:
            record_type = record.get("type")
            if record_type not in {"user", "assistant"}:
                continue
            if record_type == "user" and self._should_skip_user_record(record):
                continue

            if record_type == "user":
                detail = self._detail_for_user_record(record)
                speaker = self._speaker_for_record(
                    snapshot,
                    record=record,
                    kind=NodeKind.USER_REQUEST,
                    agent_node_id=mapped_node_id,
                )
                node_id = self._add_turn_node(
                    snapshot,
                    record=record,
                    kind=NodeKind.USER_REQUEST,
                    label=self._label_for_user_record(record),
                    agent_node_id=mapped_node_id,
                    raw_text=detail,
                    speaker=speaker,
                )
                if mapped_node_id:
                    snapshot.add_edge(
                        GraphEdge(source=node_id, target=mapped_node_id, kind=EdgeKind.ROUTED_TO)
                    )
                snapshot.add_event(
                    TimelineEvent(
                        id=f"turn:{node_id}",
                        timestamp=record.get("timestamp"),
                        kind="user_turn",
                        title=self._label_for_user_record(record),
                        detail=detail,
                        source_node_id=node_id,
                        team=team_name,
                        session_id=record.get("sessionId"),
                        metadata={
                            "speaker": speaker,
                            "is_sidechain": bool(record.get("isSidechain")),
                        },
                    )
                )
            else:
                detail = self._detail_for_assistant_record(record)
                speaker = self._speaker_for_record(
                    snapshot,
                    record=record,
                    kind=NodeKind.MODEL_TURN,
                    agent_node_id=mapped_node_id,
                )
                node_id = self._add_turn_node(
                    snapshot,
                    record=record,
                    kind=NodeKind.MODEL_TURN,
                    label=self._label_for_assistant_record(record),
                    agent_node_id=mapped_node_id,
                    raw_text=detail,
                    speaker=speaker,
                )
                if mapped_node_id:
                    snapshot.add_edge(
                        GraphEdge(source=mapped_node_id, target=node_id, kind=EdgeKind.PRODUCED)
                    )
                snapshot.add_event(
                    TimelineEvent(
                        id=f"turn:{node_id}",
                        timestamp=record.get("timestamp"),
                        kind="assistant_turn",
                        title=self._label_for_assistant_record(record),
                        detail=detail,
                        source_node_id=node_id,
                        team=team_name,
                        session_id=record.get("sessionId"),
                        metadata={
                            "speaker": speaker,
                            "is_sidechain": bool(record.get("isSidechain")),
                        },
                    )
                )

    def _add_turn_node(
        self,
        snapshot: GraphSnapshot,
        record: dict[str, Any],
        kind: NodeKind,
        label: str,
        agent_node_id: str | None,
        raw_text: str | None = None,
        speaker: str | None = None,
    ) -> str:
        node_id = f"turn:{record['uuid']}"
        cluster = record.get("teamName") or self._cluster_for_agent(snapshot, agent_node_id)
        metadata = {
            "request_id": record.get("requestId"),
            "parent_uuid": record.get("parentUuid"),
            "path": str(record.get("cwd") or ""),
        }
        if raw_text:
            metadata["raw_text"] = raw_text
        if speaker:
            metadata["speaker"] = speaker
        if record.get("isSidechain"):
            metadata["is_sidechain"] = True
        snapshot.upsert_node(
            GraphNode(
                id=node_id,
                kind=kind,
                label=label,
                cluster=cluster,
                session_id=record.get("sessionId"),
                agent_id=record.get("agentId"),
                timestamp=record.get("timestamp"),
                metadata=metadata,
            )
        )
        parent_uuid = record.get("parentUuid")
        if parent_uuid:
            parent_node_id = f"turn:{parent_uuid}"
            if parent_node_id in snapshot.nodes:
                snapshot.add_edge(
                    GraphEdge(source=parent_node_id, target=node_id, kind=EdgeKind.PARENT)
                )
        return node_id

    def _agent_for_record(
        self,
        snapshot: GraphSnapshot,
        record: dict[str, Any],
        team_hint: str | None,
    ) -> str | None:
        session_id = record.get("sessionId")
        team_name = team_hint
        agent_id = record.get("agentId")

        if agent_id:
            return self._ensure_runtime_agent(
                snapshot,
                team_name=team_name,
                runtime_agent_id=agent_id,
                session_id=session_id,
                label=agent_id,
            )

        if team_name:
            self._ensure_team(snapshot, team_name=team_name)
            return self._ensure_named_agent(
                snapshot,
                team_name=team_name,
                agent_name="team-lead",
                label="team-lead",
            )

        if not session_id:
            return None

        existing = self._session_agents.get(session_id)
        if existing:
            return existing

        label = Path(str(record.get("cwd") or session_id)).name or "claude"
        node_id = f"agent:session:{session_id}"
        self._session_agents[session_id] = node_id
        snapshot.upsert_node(
            GraphNode(
                id=node_id,
                kind=NodeKind.AGENT,
                label=label,
                status="active",
                session_id=session_id,
                metadata={"cwd": record.get("cwd")},
            )
        )
        return node_id

    def _ensure_named_agent(
        self,
        snapshot: GraphSnapshot,
        team_name: str,
        agent_name: str,
        label: str,
        agent_id: str | None = None,
        status: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        team = self._ensure_team(snapshot, team_name=team_name)
        if agent_name in team.member_nodes:
            node_id = team.member_nodes[agent_name]
        else:
            node_id = f"agent:{team_name}:{agent_name}"
            team.member_nodes[agent_name] = node_id

        if agent_id:
            team.member_ids[agent_id] = node_id

        snapshot.upsert_node(
            GraphNode(
                id=node_id,
                kind=NodeKind.AGENT,
                label=label,
                cluster=team_name,
                status=status,
                agent_id=agent_id,
                metadata=metadata or {},
            )
        )
        snapshot.add_edge(
            GraphEdge(source=team.node_id, target=node_id, kind=EdgeKind.CONTAINS)
        )
        return node_id

    def _ensure_runtime_agent(
        self,
        snapshot: GraphSnapshot,
        team_name: str | None,
        runtime_agent_id: str,
        session_id: str | None,
        label: str,
    ) -> str:
        if team_name and team_name in self._teams:
            team = self._teams[team_name]
            mapped = team.member_ids.get(runtime_agent_id)
            if mapped:
                return mapped

        if team_name:
            self._ensure_team(snapshot, team_name=team_name)

        node_id = f"agent:runtime:{runtime_agent_id}"
        snapshot.upsert_node(
            GraphNode(
                id=node_id,
                kind=NodeKind.AGENT,
                label=label,
                cluster=team_name,
                status="active",
                session_id=session_id,
                agent_id=runtime_agent_id,
            )
        )
        if team_name:
            snapshot.add_edge(
                GraphEdge(source=f"team:{team_name}", target=node_id, kind=EdgeKind.CONTAINS)
            )
        return node_id

    def _ensure_team(
        self,
        snapshot: GraphSnapshot,
        team_name: str,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TeamContext:
        team = self._teams.get(team_name)
        if team is None:
            team = TeamContext(name=team_name, node_id=f"team:{team_name}")
            self._teams[team_name] = team

        snapshot.upsert_node(
            GraphNode(
                id=team.node_id,
                kind=NodeKind.TEAM,
                label=team_name,
                cluster=team_name,
                session_id=session_id,
                metadata=metadata or {},
            )
        )
        return team

    def _cluster_for_agent(self, snapshot: GraphSnapshot, agent_node_id: str | None) -> str | None:
        if not agent_node_id:
            return None
        node = snapshot.nodes.get(agent_node_id)
        return node.cluster if node else None

    def _iter_jsonl(self, path: Path) -> Iterable[dict[str, Any]]:
        try:
            with path.open() as handle:
                for raw_line in handle:
                    stripped = raw_line.strip()
                    if not stripped:
                        continue
                    try:
                        yield json.loads(stripped)
                    except json.JSONDecodeError:
                        continue
        except OSError:
            return

    def _should_skip_user_record(self, record: dict[str, Any]) -> bool:
        if record.get("isMeta"):
            return True
        if record.get("toolUseResult"):
            return True

        content = record.get("message", {}).get("content")
        if isinstance(content, str):
            return any(marker in content for marker in LOCAL_COMMAND_MARKERS)
        if isinstance(content, list):
            for item in content:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "tool_result":
                    return True
                if item.get("type") == "text" and any(
                    marker in str(item.get("text", "")) for marker in LOCAL_COMMAND_MARKERS
                ):
                    return True
        return False

    def _label_for_user_record(self, record: dict[str, Any]) -> str:
        text = self._detail_for_user_record(record)
        return self._summarize_text(text, fallback="User request")

    def _label_for_assistant_record(self, record: dict[str, Any]) -> str:
        message = record.get("message", {})
        content = message.get("content")
        if isinstance(content, list):
            tool_uses = [item for item in content if isinstance(item, dict) and item.get("type") == "tool_use"]
            if tool_uses:
                first = tool_uses[0]
                name = first.get("name", "Tool")
                payload = first.get("input", {})
                detail = payload.get("subject") or payload.get("team_name") or payload.get("description")
                base = f"{name}: {detail}" if detail else name
                return self._summarize_text(base, fallback="Tool use")
        return self._summarize_text(self._detail_for_assistant_record(record), fallback="Assistant response")

    def _detail_for_user_record(self, record: dict[str, Any]) -> str:
        text = self._clean_message_text(self._raw_message_text(record.get("message")))
        return text or "User request"

    def _detail_for_assistant_record(self, record: dict[str, Any]) -> str:
        message = record.get("message", {})
        content = message.get("content")
        if isinstance(content, list):
            text_chunks = [
                str(item.get("text", ""))
                for item in content
                if isinstance(item, dict) and item.get("type") == "text" and item.get("text")
            ]
            text = self._clean_message_text("\n".join(text_chunks))
            if text:
                return text
        text = self._clean_message_text(self._raw_message_text(message))
        return text or "Assistant response"

    def _raw_message_text(self, message: Any) -> str:
        if isinstance(message, dict):
            content = message.get("content")
        else:
            content = message

        if isinstance(content, str):
            return content
        if isinstance(content, list):
            chunks: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        chunks.append(str(item.get("text", "")))
                    elif item.get("type") == "tool_use":
                        chunks.append(str(item.get("name", "")))
                else:
                    chunks.append(str(item))
            return "\n".join(chunk for chunk in chunks if chunk)
        return ""

    def _clean_message_text(self, text: str) -> str:
        if not text:
            return ""
        text = re.sub(r"</?teammate-message[^>]*>", "", text)
        text = text.replace("\r\n", "\n")
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _summarize_text(self, text: str, fallback: str = "Event") -> str:
        normalized = re.sub(r"\s+", " ", text).strip()
        if not normalized:
            return fallback
        if len(normalized) <= 72:
            return normalized
        return normalized[:69].rstrip() + "..."

    def _speaker_for_record(
        self,
        snapshot: GraphSnapshot,
        record: dict[str, Any],
        kind: NodeKind,
        agent_node_id: str | None,
    ) -> str:
        is_sidechain = bool(record.get("isSidechain"))
        if kind == NodeKind.USER_REQUEST:
            return "Claude Code" if is_sidechain else "You"
        if not is_sidechain:
            return "Claude Code"
        if agent_node_id and agent_node_id in snapshot.nodes:
            return self._normalize_agent_label(snapshot.nodes[agent_node_id].label)
        return "Worker"

    def _normalize_agent_label(self, label: str) -> str:
        compact = label.strip()
        if re.fullmatch(r"a[0-9a-f]{6,}", compact) or re.fullmatch(r"acompact-[0-9a-f]+", compact):
            return "Worker"
        return compact or "Worker"

    def _parse_json_text(self, raw: str) -> dict[str, Any] | None:
        raw = raw.strip()
        if not raw.startswith("{") or not raw.endswith("}"):
            return None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    def _extract_team_name(self, text: str) -> str | None:
        match = re.search(r"on the ([A-Za-z0-9._-]+) team", text)
        return match.group(1) if match else None

    def _extract_assigned_task_id(self, text: str) -> str | None:
        match = re.search(r"assigned task \(#(\d+)\)", text)
        return match.group(1) if match else None
