from __future__ import annotations

import json
from pathlib import Path

import pytest
from textual.containers import VerticalScroll

from scc.app import SCCApp
from scc.board_view import BoardCardWidget, MilestoneWidget, WorkerFlowWidget


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


@pytest.mark.anyio
async def test_app_mounts_headlessly(tmp_path: Path) -> None:
    claude_home = tmp_path / ".claude"
    (claude_home / "projects").mkdir(parents=True)
    (claude_home / "teams").mkdir(parents=True)
    (claude_home / "tasks").mkdir(parents=True)

    app = SCCApp(claude_home=claude_home, workspace=tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one("#focus").value == "all"
        assert len(app.query("#prompt")) == 0
        assert len(app.query("#send")) == 0
        assert len(app.query("#reload")) == 0


@pytest.mark.anyio
async def test_app_renders_board_cards_for_team_focus(tmp_path: Path) -> None:
    claude_home = tmp_path / ".claude"
    write_json(
        claude_home / "teams/demo/config.json",
        {
            "name": "demo",
            "leadAgentId": "team-lead@demo",
            "leadSessionId": "session-1",
            "members": [
                {
                    "agentId": "team-lead@demo",
                    "name": "team-lead",
                    "agentType": "team-lead",
                    "model": "claude-opus",
                },
                {
                    "agentId": "worker@demo",
                    "name": "worker",
                    "agentType": "general-purpose",
                    "model": "claude-sonnet",
                },
            ],
        },
    )
    write_json(
        claude_home / "tasks/demo/1.json",
        {
            "subject": "Inspect repository",
            "description": "Review the codebase",
            "status": "in_progress",
            "owner": "worker",
            "blockedBy": [],
        },
    )
    write_jsonl(
        claude_home / "projects/workspace/session-1.jsonl",
        [
            {
                "type": "user",
                "uuid": "user-1",
                "parentUuid": None,
                "sessionId": "session-1",
                "teamName": "demo",
                "timestamp": "2026-03-14T09:59:00Z",
                "cwd": "/tmp/demo",
                "message": {"role": "user", "content": "Please inspect the repo."},
            },
            {
                "type": "assistant",
                "uuid": "assistant-1",
                "parentUuid": "user-1",
                "sessionId": "session-1",
                "teamName": "demo",
                "timestamp": "2026-03-14T09:59:05Z",
                "cwd": "/tmp/demo",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Creating a team and assigning work."}],
                },
            },
        ],
    )

    app = SCCApp(claude_home=claude_home, workspace=tmp_path)
    async with app.run_test(size=(180, 48)) as pilot:
        await pilot.pause()
        app.focus_value = "team:demo"
        app._refresh_focus()
        await pilot.pause()
        cards = list(app.query(".board-card"))
        assert len(cards) >= 3


@pytest.mark.anyio
async def test_app_keeps_lead_card_visible_under_request_in_session_focus(tmp_path: Path) -> None:
    claude_home = tmp_path / ".claude"
    write_jsonl(
        claude_home / "projects/workspace/session-1.jsonl",
        [
            {
                "type": "user",
                "uuid": "user-1",
                "parentUuid": None,
                "sessionId": "session-1",
                "timestamp": "2026-03-14T09:59:00Z",
                "cwd": "/tmp/demo",
                "message": {"role": "user", "content": "Whip up a swarm to inspect the repo."},
            },
            {
                "type": "assistant",
                "uuid": "assistant-1",
                "parentUuid": "user-1",
                "sessionId": "session-1",
                "timestamp": "2026-03-14T09:59:05Z",
                "cwd": "/tmp/demo",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Agent: Explore domain model"}],
                },
            },
            {
                "type": "assistant",
                "uuid": "assistant-2",
                "parentUuid": "assistant-1",
                "sessionId": "session-1",
                "timestamp": "2026-03-14T09:59:20Z",
                "cwd": "/tmp/demo",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Here's what the swarm found."}],
                },
            },
        ],
    )
    write_jsonl(
        claude_home / "projects/workspace/session-1/subagents/agent-worker.jsonl",
        [
            {
                "type": "user",
                "uuid": "sub-user-1",
                "parentUuid": None,
                "sessionId": "session-1",
                "agentId": "runtime-worker",
                "isSidechain": True,
                "timestamp": "2026-03-14T09:59:06Z",
                "cwd": "/tmp/demo",
                "message": {
                    "role": "user",
                    "content": (
                        '<teammate-message teammate_id="team-lead" summary="Inspect repo">'
                        "Research only (no edits). Read the repo."
                        "</teammate-message>"
                    ),
                },
            },
            {
                "type": "assistant",
                "uuid": "sub-assistant-1",
                "parentUuid": "sub-user-1",
                "sessionId": "session-1",
                "agentId": "runtime-worker",
                "isSidechain": True,
                "timestamp": "2026-03-14T09:59:12Z",
                "cwd": "/tmp/demo",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Repo structure complete."}],
                },
            },
        ],
    )

    app = SCCApp(claude_home=claude_home, workspace=tmp_path)
    async with app.run_test(size=(180, 48)) as pilot:
        await pilot.pause()
        app.focus_value = "session:session-1"
        app._refresh_focus()
        await pilot.pause()

        request_card = app.query_one("#card-Q1", BoardCardWidget)
        lead_card = app.query_one("#card-L1", BoardCardWidget)
        worker_card = app.query_one("#card-W1", WorkerFlowWidget)
        log_box = worker_card.query_one(".flow-log", VerticalScroll)
        milestone = worker_card.query_one(MilestoneWidget)

        assert request_card.region.y < lead_card.region.y
        assert lead_card.region.y - request_card.region.y < 20
        assert lead_card.region.height > request_card.region.height
        assert worker_card.region.y - request_card.region.y < 30
        assert log_box.region.y < milestone.region.y


@pytest.mark.anyio
async def test_app_preserves_selected_focus_across_snapshot_reload(tmp_path: Path) -> None:
    claude_home = tmp_path / ".claude"
    write_jsonl(
        claude_home / "projects/workspace/session-1.jsonl",
        [
            {
                "type": "user",
                "uuid": "user-1",
                "parentUuid": None,
                "sessionId": "session-1",
                "timestamp": "2026-03-14T09:59:00Z",
                "cwd": "/tmp/demo",
                "message": {"role": "user", "content": "First"},
            }
        ],
    )
    write_jsonl(
        claude_home / "projects/workspace/session-2.jsonl",
        [
            {
                "type": "user",
                "uuid": "user-2",
                "parentUuid": None,
                "sessionId": "session-2",
                "timestamp": "2026-03-14T10:00:00Z",
                "cwd": "/tmp/demo",
                "message": {"role": "user", "content": "Second"},
            }
        ],
    )

    app = SCCApp(claude_home=claude_home, workspace=tmp_path)
    async with app.run_test(size=(180, 48)) as pilot:
        await pilot.pause()
        focus = app.query_one("#focus")
        focus.value = "session:session-1"
        await pilot.pause()
        assert app.focus_value == "session:session-1"

        app._apply_snapshot(app.loader.load())
        await pilot.pause()

        assert app.focus_value == "session:session-1"
        assert focus.value == "session:session-1"
