from __future__ import annotations

from dataclasses import dataclass, field

from scc.domain import GraphSnapshot, NodeKind
from scc.layout import LayoutResult, NodePlacement


@dataclass(slots=True)
class GraphDocument:
    text: str
    width: int
    height: int
    boxes: dict[str, tuple[int, int, int, int]] = field(default_factory=dict)


class AsciiGraphRenderer:
    def __init__(self, scale_x: int = 4, scale_y: int = 2) -> None:
        self.scale_x = scale_x
        self.scale_y = scale_y

    def render(
        self,
        snapshot: GraphSnapshot,
        layout: LayoutResult,
        selected_node_id: str | None = None,
    ) -> GraphDocument:
        if not snapshot.nodes or not layout.node_positions:
            return GraphDocument("No graph data available for the current focus.", 44, 1)

        boxes = self._build_boxes(snapshot, layout)
        if not boxes:
            return GraphDocument("Layout produced no renderable node boxes.", 40, 1)
        width = max(left + box_width for left, _, box_width, _ in boxes.values()) + 2
        height = max(top + box_height for _, top, _, box_height in boxes.values()) + 2
        canvas = [[" " for _ in range(width)] for _ in range(height)]

        for edge_key, edge in layout.edge_paths.items():
            points = edge.points
            if len(points) < 2:
                continue
            previous = self._point_to_cell(points[0], layout)
            for point in points[1:]:
                current = self._point_to_cell(point, layout)
                self._draw_segment(canvas, previous, current)
                previous = current

        for node_id, node in snapshot.nodes.items():
            if node_id not in boxes:
                continue
            left, top, box_width, box_height = boxes[node_id]
            label = self._display_label(node.kind, node.label, box_width - 2)
            border = "*" if node_id == selected_node_id else "+"
            horizontal = "*" if node_id == selected_node_id else "-"
            vertical = "*" if node_id == selected_node_id else "|"
            self._draw_box(canvas, left, top, box_width, box_height, border, horizontal, vertical)
            label_row = top + box_height // 2
            label_col = left + max(1, (box_width - len(label)) // 2)
            for index, char in enumerate(label):
                canvas[label_row][label_col + index] = char

        lines = ["".join(row).rstrip() for row in canvas]
        while lines and not lines[-1]:
            lines.pop()

        return GraphDocument("\n".join(lines), width=width, height=len(lines), boxes=boxes)

    def _build_boxes(
        self,
        snapshot: GraphSnapshot,
        layout: LayoutResult,
    ) -> dict[str, tuple[int, int, int, int]]:
        boxes: dict[str, tuple[int, int, int, int]] = {}
        for node_id, placement in layout.node_positions.items():
            if node_id not in snapshot.nodes:
                continue
            label = self._display_label(snapshot.nodes[node_id].kind, snapshot.nodes[node_id].label, 999)
            box_width = max(len(label) + 2, int(placement.width * self.scale_x) + 4)
            box_height = max(3, int(placement.height * self.scale_y))
            left = max(0, int((placement.x - placement.width / 2) * self.scale_x))
            top = max(0, int((layout.height - placement.y - placement.height / 2) * self.scale_y))
            boxes[node_id] = (left, top, box_width, box_height)
        return boxes

    def _point_to_cell(
        self,
        point: tuple[float, float],
        layout: LayoutResult,
    ) -> tuple[int, int]:
        x, y = point
        return int(x * self.scale_x), int((layout.height - y) * self.scale_y)

    def _draw_segment(
        self,
        canvas: list[list[str]],
        start: tuple[int, int],
        end: tuple[int, int],
    ) -> None:
        start_x, start_y = start
        end_x, end_y = end
        if start_x == end_x:
            for row in range(min(start_y, end_y), max(start_y, end_y) + 1):
                canvas[row][start_x] = "|" if canvas[row][start_x] == " " else "+"
            return

        if start_y == end_y:
            for column in range(min(start_x, end_x), max(start_x, end_x) + 1):
                canvas[start_y][column] = "-" if canvas[start_y][column] == " " else "+"
            return

        corner = (end_x, start_y)
        self._draw_segment(canvas, start, corner)
        self._draw_segment(canvas, corner, end)

    def _draw_box(
        self,
        canvas: list[list[str]],
        left: int,
        top: int,
        box_width: int,
        box_height: int,
        corner: str,
        horizontal: str,
        vertical: str,
    ) -> None:
        right = left + box_width - 1
        bottom = top + box_height - 1
        for column in range(left + 1, right):
            canvas[top][column] = horizontal
            canvas[bottom][column] = horizontal
        for row in range(top + 1, bottom):
            canvas[row][left] = vertical
            canvas[row][right] = vertical
        canvas[top][left] = corner
        canvas[top][right] = corner
        canvas[bottom][left] = corner
        canvas[bottom][right] = corner

    def _display_label(self, kind: NodeKind, label: str, width: int) -> str:
        prefix = {
            NodeKind.TEAM: "T",
            NodeKind.AGENT: "A",
            NodeKind.USER_REQUEST: "U",
            NodeKind.MODEL_TURN: "M",
            NodeKind.TASK: "K",
        }[kind]
        text = f"{prefix}: {label}"
        if len(text) <= width:
            return text
        if width <= 4:
            return text[:width]
        return text[: width - 3].rstrip() + "..."
