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

## Current Capabilities

- Reads Claude Code state from `~/.claude/projects`, `~/.claude/teams`, and
  `~/.claude/tasks`.
- Normalizes sessions, user turns, assistant turns, teams, agents, tasks, and
  mailbox assignments into a single graph snapshot.
- Prefers Graphviz `dot` for layout and falls back automatically to a layered
  pure-Python layout when `dot` is not installed.
- Launches a Textual TUI with:
  - focus selector for teams and sessions
  - scrollable ASCII graph view
  - timeline pane
  - inspector pane
  - prompt bar that shells out to Claude Code instead of reimplementing it

## Architecture

- `ClaudeStateLoader`: ingests persisted Claude artifacts and builds a normalized
  `GraphSnapshot`.
- `AutoLayoutEngine`: tries Graphviz plain output first, then a deterministic
  layered layout.
- `AsciiGraphRenderer`: turns the filtered layout into a terminal-friendly graph.
- `ClaudeCLIClient`: sends prompts through the real `claude` binary and refreshes
  the monitor from disk afterward.

The app stays thin on purpose. Claude Code still owns orchestration, sidechains,
task DAG updates, and session persistence.

## Planned surface

- `scc monitor`: launch the TUI.
- `scc snapshot`: print a normalized graph snapshot for debugging or automation.

## Development

```bash
uv sync --extra dev
uv run scc monitor
uv run pytest
```

If `uv sync` panics locally, a plain virtualenv works too:

```bash
python3 -m venv /tmp/scc-venv
/tmp/scc-venv/bin/pip install -e '.[dev]'
/tmp/scc-venv/bin/python -m scc monitor
```

## Usage

Start the monitor against your Claude state and current repo:

```bash
uv run scc monitor --claude-home ~/.claude --workspace /path/to/repo
```

Useful keys:

- `q`: quit
- `r`: reload the Claude snapshot
- `Ctrl+L`: move focus to the prompt bar

The prompt bar submits through the real `claude` CLI. If Claude Code is not
logged in, SCC surfaces the CLI error and leaves the graph monitor running.

## Graphviz

Install Graphviz if you want higher-quality clustered layouts:

```bash
brew install graphviz
```

Without `dot`, SCC still works and falls back to its layered layout engine.
