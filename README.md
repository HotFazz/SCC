# SCC

Swarm Central Control is a terminal monitor for Claude Code teams and sidechain
agents. It treats Claude Code as the execution engine and source of truth, then
builds a graph-oriented view on top of the session, task, and team artifacts
that Claude persists on disk.

## Goals

- Visualize single-agent and multi-agent Claude sessions as a graph.
- Preserve Claude Code as the control plane instead of copying its logic.
- Provide a thin input path for sending prompts through the Claude CLI.
- Keep the monitor resilient when Graphviz or Claude auth is unavailable.

## Planned surface

- `scc monitor`: launch the TUI.
- `scc snapshot`: print a normalized graph snapshot for debugging.

## Development

```bash
uv sync --extra dev
uv run scc monitor
uv run pytest
```
