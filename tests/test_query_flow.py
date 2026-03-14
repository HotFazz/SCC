from scc.domain import EdgeKind, GraphEdge, GraphNode, GraphSnapshot, NodeKind
from scc.query_flow import QueryFlowBuilder


def test_query_flow_groups_requests_into_scroll_sections() -> None:
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
            label="First query",
            session_id="session-1",
            timestamp="2026-03-15T10:00:00Z",
            metadata={"raw_text": "First query"},
        )
    )
    snapshot.upsert_node(
        GraphNode(
            id="turn:lead-1",
            kind=NodeKind.MODEL_TURN,
            label="Agent: Explore repo structure",
            session_id="session-1",
            timestamp="2026-03-15T10:00:01Z",
            metadata={"raw_text": "Agent"},
        )
    )
    snapshot.upsert_node(
        GraphNode(
            id="turn:worker-1",
            kind=NodeKind.MODEL_TURN,
            label="Repo structure complete.",
            session_id="session-1",
            timestamp="2026-03-15T10:00:03Z",
        )
    )
    snapshot.upsert_node(
        GraphNode(
            id="turn:final-1",
            kind=NodeKind.MODEL_TURN,
            label="Here is the result.",
            session_id="session-1",
            timestamp="2026-03-15T10:00:04Z",
            metadata={"raw_text": "Here is the result."},
        )
    )
    snapshot.upsert_node(
        GraphNode(
            id="turn:user-2",
            kind=NodeKind.USER_REQUEST,
            label="Second query",
            session_id="session-1",
            timestamp="2026-03-15T10:01:00Z",
            metadata={"raw_text": "Second query"},
        )
    )
    snapshot.upsert_node(
        GraphNode(
            id="turn:final-2",
            kind=NodeKind.MODEL_TURN,
            label="Second answer.",
            session_id="session-1",
            timestamp="2026-03-15T10:01:05Z",
            metadata={"raw_text": "Second answer."},
        )
    )
    snapshot.add_edge(GraphEdge(source="turn:user-1", target="agent:session:session-1", kind=EdgeKind.ROUTED_TO))
    snapshot.add_edge(GraphEdge(source="agent:session:session-1", target="turn:lead-1", kind=EdgeKind.PRODUCED))
    snapshot.add_edge(GraphEdge(source="agent:runtime:worker-1", target="turn:worker-1", kind=EdgeKind.PRODUCED))
    snapshot.add_edge(GraphEdge(source="agent:session:session-1", target="turn:final-1", kind=EdgeKind.PRODUCED))
    snapshot.add_edge(GraphEdge(source="turn:user-2", target="agent:session:session-1", kind=EdgeKind.ROUTED_TO))
    snapshot.add_edge(GraphEdge(source="agent:session:session-1", target="turn:final-2", kind=EdgeKind.PRODUCED))

    model = QueryFlowBuilder().build(snapshot)

    assert model.title.startswith("session ")
    assert len(model.sections) == 2
    assert model.sections[0].request_card.title == "You"
    assert model.sections[0].worker_flows[0].task_card is not None
    assert model.sections[0].worker_flows[0].worker_card is not None
    assert model.sections[0].worker_flows[0].summary_card is not None
    assert model.sections[0].worker_flows[0].worker_card.body_lines == ["reported progress"]
    assert model.sections[0].worker_flows[0].summary_card.body_lines == ["Repo structure complete."]
    assert model.sections[0].lead_card is not None
    assert model.sections[0].lead_card.max_body_lines == 8
    assert model.sections[0].lead_card.body_lines == [
        "window: 10:00:00",
        "delegated to 1 worker",
        "reports: 1/1",
        "spawned Explore repo structure",
        "response delivered",
    ]
    assert model.sections[0].final_card is not None
    assert model.sections[0].final_card.title == "Claude Code"
    assert model.sections[1].request_card.title == "You"
    assert model.sections[1].lead_card is not None
    assert model.sections[1].lead_card.max_body_lines == 4


def test_query_flow_ignores_sidechain_user_prompts_as_sections() -> None:
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
            label="Main query",
            session_id="session-1",
            timestamp="2026-03-15T10:00:00Z",
            metadata={"raw_text": "Main query", "speaker": "You"},
        )
    )
    snapshot.upsert_node(
        GraphNode(
            id="turn:user-2",
            kind=NodeKind.USER_REQUEST,
            label="Research only",
            session_id="session-1",
            timestamp="2026-03-15T10:00:10Z",
            metadata={
                "raw_text": "Research only",
                "speaker": "Claude Code",
                "is_sidechain": True,
            },
        )
    )
    snapshot.upsert_node(
        GraphNode(
            id="turn:assistant-1",
            kind=NodeKind.MODEL_TURN,
            label="Agent: Explore repo structure",
            session_id="session-1",
            timestamp="2026-03-15T10:00:02Z",
            metadata={"raw_text": "Agent"},
        )
    )
    snapshot.upsert_node(
        GraphNode(
            id="turn:assistant-2",
            kind=NodeKind.MODEL_TURN,
            label="Here is the result.",
            session_id="session-1",
            timestamp="2026-03-15T10:00:20Z",
            metadata={"raw_text": "Here is the result."},
        )
    )
    snapshot.upsert_node(
        GraphNode(
            id="turn:worker-1",
            kind=NodeKind.MODEL_TURN,
            label="Repo structure complete.",
            session_id="session-1",
            timestamp="2026-03-15T10:00:15Z",
        )
    )
    snapshot.add_edge(GraphEdge(source="turn:user-1", target="agent:session:session-1", kind=EdgeKind.ROUTED_TO))
    snapshot.add_edge(GraphEdge(source="turn:user-2", target="agent:runtime:worker-1", kind=EdgeKind.ROUTED_TO))
    snapshot.add_edge(GraphEdge(source="agent:session:session-1", target="turn:assistant-1", kind=EdgeKind.PRODUCED))
    snapshot.add_edge(GraphEdge(source="agent:session:session-1", target="turn:assistant-2", kind=EdgeKind.PRODUCED))
    snapshot.add_edge(GraphEdge(source="agent:runtime:worker-1", target="turn:worker-1", kind=EdgeKind.PRODUCED))

    model = QueryFlowBuilder().build(snapshot)

    assert len(model.sections) == 1
    assert model.sections[0].request_card.title == "You"
    assert model.sections[0].request_card.body_lines == ["Main query"]
