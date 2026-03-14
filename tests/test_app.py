from __future__ import annotations

from pathlib import Path

import pytest

from scc.app import SCCApp


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
