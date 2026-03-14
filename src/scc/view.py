from __future__ import annotations

from dataclasses import dataclass

from scc.domain import GraphSnapshot, NodeKind, TimelineEvent


@dataclass(slots=True)
class FocusOption:
    label: str
    value: str
    timestamp: str | None


@dataclass(slots=True)
class FocusedSnapshot:
    focus: FocusOption
    snapshot: GraphSnapshot
    events: list[TimelineEvent]


def build_transcript_events(
    focused: FocusedSnapshot,
    limit: int = 120,
) -> list[TimelineEvent]:
    turn_events = [
        event
        for event in focused.events
        if event.kind in {"user_turn", "assistant_turn"}
    ]
    if not turn_events:
        return focused.events[-limit:]

    focus_value = focused.focus.value
    if focus_value.startswith("team:"):
        team_name = focus_value.split(":", 1)[1]
        team_node = focused.snapshot.nodes.get(f"team:{team_name}")
        lead_session_id = team_node.session_id if team_node else None
        if lead_session_id:
            main_session = [
                event
                for event in turn_events
                if event.session_id == lead_session_id and not event.metadata.get("is_sidechain")
            ]
            if main_session:
                return main_session[-limit:]

        primary = [
            event
            for event in turn_events
            if event.team == team_name and not event.metadata.get("is_sidechain")
        ]
        if primary:
            return primary[-limit:]

        return []

    if focus_value.startswith("session:"):
        session_id = focus_value.split(":", 1)[1]
        session_events = [event for event in turn_events if event.session_id == session_id]
        return session_events[-limit:]

    primary = [event for event in turn_events if not event.metadata.get("is_sidechain")]
    return primary[-limit:]


def build_focus_options(snapshot: GraphSnapshot) -> list[FocusOption]:
    team_timestamps: dict[str, str | None] = {}
    session_timestamps: dict[str, str | None] = {}

    for node in snapshot.nodes.values():
        if node.kind == NodeKind.TEAM:
            team_name = node.label
            team_timestamps[team_name] = _latest(team_timestamps.get(team_name), node.timestamp)
        if node.session_id:
            session_timestamps[node.session_id] = _latest(
                session_timestamps.get(node.session_id),
                node.timestamp,
            )
        if node.cluster:
            team_timestamps[node.cluster] = _latest(team_timestamps.get(node.cluster), node.timestamp)

    for event in snapshot.timeline:
        if event.team:
            team_timestamps[event.team] = _latest(team_timestamps.get(event.team), event.timestamp)
        if event.session_id:
            session_timestamps[event.session_id] = _latest(
                session_timestamps.get(event.session_id),
                event.timestamp,
            )

    team_options = [
        FocusOption(label=f"Team: {team_name}", value=f"team:{team_name}", timestamp=timestamp)
        for team_name, timestamp in team_timestamps.items()
    ]
    session_options = [
        FocusOption(
            label=f"Session: {session_id[:8]}",
            value=f"session:{session_id}",
            timestamp=timestamp,
        )
        for session_id, timestamp in session_timestamps.items()
    ]

    return sorted(team_options, key=lambda item: (item.timestamp or "", item.label), reverse=True) + sorted(
        session_options,
        key=lambda item: (item.timestamp or "", item.label),
        reverse=True,
    )


