from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from textwrap import wrap

from scc.board import BoardBuilder, BoardCard, BoardConnection, BoardModel, BoardRow, LANE_ORDER, LANE_TITLES
from scc.domain import GraphSnapshot


@dataclass(slots=True)
class GraphDocument:
    text: str
    width: int
    height: int
    boxes: dict[str, tuple[int, int, int, int]] = field(default_factory=dict)


@dataclass(slots=True)
class CardPlacement:
    row_index: int
    lane: str


class AsciiGraphRenderer:
    def __init__(self, lane_width: int = 28, gutter_width: int = 7, max_body_lines: int = 5) -> None:
        self.lane_width = lane_width
        self.gutter_width = gutter_width
        self.max_body_lines = max_body_lines
        self.builder = BoardBuilder()

    def render(
        self,
        snapshot: GraphSnapshot,
        selected_node_id: str | None = None,
    ) -> GraphDocument:
        if not snapshot.nodes:
            return GraphDocument("No graph data available for the current focus.", 44, 1)

        board = self.builder.build(snapshot, selected_node_id=selected_node_id)
        if not board.rows:
            return GraphDocument("No graph data available for the current focus.", 44, 1)

        placements = self._placements(board)
        lines = [
            f"Board view: {board.title}",
            "",
            self._lane_header(),
            self._lane_rule(),
        ]
        for row_index, row in enumerate(board.rows):
            lines.extend(self._render_row(row_index, row, board, placements))
            if row_index < len(board.rows) - 1:
                connector_gap = self._render_gap(row_index, board, placements)
                lines.extend(connector_gap or [""])
            else:
                lines.append("")

        offboard = self._offboard_connections(board, placements)
        lines.append("Relation Notes")
        lines.append("--------------")
        for connection in offboard[:18]:
            lines.append(
                self._shorten(
                    f"{connection.source_id} {self._arrow(connection.kind)} {connection.target_id}  {connection.label}"
                )
            )
        if not offboard:
            lines.append("All primary flows are visible in the board.")
        elif len(offboard) > 18:
            lines.append(f"... {len(offboard) - 18} more relationships hidden")

        width = max(len(line) for line in lines) if lines else 0
        return GraphDocument("\n".join(lines), width=width, height=len(lines))

    def _lane_header(self) -> str:
        return self._join_columns(
            [title.center(self.lane_width) for title in (LANE_TITLES[lane] for lane in LANE_ORDER)]
        )

    def _lane_rule(self) -> str:
        return self._join_columns(["=" * self.lane_width for _ in LANE_ORDER])

    def _render_row(
        self,
        row_index: int,
        row: BoardRow,
        board: BoardModel,
        placements: dict[str, CardPlacement],
    ) -> list[str]:
        rendered = {
            lane: self._render_card(row.cells[lane], board.selected_card_id == row.cells[lane].card_id)
            for lane in LANE_ORDER
            if lane in row.cells
        }
        row_height = max((len(lines) for lines in rendered.values()), default=0)
        if row_height == 0:
            return []
        padded = {
            lane: lines + [" " * self.lane_width] * (row_height - len(lines))
            for lane, lines in rendered.items()
        }
        output = []
        for index in range(row_height):
            parts = []
            for lane_index, lane in enumerate(LANE_ORDER):
                parts.append(padded.get(lane, [" " * self.lane_width] * row_height)[index])
                if lane_index < len(LANE_ORDER) - 1:
                    next_lane = LANE_ORDER[lane_index + 1]
                    parts.append(
                        self._gutter(
                            row_index,
                            row,
                            lane,
                            next_lane,
                            board,
                            placements,
                            index,
                            row_height,
                        )
                    )
            output.append("".join(parts).rstrip())
        return output

    def _render_card(self, card: BoardCard, selected: bool) -> list[str]:
        corner = "#" if selected else "+"
        horizontal = "#" if selected else "-"
        vertical = "#" if selected else "|"
        inner_width = self.lane_width - 4
        title = self._shorten(f"{card.card_id} {card.title}", inner_width)
        subtitle = self._shorten(card.subtitle or "", inner_width)
        body = self._wrap_body(card.body_lines, inner_width)
        if not body:
            body = [""]
        lines = [corner + horizontal * (self.lane_width - 2) + corner]
        lines.append(f"{vertical} {title.ljust(inner_width)} {vertical}")
        lines.append(f"{vertical} {subtitle.ljust(inner_width)} {vertical}")
        for line in body:
            lines.append(f"{vertical} {line.ljust(inner_width)} {vertical}")
        lines.append(corner + horizontal * (self.lane_width - 2) + corner)
        return lines

    def _gutter(
        self,
        row_index: int,
        row: BoardRow,
        left_lane: str,
        right_lane: str,
        board: BoardModel,
        placements: dict[str, CardPlacement],
        line_index: int,
        row_height: int,
    ) -> str:
        left = row.cells.get(left_lane)
        right = row.cells.get(right_lane)
        direct = self._direct_connection(board, left, right)
        incoming = self._incoming_connection(board, placements, row_index, left_lane, right)
        if line_index != row_height // 2:
            return " " * self.gutter_width
        if direct:
            return self._arrow(direct.kind).center(self.gutter_width)
        if incoming:
            return self._arrow(incoming.kind).center(self.gutter_width)
        return " " * self.gutter_width

    def _render_gap(
        self,
        row_index: int,
        board: BoardModel,
        placements: dict[str, CardPlacement],
    ) -> list[str]:
        columns = [" " * self.lane_width]
        for lane_index, left_lane in enumerate(LANE_ORDER[:-1]):
            right_lane = LANE_ORDER[lane_index + 1]
            columns.append(self._gap_gutter(row_index, left_lane, right_lane, board, placements))
            columns.append(" " * self.lane_width)
        return [self._join_parts(columns).rstrip()]

    def _gap_gutter(
        self,
        row_index: int,
        left_lane: str,
        right_lane: str,
        board: BoardModel,
        placements: dict[str, CardPlacement],
    ) -> str:
        for connection in board.connections:
            source = placements.get(connection.source_id)
            target = placements.get(connection.target_id)
            if not source or not target:
                continue
            if source.lane != left_lane or target.lane != right_lane:
                continue
            if source.row_index <= row_index < target.row_index:
                return "|".center(self.gutter_width)
        return " " * self.gutter_width

    def _arrow(self, kind: str) -> str:
        if kind == "blocked":
            return "-x>"
        return "-->"

    def _wrap_body(self, lines: list[str], width: int) -> list[str]:
        wrapped: list[str] = []
        truncated = False
        for line in lines:
            chunks = wrap(line, width=width, break_long_words=True, break_on_hyphens=False) or [""]
            for chunk in chunks:
                if len(wrapped) == self.max_body_lines:
                    truncated = True
                    break
                wrapped.append(chunk)
            if truncated:
                break
        if truncated and wrapped:
            wrapped[-1] = self._shorten(wrapped[-1], width)
        return wrapped

    def _shorten(self, text: str, width: int | None = None) -> str:
        max_width = width if width is not None else self.lane_width - 4
        if len(text) <= max_width:
            return text
        if max_width <= 3:
            return text[:max_width]
        return text[: max_width - 3].rstrip() + "..."

    def _join_columns(self, columns: list[str]) -> str:
        separator = " " * self.gutter_width
        return separator.join(columns)

    def _join_parts(self, parts: Iterable[str]) -> str:
        return "".join(parts)

    def _placements(self, board: BoardModel) -> dict[str, CardPlacement]:
        placements: dict[str, CardPlacement] = {}
        for row_index, row in enumerate(board.rows):
            for lane, card in row.cells.items():
                placements[card.card_id] = CardPlacement(row_index=row_index, lane=lane)
        return placements

    def _direct_connection(
        self,
        board: BoardModel,
        left: BoardCard | None,
        right: BoardCard | None,
    ) -> BoardConnection | None:
        if not left or not right:
            return None
        return next(
            (
                connection
                for connection in board.connections
                if connection.source_id == left.card_id and connection.target_id == right.card_id
            ),
            None,
        )

    def _incoming_connection(
        self,
        board: BoardModel,
        placements: dict[str, CardPlacement],
        row_index: int,
        left_lane: str,
        right: BoardCard | None,
    ) -> BoardConnection | None:
        if not right:
            return None
        for connection in board.connections:
            if connection.target_id != right.card_id:
                continue
            source = placements.get(connection.source_id)
            if not source:
                continue
            if source.lane == left_lane and source.row_index < row_index:
                return connection
        return None

    def _offboard_connections(
        self,
        board: BoardModel,
        placements: dict[str, CardPlacement],
    ) -> list[BoardConnection]:
        offboard: list[BoardConnection] = []
        for connection in board.connections:
            source = placements.get(connection.source_id)
            target = placements.get(connection.target_id)
            if not source or not target:
                continue
            if target.row_index == source.row_index and self._lane_distance(source.lane, target.lane) == 1:
                continue
            if source.lane == target.lane:
                offboard.append(connection)
                continue
            if target.row_index > source.row_index and self._lane_distance(source.lane, target.lane) == 1:
                continue
            offboard.append(connection)
        return offboard

    def _lane_distance(self, source_lane: str, target_lane: str) -> int:
        return abs(LANE_ORDER.index(source_lane) - LANE_ORDER.index(target_lane))
