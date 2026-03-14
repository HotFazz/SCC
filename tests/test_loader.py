from __future__ import annotations

import json
from pathlib import Path

from scc.loader import ClaudeStateLoader


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def test_loader_builds_graph_from_team_files_and_transcripts(tmp_path: Path) -> None:
    claude_home = tmp_path / ".claude"
    write_json(
        claude_home / "teams/demo/config.json",
        {
            "name": "demo",
            "description": "Demo team",
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
            "owner": "team-lead",
            "blockedBy": [],
        },
    )
    write_json(
        claude_home / "teams/demo/inboxes/worker.json",
        [
            {
                "from": "team-lead",
                "timestamp": "2026-03-14T10:00:00Z",
                "text": json.dumps(
                    {
                        "type": "task_assignment",
                        "taskId": "1",
                        "subject": "Inspect repository",
                    }
                ),
            }
        ],
    )
    write_json(
        claude_home / "teams/demo/inboxes/team-lead.json",
        [
            {
                "from": "worker",
                "timestamp": "2026-03-14T10:01:00Z",
                "text": "Repository review is complete.",
            }
        ],
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
                "timestamp": "2026-03-14T10:00:01Z",
                "cwd": "/tmp/demo",
                "message": {
                    "role": "user",
                    "content": (
                        '<teammate-message teammate_id="team-lead" summary="Inspect repo">'
                        "You are a teammate on the demo team. "
                        "Start by reading your assigned task (#1)."
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
                "timestamp": "2026-03-14T10:00:10Z",
                "cwd": "/tmp/demo",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "The repository structure is clear."}],
                },
            },
        ],
    )

    snapshot = ClaudeStateLoader(claude_home).load()

    assert "team:demo" in snapshot.nodes
    assert "agent:demo:worker" in snapshot.nodes
    assert "task:demo:1" in snapshot.nodes
    assert "turn:user-1" in snapshot.nodes
    assert "turn:assistant-1" in snapshot.nodes
    assert "turn:sub-assistant-1" in snapshot.nodes

    produced_edges = {
        (edge.source, edge.target, edge.kind.value)
        for edge in snapshot.edges
    }
    assert ("team:demo", "agent:demo:worker", "contains") in produced_edges
    assert ("task:demo:1", "agent:demo:worker", "assigned") in produced_edges
    assert ("agent:demo:worker", "turn:sub-assistant-1", "produced") in produced_edges

    timeline_titles = [event.title for event in snapshot.timeline]
    assert "Task #1 assigned to worker" in timeline_titles