def focus_snapshot(
    snapshot: GraphSnapshot,
    focus_value: str,
    turn_limit: int = 80,
    event_limit: int = 140,
) -> FocusedSnapshot:
    focus = next(
        (option for option in build_focus_options(snapshot) if option.value == focus_value),
        FocusOption(label="All activity", value="all", timestamp=None),
    )

    if focus_value == "all":
        node_ids = set(snapshot.nodes)
        events = snapshot.sorted_timeline()[-event_limit:]
        return FocusedSnapshot(focus=focus, snapshot=_clone_snapshot(snapshot, node_ids, events), events=events)

    if focus_value.startswith("team:"):
        team_name = focus_value.split(":", 1)[1]
        team_node = snapshot.nodes.get(f"team:{team_name}")
        lead_session_id = team_node.session_id if team_node else None
        node_ids = {
            node_id
            for node_id, node in snapshot.nodes.items()
            if node.cluster == team_name or node_id == f"team:{team_name}"
        }
        if lead_session_id:
            node_ids.update(
                node_id
                for node_id, node in snapshot.nodes.items()
                if node.session_id == lead_session_id
            )
        node_ids = _trim_turn_nodes(snapshot, node_ids, turn_limit)
        events = [
            event
            for event in snapshot.sorted_timeline()
            if event.team == team_name
            or event.source_node_id in node_ids
            or (lead_session_id is not None and event.session_id == lead_session_id)
        ][-event_limit:]
        return FocusedSnapshot(focus=focus, snapshot=_clone_snapshot(snapshot, node_ids, events), events=events)

    if focus_value.startswith("session:"):
        session_id = focus_value.split(":", 1)[1]
        node_ids = {
            node_id
            for node_id, node in snapshot.nodes.items()
            if node.session_id == session_id
        }
        expanded = set(node_ids)
        for edge in snapshot.edges:
            if edge.source in node_ids and edge.target in snapshot.nodes:
                target = snapshot.nodes[edge.target]
                if target.kind in {NodeKind.AGENT, NodeKind.TEAM}:
                    expanded.add(edge.target)
            if edge.target in node_ids and edge.source in snapshot.nodes:
                source = snapshot.nodes[edge.source]
                if source.kind in {NodeKind.AGENT, NodeKind.TEAM}:
                    expanded.add(edge.source)
        expanded = _trim_turn_nodes(snapshot, expanded, turn_limit)
        events = [
            event
            for event in snapshot.sorted_timeline()
            if event.session_id == session_id or event.source_node_id in expanded
        ][-event_limit:]
        return FocusedSnapshot(focus=focus, snapshot=_clone_snapshot(snapshot, expanded, events), events=events)

    events = snapshot.sorted_timeline()[-event_limit:]
    return FocusedSnapshot(focus=focus, snapshot=_clone_snapshot(snapshot, set(snapshot.nodes), events), events=events)


def pick_default_node(snapshot: GraphSnapshot) -> str | None:
    turns = sorted(
        (node for node in snapshot.nodes.values() if node.kind in {NodeKind.MODEL_TURN, NodeKind.USER_REQUEST}),
        key=lambda item: (item.timestamp or "", item.id),
    )
    if turns:
        return turns[-1].id

    agents = sorted(
        (node for node in snapshot.nodes.values() if node.kind == NodeKind.AGENT),
        key=lambda item: item.id,
    )
    return agents[0].id if agents else None


def _clone_snapshot(
    snapshot: GraphSnapshot,
    node_ids: set[str],
    events: list[TimelineEvent],
) -> GraphSnapshot:
    cloned = GraphSnapshot()
    for node_id in sorted(node_ids):
        node = snapshot.nodes.get(node_id)
        if node:
            cloned.upsert_node(node)
    for edge in snapshot.edges:
        if edge.source in node_ids and edge.target in node_ids:
            cloned.add_edge(edge)
    for event in events:
        cloned.add_event(event)
    cloned.warnings.extend(snapshot.warnings)
    return cloned


def _trim_turn_nodes(snapshot: GraphSnapshot, node_ids: set[str], turn_limit: int) -> set[str]:
    turn_ids = [
        node_id
        for node_id in node_ids
        if snapshot.nodes[node_id].kind in {NodeKind.USER_REQUEST, NodeKind.MODEL_TURN}
    ]
    if len(turn_ids) <= turn_limit:
        return node_ids

    keep_turns = {
        node.id
        for node in sorted(
            (snapshot.nodes[node_id] for node_id in turn_ids),
            key=lambda item: (item.timestamp or "", item.id),
        )[-turn_limit:]
    }
    return {node_id for node_id in node_ids if node_id not in turn_ids or node_id in keep_turns}


def _latest(current: str | None, candidate: str | None) -> str | None:
    if current is None:
        return candidate
    if candidate is None:
        return current
    return max(current, candidate)
