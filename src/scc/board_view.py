from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from textual import events, on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Static

from scc.board import BoardBuilder, BoardCard, BoardConnection, BoardModel, LANE_ORDER, LANE_TITLES
from scc.domain import GraphSnapshot


@dataclass(slots=True)
class CardRelations:
    incoming: list[str]
    outgoing: list[str]


class BoardCardWidget(Vertical):
    DEFAULT_CSS = """
    BoardCardWidget {
      height: auto;
      min-height: 8;
      padding: 1;
      border: round $panel-lighten-1;
      background: $panel;
    }

    BoardCardWidget:hover {
      background: $panel-lighten-1;
    }

    BoardCardWidget.is-selected {
      border: heavy $accent;
      background: $boost;
    }

    BoardCardWidget.lane-requests {
      border: round #1d7874;
      background: #0f2d2b;
    }

    BoardCardWidget.lane-lead {
      border: round #d97706;
      background: #352108;
    }

    BoardCardWidget.lane-tasks {
      border: round #2563eb;
      background: #11213d;
    }

    BoardCardWidget.lane-workers {
      border: round #15803d;
      background: #0f2b18;
    }

    BoardCardWidget.lane-summaries {
      border: round #c2410c;
      background: #35190c;
    }

    BoardCardWidget:focus {
      border: heavy $accent-lighten-1;
    }

    BoardCardWidget .card-token {
      color: $text-muted;
      text-style: bold;
    }

    BoardCardWidget .card-title {
      text-style: bold;
      margin-top: 1;
    }

    BoardCardWidget .card-subtitle {
      color: $text-muted;
      margin-top: 1;
    }

    BoardCardWidget .card-body {
      margin-top: 1;
      color: $text;
    }

    BoardCardWidget .card-relations {
      margin-top: 1;
      color: $text-muted;
    }
    """

    class Selected(Message):
        def __init__(self, node_id: str) -> None:
            super().__init__()
            self.node_id = node_id

    can_focus = True

    def __init__(
        self,
        card: BoardCard,
        relations: CardRelations,
        selected: bool = False,
    ) -> None:
        classes = f"board-card lane-{card.lane}"
        if selected:
            classes += " is-selected"
        super().__init__(classes=classes, id=f"card-{card.card_id}")
        self.card = card
        self.relations = relations

    @property
    def preferred_node_id(self) -> str | None:
        if not self.card.node_ids:
            return None
        return sorted(self.card.node_ids)[0]

    def compose(self) -> ComposeResult:
        yield Static(self.card.card_id, classes="card-token")
        yield Static(self.card.title, classes="card-title")
        if self.card.subtitle:
            yield Static(self.card.subtitle, classes="card-subtitle")
        for line in self.card.body_lines[:4]:
            yield Static(line, classes="card-body")
        relation_text = self._relation_text()
        if relation_text:
            yield Static(relation_text, classes="card-relations")

    def on_click(self, event: events.Click) -> None:
        event.stop()
        if self.preferred_node_id:
            self.post_message(self.Selected(self.preferred_node_id))

    def _relation_text(self) -> str:
        labels = self.relations.incoming[:1] + self.relations.outgoing[:2]
        return "  |  ".join(labels)


class SwarmBoard(Vertical):
    DEFAULT_CSS = """
    SwarmBoard {
      width: 180;
      min-width: 140;
      height: auto;
    }

    SwarmBoard #board-title {
      padding: 0 1 1 1;
      color: $text-muted;
      text-style: bold;
    }

    SwarmBoard .board-empty {
      padding: 1;
      color: $text-muted;
    }

    SwarmBoard .board-header {
      height: 3;
      margin-bottom: 1;
    }

    SwarmBoard .lane-header {
      width: 1fr;
      min-width: 24;
      content-align: center middle;
      text-style: bold;
      color: $text;
      background: $surface;
      border: tall $panel-lighten-1;
    }

    SwarmBoard .board-body {
      height: auto;
    }

    SwarmBoard .board-row {
      height: auto;
      margin-bottom: 1;
    }

    SwarmBoard .board-cell {
      width: 1fr;
      min-width: 24;
      height: auto;
      padding: 0 1;
    }

    SwarmBoard .board-spacer {
      height: 1;
    }
    """

    class CardSelected(Message):
        def __init__(self, node_id: str) -> None:
            super().__init__()
            self.node_id = node_id

    def __init__(self) -> None:
        super().__init__(id="board")
        self.builder = BoardBuilder()
        self.model = BoardModel(title="No focus", rows=[], connections=[], selected_card_id=None)

    def update_from_snapshot(
        self,
        snapshot: GraphSnapshot,
        selected_node_id: str | None = None,
    ) -> None:
        self.model = self.builder.build(snapshot, selected_node_id=selected_node_id)
        self.refresh(layout=True, recompose=True)

    def compose(self) -> ComposeResult:
        yield Static(self.model.title, id="board-title")
        if not self.model.rows:
            yield Static("No graph data available for the current focus.", classes="board-empty")
            return

        with Horizontal(classes="board-header"):
            for lane in LANE_ORDER:
                yield Static(LANE_TITLES[lane], classes="lane-header")

        relation_map = self._relation_map()
        with Vertical(classes="board-body"):
            for row in self.model.rows:
                with Horizontal(classes="board-row"):
                    for lane in LANE_ORDER:
                        card = row.cells.get(lane)
                        with Vertical(classes=f"board-cell lane-{lane}"):
                            if card is None:
                                yield Static("", classes="board-spacer")
                            else:
                                yield BoardCardWidget(
                                    card,
                                    relations=relation_map[card.card_id],
                                    selected=self.model.selected_card_id == card.card_id,
                                )

    @on(BoardCardWidget.Selected)
    def handle_card_selected(self, message: BoardCardWidget.Selected) -> None:
        message.stop()
        self.post_message(self.CardSelected(message.node_id))

    def _relation_map(self) -> dict[str, CardRelations]:
        incoming: dict[str, list[str]] = defaultdict(list)
        outgoing: dict[str, list[str]] = defaultdict(list)
        for connection in self.model.connections:
            outgoing[connection.source_id].append(self._format_relation(connection, target=True))
            incoming[connection.target_id].append(self._format_relation(connection, target=False))
        card_ids = {card.card_id for row in self.model.rows for card in row.cells.values()}
        return {
            card_id: CardRelations(
                incoming=incoming.get(card_id, []),
                outgoing=outgoing.get(card_id, []),
            )
            for card_id in card_ids
        }

    def _format_relation(self, connection: BoardConnection, target: bool) -> str:
        other_id = connection.target_id if target else connection.source_id
        if connection.kind == "blocked":
            prefix = "blocks" if target else "blocked by"
            return f"{prefix} {other_id}"
        prefix = connection.label or connection.kind
        return f"{prefix} {other_id}"
