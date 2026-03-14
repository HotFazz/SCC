from __future__ import annotations

import subprocess

from scc.domain import EdgeKind, GraphEdge, GraphNode, GraphSnapshot, NodeKind
from scc.layout import AutoLayoutEngine, GraphvizLayoutEngine, LayeredLayoutEngine


def sample_snapshot() -> GraphSnapshot:
    snapshot = GraphSnapshot()
    snapshot.upsert_node(GraphNode(id="team:demo", kind=NodeKind.TEAM, label="demo", cluster="demo"))
    snapshot.upsert_node(GraphNode(id="agent:demo:lead", kind=NodeKind.AGENT, label="team-lead", cluster="demo"))
    snapshot.upsert_node(
        GraphNode(id="turn:user-1", kind=NodeKind.USER_REQUEST, label="Inspect the repo", cluster="demo")
    )
    snapshot.add_edge(GraphEdge(source="team:demo", target="agent:demo:lead", kind=EdgeKind.CONTAINS))
    snapshot.add_edge(GraphEdge(source="turn:user-1", target="agent:demo:lead", kind=EdgeKind.ROUTED_TO))
    return snapshot


def test_graphviz_layout_parses_plain_output() -> None:
    def runner(*args, **kwargs) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["dot", "-Tplain"],
            returncode=0,
            stdout=(
                "graph 1 10 5\n"
                "node team:demo 1 4 2 1 demo solid box black lightgrey\n"
                "node agent:demo:lead 5 2 2 1 team-lead solid box black lightgrey\n"
                "edge team:demo agent:demo:lead 2 2 4 4 2 solid black\n"
                "stop\n"
            ),
            stderr="",
        )

    layout = GraphvizLayoutEngine(runner=runner).layout(sample_snapshot())
    assert layout.engine == "graphviz"
    assert "team:demo" in layout.node_positions
    assert ("team:demo", "agent:demo:lead", "plain") in layout.edge_paths


def test_graphviz_layout_parses_quoted_identifiers() -> None:
    def runner(*args, **kwargs) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["dot", "-Tplain"],
            returncode=0,
            stdout=(
                'graph 1 10 5\n'
                'node "team:demo" 1 4 2 1 "demo" solid box black lightgrey\n'
                'node "agent:demo:lead" 5 2 2 1 "team-lead" solid box black lightgrey\n'
                'edge "team:demo" "agent:demo:lead" 2 2 4 4 2 solid black\n'
                "stop\n"
            ),
            stderr="",
        )

    layout = GraphvizLayoutEngine(runner=runner).layout(sample_snapshot())
    assert "team:demo" in layout.node_positions
    assert "agent:demo:lead" in layout.node_positions
    assert ("team:demo", "agent:demo:lead", "plain") in layout.edge_paths


def test_auto_layout_falls_back_when_graphviz_is_missing() -> None:
    def missing_runner(*args, **kwargs) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("dot not found")

    layout = AutoLayoutEngine(
        graphviz=GraphvizLayoutEngine(runner=missing_runner),
        fallback=LayeredLayoutEngine(),
    ).layout(sample_snapshot())
    assert layout.engine == "layered"
    assert "turn:user-1" in layout.node_positions
