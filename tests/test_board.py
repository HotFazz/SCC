from scc.board import BoardBuilder
from scc.domain import EdgeKind, GraphEdge, GraphNode, GraphSnapshot, NodeKind


def test_session_board_materializes_swarm_tasks_from_agent_turns() -> None:
    snapshot = GraphSnapshot()
    snapshot.upsert_node(
        GraphNode(
            id="agent:session:session-1",
            kind=NodeKind.AGENT,
            label="claude",
            session_id="session-1",
        )
    )
    snapshot.upsert_node(
        GraphNode(
            id="agent:runtime:worker-1",
            kind=NodeKind.AGENT,
            label="worker-1",
            session_id="session-1",
            agent_id="worker-1",
        )
    )
    snapshot.upsert_node(
        GraphNode(
            id="turn:user-1",
            kind=NodeKind.USER_REQUEST,
            label="Inspect the repo.",
            session_id="session-1",
            timestamp="2026-03-15T10:00:00Z",
        )
    )
    snapshot.upsert_node(
        GraphNode(
            id="turn:agent-1",
            kind=NodeKind.MODEL_TURN,
            label="Agent: Explore repo structure",
            session_id="session-1",
            timestamp="2026-03-15T10:00:01Z",
            metadata={"raw_text": "Agent"},
        )
    )
    snapshot.upsert_node(
        GraphNode(
            id="turn:summary-1",
            kind=NodeKind.MODEL_TURN,
            label="Launched agents",
            session_id="session-1",
            timestamp="2026-03-15T10:00:02Z",
        )
    )
    snapshot.upsert_node(
        GraphNode(
            id="turn:worker-1",
            kind=NodeKind.MODEL_TURN,
            label="Repository structure is clear.",
            session_id="session-1",
            timestamp="2026-03-15T10:00:03Z",
        )
    )
    snapshot.add_edge(GraphEdge(source="turn:user-1", target="agent:session:session-1", kind=EdgeKind.ROUTED_TO))
    snapshot.add_edge(GraphEdge(source="agent:session:session-1", target="turn:agent-1", kind=EdgeKind.PRODUCED))
    snapshot.add_edge(GraphEdge(source="agent:session:session-1", target="turn:summary-1", kind=EdgeKind.PRODUCED))
    snapshot.add_edge(GraphEdge(source="agent:runtime:worker-1", target="turn:worker-1", kind=EdgeKind.PRODUCED))

    board = BoardBuilder().build(snapshot)

    task_cards = [
        card
        for row in board.rows
        for lane, card in row.cells.items()
        if lane == "tasks"
    ]
    worker_cards = [
        card
        for row in board.rows
        for lane, card in row.cells.items()
        if lane == "workers"
    ]

    assert board.title.startswith("session ")
    assert any(card.title == "Explore repo structure" for card in task_cards)
    assert any(card.title == "worker-1" for card in worker_cards)
