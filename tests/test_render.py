from scc.domain import EdgeKind, GraphEdge, GraphNode, GraphSnapshot, NodeKind
from scc.render import AsciiGraphRenderer


def test_renderer_outputs_board_cards_and_connections() -> None:
    snapshot = GraphSnapshot()
    snapshot.upsert_node(GraphNode(id="team:demo", kind=NodeKind.TEAM, label="demo", cluster="demo"))
    snapshot.upsert_node(
        GraphNode(
            id="agent:demo:lead",
            kind=NodeKind.AGENT,
            label="team-lead",
            cluster="demo",
            metadata={"agent_type": "team-lead", "model": "claude-opus"},
        )
    )
    snapshot.upsert_node(
        GraphNode(id="agent:demo:worker", kind=NodeKind.AGENT, label="worker", cluster="demo")
    )
    snapshot.upsert_node(
        GraphNode(
            id="turn:user-1",
            kind=NodeKind.USER_REQUEST,
            label="Please inspect the repository.",
            cluster="demo",
            timestamp="2026-03-14T10:00:00Z",
        )
    )
    snapshot.upsert_node(
        GraphNode(
            id="turn:model-1",
            kind=NodeKind.MODEL_TURN,
            label="I will inspect the repository and report back.",
            cluster="demo",
            timestamp="2026-03-14T10:00:01Z",
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
    snapshot.add_edge(GraphEdge(source="team:demo", target="agent:demo:lead", kind=EdgeKind.CONTAINS))
    snapshot.add_edge(GraphEdge(source="team:demo", target="agent:demo:worker", kind=EdgeKind.CONTAINS))
    snapshot.add_edge(GraphEdge(source="turn:user-1", target="agent:demo:lead", kind=EdgeKind.ROUTED_TO))
    snapshot.add_edge(GraphEdge(source="agent:demo:lead", target="turn:model-1", kind=EdgeKind.PRODUCED))
    snapshot.add_edge(GraphEdge(source="task:demo:1", target="agent:demo:worker", kind=EdgeKind.ASSIGNED))

    document = AsciiGraphRenderer(lane_width=26).render(
        snapshot,
        selected_node_id="turn:model-1",
    )

    assert "Board view: demo board" in document.text
    assert "Requests" in document.text
    assert "Lead" in document.text
    assert "Tasks" in document.text
    assert "Workers" in document.text
    assert "Summaries" in document.text
    assert "R1 Recent user" in document.text
    assert "L1 team-lead" in document.text
    assert "T1 #1 Inspect" in document.text
    assert "W1 worker" in document.text
    assert "-->" in document.text
    assert "Relation Notes" in document.text


def test_renderer_resets_card_ids_between_renders() -> None:
    snapshot = GraphSnapshot()
    snapshot.upsert_node(GraphNode(id="team:demo", kind=NodeKind.TEAM, label="demo", cluster="demo"))
    snapshot.upsert_node(
        GraphNode(
            id="agent:demo:lead",
            kind=NodeKind.AGENT,
            label="team-lead",
            cluster="demo",
            metadata={"agent_type": "team-lead"},
        )
    )
    snapshot.upsert_node(
        GraphNode(
            id="turn:user-1",
            kind=NodeKind.USER_REQUEST,
            label="Inspect the repo.",
            cluster="demo",
            timestamp="2026-03-14T10:00:00Z",
        )
    )
    snapshot.add_edge(GraphEdge(source="turn:user-1", target="agent:demo:lead", kind=EdgeKind.ROUTED_TO))

    renderer = AsciiGraphRenderer(lane_width=24)
    first = renderer.render(snapshot).text
    second = renderer.render(snapshot).text

    assert "R1 Recent user" in first
    assert "R1 Recent user" in second
    assert "L1 team-lead" in first
    assert "L1 team-lead" in second
