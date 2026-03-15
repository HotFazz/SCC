from __future__ import annotations

from textual import events, on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Static

from scc.board import BoardCard, BoardMilestone
from scc.domain import GraphSnapshot
from scc.query_flow import QueryFlowBuilder, QueryFlowModel, QuerySection, WorkerFlow


class BoardCardWidget(Vertical):
    DEFAULT_CSS = """
    BoardCardWidget {
      height: auto;
      min-height: 7;
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

    BoardCardWidget.lane-final {
      border: round #3f7d31;
      background: #21391a;
    }

    BoardCardWidget .card-token {
      color: $text-muted;
      text-style: bold;
    }

    BoardCardWidget .card-title {
      margin-top: 1;
      text-style: bold;
    }

    BoardCardWidget .card-subtitle {
      margin-top: 1;
      color: $text-muted;
    }

    BoardCardWidget .card-body {
      margin-top: 1;
      color: $text;
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
        selected: bool = False,
        extra_classes: str = "",
    ) -> None:
        classes = f"board-card lane-{card.lane}"
        if extra_classes:
            classes += f" {extra_classes}"
        if selected:
            classes += " is-selected"
        super().__init__(classes=classes, id=f"card-{card.card_id}")
        self.card = card

    @property
    def preferred_node_id(self) -> str | None:
        if self.card.preferred_node_id:
            return self.card.preferred_node_id
        if not self.card.node_ids:
            return None
        return sorted(self.card.node_ids)[0]

    def compose(self) -> ComposeResult:
        yield Static(self.card.card_id, classes="card-token")
        yield Static(self.card.title, classes="card-title")
        if self.card.subtitle:
            yield Static(self.card.subtitle, classes="card-subtitle")
        for line in self.card.body_lines[: self.card.max_body_lines]:
            yield Static(line, classes="card-body")

    def on_click(self, event: events.Click) -> None:
        event.stop()
        if self.preferred_node_id:
            self.post_message(self.Selected(self.preferred_node_id))


class WorkerFlowWidget(Vertical):
    DEFAULT_CSS = """
    WorkerFlowWidget {
      width: 34;
      min-width: 30;
      max-width: 38;
      height: auto;
      margin-right: 1;
    }

    WorkerFlowWidget {
      padding: 1;
      border: round #2563eb;
      background: #0f1f39;
    }

    WorkerFlowWidget:hover {
      background: #13274a;
    }

    WorkerFlowWidget.is-selected {
      border: heavy $accent;
      background: $boost;
    }

    WorkerFlowWidget .card-token {
      color: $text-muted;
      text-style: bold;
    }

    WorkerFlowWidget .task-title {
      margin-top: 1;
      text-style: bold;
    }

    WorkerFlowWidget .task-subtitle {
      margin-top: 1;
      color: $text-muted;
    }

    WorkerFlowWidget .worker-title {
      margin-top: 1;
      color: #7dd3fc;
      text-style: bold;
    }

    WorkerFlowWidget .worker-subtitle {
      margin-top: 1;
      color: $text-muted;
    }

    WorkerFlowWidget .milestone-stack {
      margin-top: 1;
      height: auto;
    }

    WorkerFlowWidget .flow-log {
      margin-top: 1;
      height: 10;
      max-height: 10;
      border: round #15803d;
      background: #0d2a18;
      overflow-y: auto;
      padding: 0 1;
    }

    WorkerFlowWidget .flow-line {
      margin-top: 1;
      color: $text;
    }
    """

    def __init__(self, flow: WorkerFlow, selected_card_id: str | None) -> None:
        classes = "worker-flow"
        if selected_card_id == flow.card.card_id:
            classes += " is-selected"
        super().__init__(classes=classes, id=f"card-{flow.card.card_id}")
        self.flow = flow
        self.selected_card_id = selected_card_id

    @property
    def preferred_node_id(self) -> str | None:
        if self.flow.card.preferred_node_id:
            return self.flow.card.preferred_node_id
        if not self.flow.card.node_ids:
            return None
        return sorted(self.flow.card.node_ids)[0]

    def compose(self) -> ComposeResult:
        yield Static(self.flow.card.card_id, classes="card-token")
        yield Static(self.flow.card.title, classes="task-title")
        if self.flow.card.subtitle:
            yield Static(self.flow.card.subtitle, classes="task-subtitle")
        if self.flow.card.body_lines:
            yield Static(self.flow.card.body_lines[0], classes="worker-title")
        if len(self.flow.card.body_lines) > 1:
            yield Static(self.flow.card.body_lines[1], classes="worker-subtitle")
        if self.flow.card.milestones:
            with Vertical(classes="milestone-stack"):
                for milestone in self.flow.card.milestones:
                    yield MilestoneWidget(milestone)
        with VerticalScroll(classes="flow-log"):
            for line in self.flow.card.progress_lines:
                yield Static(line, classes="flow-line", markup=False)

    def on_click(self, event: events.Click) -> None:
        event.stop()
        if self.preferred_node_id:
            self.post_message(BoardCardWidget.Selected(self.preferred_node_id))


class MilestoneWidget(Vertical):
    DEFAULT_CSS = """
    MilestoneWidget {
      height: auto;
      margin-top: 1;
      padding: 0 1;
      border: round #2d5a9b;
      background: #102341;
    }

    MilestoneWidget.kind-assignment {
      border: round #3b82f6;
      background: #10203a;
    }

    MilestoneWidget.kind-progress {
      border: round #2563eb;
      background: #102341;
    }

    MilestoneWidget.kind-hook {
      border: round #7c3aed;
      background: #20153d;
    }

    MilestoneWidget.kind-report {
      border: round #16a34a;
      background: #0f2b18;
    }

    MilestoneWidget.kind-complete {
      border: round #15803d;
      background: #12331d;
    }

    MilestoneWidget .milestone-token {
      color: $text-muted;
      text-style: bold;
    }

    MilestoneWidget .milestone-title {
      text-style: bold;
    }

    MilestoneWidget .milestone-subtitle {
      color: $text-muted;
    }
    """

    def __init__(self, milestone: BoardMilestone) -> None:
        super().__init__(classes=f"milestone kind-{milestone.kind}")
        self.milestone = milestone

    def compose(self) -> ComposeResult:
        if self.milestone.timestamp:
            yield Static(self.milestone.timestamp, classes="milestone-token")
        yield Static(self.milestone.title, classes="milestone-title")
        if self.milestone.subtitle:
            yield Static(self.milestone.subtitle, classes="milestone-subtitle")


class QuerySectionWidget(Vertical):
    DEFAULT_CSS = """
    QuerySectionWidget {
      height: auto;
      margin-bottom: 2;
    }

    QuerySectionWidget .request-row {
      height: auto;
      margin-bottom: 1;
    }

    QuerySectionWidget .request-wrap {
      height: auto;
    }

    QuerySectionWidget .cluster-shell {
      height: auto;
      padding: 1;
      border: round $panel-lighten-1;
      background: $surface;
    }

    QuerySectionWidget .cluster-main {
      height: auto;
    }

    QuerySectionWidget .lead-wrap {
      height: auto;
    }

    QuerySectionWidget .workers-strip {
      width: 1fr;
      height: auto;
    }

    QuerySectionWidget .empty-workers {
      color: $text-muted;
      padding: 2 1;
    }

    QuerySectionWidget .cluster-footer {
      height: auto;
      margin-top: 1;
    }

    QuerySectionWidget .final-wrap {
      height: auto;
    }

    QuerySectionWidget .request-card {
      width: 52;
      min-width: 40;
      height: auto;
    }

    QuerySectionWidget .lead-card {
      width: 32;
      min-width: 28;
      height: auto;
      margin-right: 2;
    }

    QuerySectionWidget .final-card {
      width: 64;
      min-width: 48;
      height: auto;
    }
    """

    def __init__(self, section: QuerySection, selected_card_id: str | None) -> None:
        super().__init__(classes="query-section")
        self.section = section
        self.selected_card_id = selected_card_id

    def compose(self) -> ComposeResult:
        with Horizontal(classes="request-row"):
            yield BoardCardWidget(
                self.section.request_card,
                selected=self.selected_card_id == self.section.request_card.card_id,
                extra_classes="request-card",
            )

        with Vertical(classes="cluster-shell"):
            with Horizontal(classes="cluster-main"):
                if self.section.lead_card is not None:
                    yield BoardCardWidget(
                        self.section.lead_card,
                        selected=self.selected_card_id == self.section.lead_card.card_id,
                        extra_classes="lead-card",
                    )
                with Horizontal(classes="workers-strip"):
                    if self.section.worker_flows:
                        for flow in self.section.worker_flows:
                            yield WorkerFlowWidget(flow, self.selected_card_id)
                    else:
                        yield Static("No delegated work in this query window.", classes="empty-workers")
            if self.section.final_card is not None:
                with Horizontal(classes="cluster-footer"):
                    yield BoardCardWidget(
                        self.section.final_card,
                        selected=self.selected_card_id == self.section.final_card.card_id,
                        extra_classes="final-card",
                    )


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
    """

    class CardSelected(Message):
        def __init__(self, node_id: str) -> None:
            super().__init__()
            self.node_id = node_id

    def __init__(self) -> None:
        super().__init__(id="board")
        self.builder = QueryFlowBuilder()
        self.model = QueryFlowModel(title="No focus", sections=[], selected_card_id=None)

    def update_from_snapshot(
        self,
        snapshot: GraphSnapshot,
        selected_node_id: str | None = None,
    ) -> None:
        self.model = self.builder.build(snapshot, selected_node_id=selected_node_id)
        self.refresh(layout=True, recompose=True)

    def compose(self) -> ComposeResult:
        yield Static(self.model.title, id="board-title")
        if not self.model.sections:
            yield Static("No query flow available for the current focus.", classes="board-empty")
            return

        for section in self.model.sections:
            yield QuerySectionWidget(section, self.model.selected_card_id)

    @on(BoardCardWidget.Selected)
    def handle_card_selected(self, message: BoardCardWidget.Selected) -> None:
        message.stop()
        self.post_message(self.CardSelected(message.node_id))
