# Trendpower Shell

VS Code shell that drives the [trendpower](../../trendpower/) ReAct agent for
natural-language API/UI testing. Type a prompt in the sidebar, watch the agent
think, call MCP tools (`pywinauto`, `api-mcp`, `apifox-mcp`, …), and return a
final answer.

> **No more writing `.feature` files.** No more "Send to Copilot" CodeLens. The
> runner talks to your real MCP servers (registered in `~/.trendpower/`), not
> to GitHub Copilot Chat.

## Quick start

1. **Install the extension** (or run `npm run compile` and launch the dev host
   with F5).
2. **Make sure trendpower is reachable**: editable install of
   `trendpower/trendpower-py` so `python -c "import trendpower"` succeeds.
3. **Open the Trendpower activity-bar icon** — the sidebar shows three health
   badges (`uv`, `trendpower`, MCP server count).
4. **Type a prompt** in the input box and press `Run` (or `Ctrl+Enter`).

### Example prompt

```
看看 Apifox Tikhub 项目里有哪些 health 相关的接口，测一下健康检查接口
```

The agent will:
1. `apifox_list_endpoints(path_contains="health")` → list endpoints
2. `apifox_get_endpoint_detail(...)` → fetch contract
3. `api-mcp.set_base_url(...)` / `http_get(...)` / `assert_status(200)` → run
4. Stream the final answer back into the sidebar.

## Configuration

Everything lives in `~/.trendpower/`:

| Path | What |
|---|---|
| `mcp_servers.json` | MCP servers (pywinauto / api-mcp / apifox-mcp) |
| `OPENAI_API_KEY` env | OpenAI provider API key |
| `ANTHROPIC_API_KEY` env | Anthropic provider API key |
| `TRENDPOWER_MODEL` env | Override model name |
| `TRENDPOWER_PROVIDER` env | `openai` (default) or `anthropic` |

Click **"Open ~/.trendpower"** in the sidebar footer to jump there.

## What changed vs the old BDD AI Toolkit

This is **v2.0.0** — a complete rewrite. Gone:

- ❌ Gherkin parsing / `.feature` file support
- ❌ "Send to Copilot" CodeLens
- ❌ Auto-generate pytest step definitions
- ❌ MS Copilot Chat fallback
- ❌ Bundling MCP server source into the extension
- ❌ `bdd_ai_conf.json` configuration scaffolding

In:

- ✅ Subprocess runner (`resources/trendpower-headless/runner.py`) speaks
  NDJSON on stdout
- ✅ Chat-like sidebar with streaming event log
- ✅ Health badges (`uv` / `trendpower` / MCP server count)
- ✅ One source of truth for everything: `~/.trendpower/`

## Development

```bash
cd bdd_ai_toolkit
npm install
npm run compile          # tsc + copy resources + copy webview script
```

Launch with F5 in VS Code (Extension Development Host).

## License

MIT