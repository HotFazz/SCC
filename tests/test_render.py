from scc.domain import EdgeKind, GraphEdge, GraphNode, GraphSnapshot, NodeKind
from scc.layout import LayoutResult
from scc.render import AsciiGraphRenderer


def test_renderer_outputs_readable_flow_tree() -> None:
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

    document = AsciiGraphRenderer(max_line_length=80).render(
        snapshot,
        LayoutResult("graphviz", 0.0, 0.0, {}, {}),
        selected_node_id="turn:model-1",
    )

    assert "Flow view: recent swarm activity grouped by team and agent." in document.text
    assert "[T] demo" in document.text
    assert "[A] team-lead [claude-opus]" in document.text
    assert "[K] #1 Inspect repository [in_progress] -> worker" in document.text
    assert "* [M] I will inspect the repository and report back." in document.text
