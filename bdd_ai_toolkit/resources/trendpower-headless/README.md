# trendpower-headless runner

A subprocess entry point for the `trendpower-shell` VS Code extension. Spawned
as `uv run --no-project python runner.py --prompt <text>`. Writes NDJSON events
to stdout.

## How the VS Code shell invokes it

```
uv run --no-project \
  python <extensionPath>/resources/trendpower-headless/runner.py \
  --prompt "<user prompt>" \
  --cwd <workspaceFolder>
```

## NDJSON event schema

| `type` | Payload | Meaning |
|---|---|---|
| `session_start` | `{run_id, cwd, model, provider}` | Runner has started |
| `status` | `{phase, detail}` | Status update (loading tools, connecting MCP, etc.) |
| `thinking` | `{text}` | Model's internal reasoning |
| `tool_call` | `{id, name, input}` | Model invoked a tool |
| `tool_result` | `{tool_call_id, name, output, is_error, elapsed_ms}` | Tool finished |
| `assistant_text` | `{text}` | Streaming model text (incremental) |
| `assistant_final` | `{text}` | Final model text (after last tool call) |
| `error` | `{message, trace?}` | Fatal error |
| `session_end` | `{run_id, ok, duration_ms}` | Runner finished |

## Configuration

All configuration lives in `~/.trendpower/`:

- `mcp_servers.json` — MCP server registry (pywinauto, api-mcp, apifox-mcp, …)
- Provider API keys via env: `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`
- Optional overrides: `TRENDPOWER_PROVIDER`, `TRENDPOWER_MODEL`

This runner does **not** create or modify any of those files.

## Stop

SIGTERM (sent by `TrendpowerRunner.stop()` on the TS side) translates into
`asyncio.CancelledError` inside `agent.stream()`. The runner emits
`status{cancelled}` + `session_end{ok:false}` then exits.