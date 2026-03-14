from __future__ import annotations

import argparse
from pathlib import Path

from scc.app import SCCApp


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scc")
    subparsers = parser.add_subparsers(dest="command", required=True)

    monitor = subparsers.add_parser("monitor", help="Launch the SCC monitor")
    monitor.add_argument(
        "--claude-home",
        type=Path,
        default=Path.home() / ".claude",
        help="Path to Claude Code state",
    )
    monitor.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help="Workspace path for prompt submission",
    )

    snapshot = subparsers.add_parser(
        "snapshot",
        help="Print a placeholder graph snapshot while the monitor is under construction",
    )
    snapshot.add_argument(
        "--claude-home",
        type=Path,
        default=Path.home() / ".claude",
        help="Path to Claude Code state",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "monitor":
        app = SCCApp()
        app.run()
        return 0

    if args.command == "snapshot":
        print(
            "{"
            f'"claude_home": "{args.claude_home}", '
            '"status": "scaffold"'
            "}"
        )
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2

