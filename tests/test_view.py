from scc.domain import GraphNode, GraphSnapshot, NodeKind, TimelineEvent
from scc.view import FocusOption, FocusedSnapshot, build_transcript_events


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
