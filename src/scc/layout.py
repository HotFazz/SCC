from __future__ import annotations

import re
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import networkx as nx

from scc.domain import EdgeKind, GraphSnapshot, NodeKind


@dataclass(slots=True)
class NodePlacement:
    x: float
    y: float
    width: float
    height: float


@dataclass(slots=True)
class EdgePlacement:
    points: list[tuple[float, float]] = field(default_factory=list)


@dataclass(slots=True)
class LayoutResult:
    engine: str
    width: float
    height: float
    node_positions: dict[str, NodePlacement]
    edge_paths: dict[tuple[str, str, str], EdgePlacement]


class GraphvizUnavailable(RuntimeError):
    pass


class GraphvizLayoutEngine:
    def __init__(
        self,
        executable: str = "dot",
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self.executable = executable
        self.runner = runner or subprocess.run

    def layout(self, snapshot: GraphSnapshot) -> LayoutResult:
        try:
            completed = self.runner(
                [self.executable, "-Tplain"],
                input=self._to_dot(snapshot),
                text=True,
                capture_output=True,
                check=True,
            )
        except FileNotFoundError as error:
            raise GraphvizUnavailable("Graphviz dot executable is not installed") from error
        except subprocess.CalledProcessError as error:
            raise GraphvizUnavailable(error.stderr.strip() or "Graphviz dot failed") from error

        return self._parse_plain_output(completed.stdout)

    def _to_dot(self, snapshot: GraphSnapshot) -> str:
        lines = [
            "digraph scc {",
            "  graph [rankdir=LR, splines=polyline, compound=true, pad=0.3];",
            '  node [fontname="Menlo", fontsize=10, margin=0.2];',
            '  edge [fontname="Menlo", fontsize=9, arrowsize=0.7];',
        ]

        grouped: dict[str | None, list[str]] = {}
        for node in snapshot.nodes.values():
            grouped.setdefault(node.cluster, []).append(node.id)

        for cluster, node_ids in sorted(grouped.items(), key=lambda item: item[0] or ""):
            if cluster is None:
                for node_id in sorted(node_ids):
                    lines.append(self._node_statement(snapshot, node_id))
                continue

            cluster_id = f"cluster_{self._escape_identifier(cluster)}"
            lines.append(f'  subgraph "{cluster_id}" {{')
            lines.append(f'    label="{self._escape_label(cluster)}";')
            lines.append('    style="rounded";')
            lines.append('    color="#6b7280";')
            for node_id in sorted(node_ids):
                lines.append(f"    {self._node_statement(snapshot, node_id).strip()}")
            lines.append("  }")

        for edge in snapshot.edges:
            source = self._quote_identifier(edge.source)
            target = self._quote_identifier(edge.target)
            attrs = []
            if edge.label:
                attrs.append(f'label="{self._escape_label(edge.label)}"')
            color = {
                EdgeKind.CONTAINS: "#6b7280",
                EdgeKind.ROUTED_TO: "#0f766e",
                EdgeKind.PRODUCED: "#7c3aed",
                EdgeKind.PARENT: "#2563eb",
                EdgeKind.ASSIGNED: "#d97706",
                EdgeKind.DISPATCHED: "#f59e0b",
                EdgeKind.BLOCKED_BY: "#dc2626",
                EdgeKind.SUMMARIZED_TO: "#4b5563",
            }[edge.kind]
            attrs.append(f'color="{color}"')
            lines.append(f"  {source} -> {target} [{', '.join(attrs)}];")

        lines.append("}")
        return "\n".join(lines)

    def _node_statement(self, snapshot: GraphSnapshot, node_id: str) -> str:
        node = snapshot.nodes[node_id]
        shape = {
            NodeKind.TEAM: "folder",
            NodeKind.AGENT: "component",
            NodeKind.USER_REQUEST: "note",
            NodeKind.MODEL_TURN: "box",
            NodeKind.TASK: "hexagon",
        }[node.kind]
        fill = {
            NodeKind.TEAM: "#e5e7eb",
            NodeKind.AGENT: "#dbeafe",
            NodeKind.USER_REQUEST: "#dcfce7",
            NodeKind.MODEL_TURN: "#ede9fe",
            NodeKind.TASK: "#fef3c7",
        }[node.kind]
        label = self._escape_label(node.label)
        return (
            f'  {self._quote_identifier(node.id)} '
            f'[label="{label}", shape="{shape}", style="filled,rounded", fillcolor="{fill}"];'
        )

    def _parse_plain_output(self, output: str) -> LayoutResult:
        width = 0.0
        height = 0.0
        node_positions: dict[str, NodePlacement] = {}
        edge_paths: dict[tuple[str, str, str], EdgePlacement] = {}

        for line in output.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            parts = shlex.split(stripped)
            if parts[0] == "graph":
                width = float(parts[2])
                height = float(parts[3])
                continue
            if parts[0] == "node":
                node_positions[parts[1]] = NodePlacement(
                    x=float(parts[2]),
                    y=float(parts[3]),
                    width=float(parts[4]),
                    height=float(parts[5]),
                )
                continue
            if parts[0] == "edge":
                source = parts[1]
                target = parts[2]
                count = int(parts[3])
                points = []
                cursor = 4
                for _ in range(count):
                    points.append((float(parts[cursor]), float(parts[cursor + 1])))
                    cursor += 2
                edge_paths[(source, target, "plain")] = EdgePlacement(points=points)

        return LayoutResult(
            engine="graphviz",
            width=width,
            height=height,
            node_positions=node_positions,
            edge_paths=edge_paths,
        )

    def _quote_identifier(self, raw: str) -> str:
        return f'"{self._escape_identifier(raw)}"'

    def _escape_identifier(self, raw: str) -> str:
        return raw.replace("\\", "\\\\").replace('"', '\\"')

    def _escape_label(self, raw: str) -> str:
        return raw.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


class LayeredLayoutEngine:
    def layout(self, snapshot: GraphSnapshot) -> LayoutResult:
        graph = nx.DiGraph()
        for node_id in snapshot.nodes:
            graph.add_node(node_id)
        for edge in snapshot.edges:
            graph.add_edge(edge.source, edge.target)

        if graph.number_of_nodes() == 0:
            return LayoutResult("layered", 0.0, 0.0, {}, {})

        try:
            generations = list(nx.topological_generations(graph))
        except nx.NetworkXUnfeasible:
            generations = [sorted(snapshot.nodes.keys())]

        positions: dict[str, NodePlacement] = {}
        max_rows = max(len(generation) for generation in generations)
        for column, generation in enumerate(generations):
            for row, node_id in enumerate(sorted(generation)):
                positions[node_id] = NodePlacement(
                    x=column * 18.0 + 4.0,
                    y=(max_rows - row) * 6.0,
                    width=max(10.0, min(24.0, len(snapshot.nodes[node_id].label) * 0.7)),
                    height=3.0,
                )

        edge_paths: dict[tuple[str, str, str], EdgePlacement] = {}
        for edge in snapshot.edges:
            if edge.source not in positions or edge.target not in positions:
                continue
            source = positions[edge.source]
            target = positions[edge.target]
            mid_x = (source.x + target.x) / 2
            edge_paths[(edge.source, edge.target, edge.kind.value)] = EdgePlacement(
                points=[
                    (source.x, source.y),
                    (mid_x, source.y),
                    (mid_x, target.y),
                    (target.x, target.y),
                ]
            )

        width = max(position.x + position.width for position in positions.values()) + 4.0
        height = max(position.y + position.height for position in positions.values()) + 4.0
        return LayoutResult(
            engine="layered",
            width=width,
            height=height,
            node_positions=positions,
            edge_paths=edge_paths,
        )


class AutoLayoutEngine:
    def __init__(
        self,
        graphviz: GraphvizLayoutEngine | None = None,
        fallback: LayeredLayoutEngine | None = None,
    ) -> None:
        self.graphviz = graphviz or GraphvizLayoutEngine()
        self.fallback = fallback or LayeredLayoutEngine()

    def layout(self, snapshot: GraphSnapshot) -> LayoutResult:
        try:
            return self.graphviz.layout(snapshot)
        except GraphvizUnavailable:
            return self.fallback.layout(snapshot)
