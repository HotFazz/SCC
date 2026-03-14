from __future__ import annotations

import json
from pathlib import Path

import pytest

from scc.app import SCCApp


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
