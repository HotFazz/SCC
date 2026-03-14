from __future__ import annotations

import argparse
import json
from pathlib import Path

from scc.app import SCCApp
from scc.layout import AutoLayoutEngine
from scc.loader import ClaudeStateLoader


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
    snapshot.add_argument(
        "--layout",
        choices=("none", "auto"),
        default="none",
        help="Include a layout preview in the snapshot output",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "monitor":
        app = SCCApp(claude_home=args.claude_home, workspace=args.workspace)
        app.run()
        return 0

    if args.command == "snapshot":
        loader = ClaudeStateLoader(args.claude_home)
        snapshot = loader.load()
        payload = snapshot.to_dict()
        payload["claude_home"] = str(args.claude_home)
        if args.layout == "auto":
            layout = AutoLayoutEngine().layout(snapshot)
            payload["layout"] = {
                "engine": layout.engine,
                "width": layout.width,
                "height": layout.height,
                "node_positions": {
                    node_id: {
                        "x": placement.x,
                        "y": placement.y,
                        "width": placement.width,
                        "height": placement.height,
                    }
                    for node_id, placement in sorted(layout.node_positions.items())
                },
            }
        print(json.dumps(payload, indent=2))
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2
