from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class NodeKind(StrEnum):
    TEAM = "team"
    AGENT = "agent"
    USER_REQUEST = "user_request"
    MODEL_TURN = "model_turn"
    TASK = "task"


class EdgeKind(StrEnum):
    CONTAINS = "contains"
    ROUTED_TO = "routed_to"
    PRODUCED = "produced"
    PARENT = "parent"
    ASSIGNED = "assigned"
    DISPATCHED = "dispatched"
    BLOCKED_BY = "blocked_by"
    SUMMARIZED_TO = "summarized_to"


@dataclass(slots=True)
class GraphNode:
    id: str
    kind: NodeKind
    label: str
    cluster: str | None = None
    status: str | None = None
    session_id: str | None = None
    agent_id: str | None = None
    timestamp: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class GraphEdge:
    source: str
    target: str
    kind: EdgeKind
    label: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TimelineEvent:
    id: str
    timestamp: str | None
    kind: str
    title: str
    detail: str | None = None
    source_node_id: str | None = None
    team: str | None = None
    session_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class GraphSnapshot:
    nodes: dict[str, GraphNode] = field(default_factory=dict)
    edges: list[GraphEdge] = field(default_factory=list)
    timeline: list[TimelineEvent] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    _edge_index: set[tuple[str, str, EdgeKind]] = field(
        default_factory=set,
        init=False,
        repr=False,
    )

    def upsert_node(self, node: GraphNode) -> GraphNode:
        existing = self.nodes.get(node.id)
        if existing is None:
            self.nodes[node.id] = node
            return node

        if node.label and existing.label != node.label:
            existing.label = node.label
        if node.cluster and not existing.cluster:
            existing.cluster = node.cluster
        if node.status:
            existing.status = node.status
        if node.session_id and not existing.session_id:
            existing.session_id = node.session_id
        if node.agent_id and not existing.agent_id:
            existing.agent_id = node.agent_id
        if node.timestamp and not existing.timestamp:
            existing.timestamp = node.timestamp
        if node.metadata:
            existing.metadata.update(node.metadata)
        return existing

    def add_edge(self, edge: GraphEdge) -> None:
        key = (edge.source, edge.target, edge.kind)
        if key in self._edge_index:
            return
        self._edge_index.add(key)
        self.edges.append(edge)

    def add_event(self, event: TimelineEvent) -> None:
        self.timeline.append(event)

    def sorted_timeline(self) -> list[TimelineEvent]:
        return sorted(self.timeline, key=lambda item: (item.timestamp or "", item.id))

    def to_dict(self) -> dict[str, Any]:
        return {
            "counts": {
                "nodes": len(self.nodes),
                "edges": len(self.edges),
                "timeline_events": len(self.timeline),
            },
            "warnings": list(self.warnings),
            "nodes": [
                {
                    "id": node.id,
                    "kind": node.kind.value,
                    "label": node.label,
                    "cluster": node.cluster,
                    "status": node.status,
                    "session_id": node.session_id,
                    "agent_id": node.agent_id,
                    "timestamp": node.timestamp,
                    "metadata": node.metadata,
                }
                for node in sorted(self.nodes.values(), key=lambda item: item.id)
            ],
            "edges": [
                {
                    "source": edge.source,
                    "target": edge.target,
                    "kind": edge.kind.value,
                    "label": edge.label,
                    "metadata": edge.metadata,
                }
                for edge in sorted(
                    self.edges,
                    key=lambda item: (item.source, item.target, item.kind.value),
                )
            ],
            "timeline": [
                {
                    "id": event.id,
                    "timestamp": event.timestamp,
                    "kind": event.kind,
                    "title": event.title,
                    "detail": event.detail,
                    "source_node_id": event.source_node_id,
                    "team": event.team,
                    "session_id": event.session_id,
                    "metadata": event.metadata,
                }
                for event in self.sorted_timeline()
            ],
        }

