from scc.domain import EdgeKind, GraphEdge, GraphNode, GraphSnapshot, NodeKind, TimelineEvent
from scc.view import FocusOption, FocusedSnapshot, build_transcript_events, focus_snapshot


def test_team_transcript_prefers_lead_session() -> None:
    snapshot = GraphSnapshot()
    snapshot.upsert_node(
        GraphNode(
            id="team:demo",
            kind=NodeKind.TEAM,
            label="demo",
            cluster="demo",
            session_id="session-main",
        )
    )

    events = [
        TimelineEvent(
            id="main-user",
            timestamp="2026-03-14T09:59:00Z",
            kind="user_turn",
            title="Please inspect the repo.",
            detail="Please inspect the repo.",
            source_node_id="turn:user-main",
            team="demo",
            session_id="session-main",
            metadata={"speaker": "You", "is_sidechain": False},
        ),
        TimelineEvent(
            id="main-assistant",
            timestamp="2026-03-14T09:59:05Z",
            kind="assistant_turn",
            title="Creating a team and assigning work.",
            detail="Creating a team and assigning work.",
            source_node_id="turn:assistant-main",
            team="demo",
            session_id="session-main",
            metadata={"speaker": "Claude Code", "is_sidechain": False},
        ),
        TimelineEvent(
            id="worker-user",
            timestamp="2026-03-14T10:00:00Z",
            kind="user_turn",
            title="Read task #1.",
            detail="Read task #1.",
            source_node_id="turn:user-worker",
            team="demo",
            session_id="session-worker",
            metadata={"speaker": "Claude Code", "is_sidechain": True},
        ),
        TimelineEvent(
            id="worker-assistant",
            timestamp="2026-03-14T10:00:10Z",
            kind="assistant_turn",
            title="The repository structure is clear.",
            detail="The repository structure is clear.",
            source_node_id="turn:assistant-worker",
            team="demo",
            session_id="session-worker",
            metadata={"speaker": "worker", "is_sidechain": True},
        ),
    ]

    focused = FocusedSnapshot(
        focus=FocusOption(label="Team: demo", value="team:demo", timestamp="2026-03-14T10:00:10Z"),
        snapshot=snapshot,
        events=events,
    )

    transcript = build_transcript_events(focused)

    assert [event.id for event in transcript] == ["main-user", "main-assistant"]


def test_team_transcript_hides_sidechains_without_primary_session() -> None:
    snapshot = GraphSnapshot()
    snapshot.upsert_node(
        GraphNode(
            id="team:demo",
            kind=NodeKind.TEAM,
            label="demo",
            cluster="demo",
            session_id="session-main",
        )
    )

    focused = FocusedSnapshot(
        focus=FocusOption(label="Team: demo", value="team:demo", timestamp="2026-03-14T10:00:10Z"),
        snapshot=snapshot,
        events=[
            TimelineEvent(
                id="worker-assistant",
                timestamp="2026-03-14T10:00:10Z",
                kind="assistant_turn",
                title="The repository structure is clear.",
                detail="The repository structure is clear.",
                source_node_id="turn:assistant-worker",
                team="demo",
                session_id="session-main",
                metadata={"speaker": "worker", "is_sidechain": True},
            )
        ],
    )

    assert build_transcript_events(focused) == []


def test_session_focus_keeps_related_tasks_and_team_nodes() -> None:
    snapshot = GraphSnapshot()
    snapshot.upsert_node(
        GraphNode(
            id="team:demo",
            kind=NodeKind.TEAM,
            label="demo",
            cluster="demo",
            session_id="session-1",
        )
    )
    snapshot.upsert_node(
        GraphNode(
            id="agent:session:session-1",
            kind=NodeKind.AGENT,
            label="claude",
            session_id="session-1",
            cluster="demo",
        )
    )
    snapshot.upsert_node(
        GraphNode(
            id="task:demo:1",
            kind=NodeKind.TASK,
            label="#1 Inspect repository",
            cluster="demo",
            status="in_progress",
        )
    )
    snapshot.upsert_node(
        GraphNode(
            id="turn:user-1",
            kind=NodeKind.USER_REQUEST,
            label="Inspect the repo.",
            session_id="session-1",
            cluster="demo",
            timestamp="2026-03-15T10:00:00Z",
        )
    )
    snapshot.add_edge(GraphEdge(source="team:demo", target="agent:session:session-1", kind=EdgeKind.CONTAINS))
    snapshot.add_edge(GraphEdge(source="team:demo", target="task:demo:1", kind=EdgeKind.CONTAINS))
    snapshot.add_edge(GraphEdge(source="task:demo:1", target="agent:session:session-1", kind=EdgeKind.ASSIGNED))

    focused = focus_snapshot(snapshot, "session:session-1")

    assert "team:demo" in focused.snapshot.nodes
    assert "task:demo:1" in focused.snapshot.nodes


def test_trim_turn_nodes_preserves_swarm_agent_launches() -> None:
    snapshot = GraphSnapshot()
    session_id = "session-1"
    snapshot.upsert_node(
        GraphNode(
            id="agent:session:session-1",
            kind=NodeKind.AGENT,
            label="claude",
            session_id=session_id,
        )
    )
    for index in range(90):
        node = GraphNode(
            id=f"turn:{index}",
            kind=NodeKind.MODEL_TURN,
            label="Agent: Explore repo structure" if index == 0 else f"Turn {index}",
            session_id=session_id,
            timestamp=f"2026-03-15T10:{index:02d}:00Z",
        )
        snapshot.upsert_node(node)

    focused = focus_snapshot(snapshot, f"session:{session_id}", turn_limit=20)

    assert "turn:0" in focused.snapshot.nodes
