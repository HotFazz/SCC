from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ClaudeCommandResult:
    ok: bool
    session_id: str | None
    display_text: str
    error: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    return_code: int = 0


class ClaudeCLIClient:
    def __init__(self, executable: str = "claude") -> None:
        self.executable = executable

    def send_prompt(
        self,
        prompt: str,
        workspace: Path,
        resume_session_id: str | None = None,
    ) -> ClaudeCommandResult:
        if shutil.which(self.executable) is None:
            return ClaudeCommandResult(
                ok=False,
                session_id=None,
                display_text="Claude CLI is not installed or not on PATH.",
                error="missing_executable",
                return_code=127,
            )

        command = [self.executable]
        if resume_session_id:
            command.extend(["-r", resume_session_id])
        command.extend(
            [
                "-p",
                "--verbose",
                "--output-format",
                "stream-json",
                "--permission-mode",
                "acceptEdits",
                prompt,
            ]
        )

        try:
            completed = subprocess.run(
                command,
                cwd=str(workspace),
                capture_output=True,
                text=True,
            )
        except OSError as error:
            return ClaudeCommandResult(
                ok=False,
                session_id=None,
                display_text=str(error),
                error="spawn_failed",
                return_code=1,
            )

        return self._parse_output(completed.stdout, completed.stderr, completed.returncode)

    def _parse_output(
        self,
        stdout: str,
        stderr: str,
        return_code: int,
    ) -> ClaudeCommandResult:
        events: list[dict[str, Any]] = []
        session_id: str | None = None
        assistant_text: list[str] = []
        result_text: str | None = None
        error_code: str | None = None
        is_error = return_code != 0

        for line in stdout.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                event = json.loads(stripped)
            except json.JSONDecodeError:
                assistant_text.append(stripped)
                continue

            if not isinstance(event, dict):
                continue
            events.append(event)
            session_id = (
                session_id
                or event.get("session_id")
                or event.get("sessionId")
                or event.get("session_id")
            )

            if event.get("type") == "assistant":
                message = event.get("message", {})
                assistant_text.extend(self._extract_text_chunks(message.get("content")))
                if event.get("error"):
                    error_code = str(event["error"])
                    is_error = True

            if event.get("type") == "result":
                result_text = str(event.get("result", "")).strip() or result_text
                if event.get("is_error"):
                    is_error = True

        display_text = result_text or "\n".join(chunk for chunk in assistant_text if chunk).strip()
        if not display_text:
            display_text = stderr.strip() or "Claude returned no output."

        return ClaudeCommandResult(
            ok=not is_error,
            session_id=session_id,
            display_text=display_text,
            error=error_code if is_error else None,
            events=events,
            return_code=return_code,
        )

    def _extract_text_chunks(self, content: Any) -> list[str]:
        if isinstance(content, str):
            return [content]
        if not isinstance(content, list):
            return []

        chunks: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                chunks.append(str(item.get("text", "")))
        return chunks

