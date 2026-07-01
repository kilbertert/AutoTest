# MCP integration — deep dive

This document explains how trendpower hosts third-party
[Model Context Protocol](https://modelcontextprotocol.io) servers. For a quick
"how do I add a server" guide, see
[`trendpower-tui/README.md`](../trendpower-tui/README.md#mcp-servers). This file is
for people who want to understand the protocol layer, the design choices, and
how to extend the integration.

## What is MCP, in one paragraph

MCP is an open JSON-RPC 2.0 protocol invented by Anthropic to give LLM agents
a uniform plugin format. Instead of every agent framework writing its own
filesystem / GitHub / database tools, anyone can publish an **MCP server**
once and any compliant **MCP host** (Claude Desktop, Cursor, Cline, trendpower,
…) can use it. From the LLM's point of view an MCP tool is indistinguishable
from a locally-defined function-calling tool: same JSON Schema, same call /
result shape.

## Three roles

```
┌─────────────┐         ┌────────────┐         ┌─────────────┐
│   Host      │  spawns │   Client   │  speaks │   Server    │
│ (trendpower)    │ ──────▶ │ (in-proc)  │ ──────▶ │ (process or │
│             │   1 : N │            │  1 : 1  │  remote)    │
└─────────────┘         └────────────┘         └─────────────┘
```

- **Host** = the application running the agent loop (trendpower).
- **Client** = an *object inside the host process* that owns one connection
  and speaks JSON-RPC. Provided by the official `mcp` Python SDK — trendpower does
  not implement the protocol itself.
- **Server** = the other side. For stdio it's a local subprocess; for SSE /
  Streamable HTTP it's a remote HTTP service.

## Three transports

| transport | client side | server side | use case |
|---|---|---|---|
| `stdio` | `mcp.client.stdio.stdio_client` forks the server binary and reads/writes JSON over its stdin/stdout, one message per line | a process trendpower launches | local tools (filesystem, git, db driver, shell wrappers) |
| `sse` | `mcp.client.sse.sse_client` connects to a long-lived SSE stream and posts requests via HTTP | already-running HTTP service | legacy remote servers; deprecated by the protocol but still common |
| `streamable_http` | `mcp.client.streamable_http.streamablehttp_client` uses one HTTP endpoint that upgrades to SSE on demand | already-running HTTP service | current recommendation for remote servers |

All three converge on the same `(read_stream, write_stream)` pair, which
`mcp.ClientSession` consumes uniformly. trendpower exposes a single
`open_transport(cfg)` async context manager
([`trendpower/community/mcp/transports.py`](../trendpower-py/trendpower/community/mcp/transports.py))
that picks the right one.

## How a request flows end-to-end

```
1. trendpower starts → reads ~/.trendpower/mcp_servers.json
2. MCPManager.connect_all() → spawn N MCPToolsets in parallel
3. each MCPToolset:
       open_transport(cfg) → (read, write) streams
       ClientSession(read, write).initialize()    # JSON-RPC handshake
       session.list_tools()                       # cache tool definitions
       wrap each tool as a trendpower FunctionTool, prefix name with server name
4. MCPManager aggregates tools → returned to TUI startup
5. TUI calls create_coding_agent(..., extra_tools=mcp_tools)
6. Agent serializes tools to OpenAI / Anthropic JSON schema
   (raw_input_schema is used verbatim, no pydantic round-trip)
7. LLM picks a tool → emits `filesystem__read_file({"path": "..."})`
8. Agent loop's _act() looks up the FunctionTool by name and calls invoke
9. invoke is a closure: forwards to MCPSession.call_tool("read_file", args)
10. Result content gets flattened to text (or a structured error)
11. Tool result message appended to transcript → next loop iteration
```

The `ClientSession`, the JSON-RPC encoding, and the protocol state machine
all live inside the official SDK. trendpower only owns steps 2–4, 9–10.

## Why the integration is small

The integration adds **~1k lines** including tests and docs because:

- trendpower's `FunctionTool` already matches MCP's tool shape: name, description,
  JSON Schema, async invoke.
- The agent loop is already async and runs tools in parallel — remote calls
  inherit that for free
  ([`trendpower-py/trendpower/agent/agent.py`](../trendpower-py/trendpower/agent/agent.py)).
- The `community/` layer is the explicit extension surface — no changes
  required to `foundation/` or `agent/` semantics.

## Design decisions worth knowing

### `FunctionTool.raw_input_schema`

MCP servers hand trendpower a raw JSON Schema for each tool's inputs. The
provider adapters serialize tools via `parameters.model_json_schema()` on a
pydantic class. Round-tripping arbitrary JSON Schema through pydantic is
brittle (custom `format`, `$ref`, oneOf trees, vendor extensions all break in
subtle ways). The cleanest fix was widening `FunctionTool`:

```python
@dataclass
class FunctionTool(...):
    name: str
    description: str
    parameters: Type[BaseModel]
    invoke: ...
    raw_input_schema: Optional[Dict[str, Any]] = None  # NEW
```

When set, provider adapters skip pydantic and use the raw schema verbatim
(see [`trendpower/community/openai/utils.py`](../trendpower-py/trendpower/community/openai/utils.py)
and [`trendpower/community/anthropic/utils.py`](../trendpower-py/trendpower/community/anthropic/utils.py)).
Local tools that already have a pydantic class are unaffected.

### Closure routing instead of a global registry

Each MCP `FunctionTool.invoke` is a closure that captures its `MCPSession`:

```python
def make_invoke(session, tool_name):
    async def invoke(args, signal):
        return _format(await session.call_tool(tool_name, args))
    return invoke
```

The agent layer doesn't need to know which session a tool belongs to. Adding
a new MCP server costs zero changes to the agent — only the closure carries
the routing.

### Name prefixing — `servername__toolname`

Different MCP servers often expose tools with the same name (`read`,
`create_issue`, `query`). trendpower prefixes every tool with its server key from
the config file (`filesystem__read_file`, `github__create_issue`). The
separator is `__` and is exposed as `PREFIX_SEPARATOR` in
[`tool_adapter.py`](../trendpower-py/trendpower/community/mcp/tool_adapter.py) if you
need to round-trip the prefix. The prefixed name is also run through
`_sanitize_tool_name` so it satisfies strict provider constraints
(`^[A-Za-z0-9_-]{1,64}$`); only the LLM-facing name is rewritten — the closure
still calls the server with the tool's real, unprefixed name.

### Long-lived session inside a dedicated task

`mcp.client.stdio.stdio_client` is backed by anyio task scopes that
**must be entered and exited from the same task**. The trendpower app opens
sessions in `on_mount` and closes them in `on_unmount` — usually different
tasks. To bridge that, `MCPToolset._run()` runs the entire session lifetime
inside one dedicated `asyncio.Task` and uses `asyncio.Event` to signal ready
/ close. The public `connect()` and `aclose()` are therefore safe to call
from any task.

### Error isolation by default

`MCPManager.connect_all()` runs every server's `connect()` inside
`asyncio.gather` with explicit per-server exception capture. A bad config
(typo'd command, missing API key, unreachable URL) is logged, stored on the
toolset's `.error`, and surfaced via `/mcp list` — but **never** breaks
agent startup or other servers. This matches Claude Desktop's behavior and
is critical for usability: most users have at least one flaky server.

### Server-side validation

`call_tool` forwards the raw input dict without local pydantic validation.
MCP servers are required to validate against their own `inputSchema`, and
duplicating validation client-side would create drift the moment a server
adds a new optional field. If the LLM sends garbage, the server returns
`isError=true` with a text body; the adapter turns that into a
`StructuredToolError` that flows through the agent's normal tool-error path.

## Configuration reference

Location: `~/.trendpower/mcp_servers.json` (or `$TRENDPOWER_HOME/mcp_servers.json`
when the env var is set). Missing or malformed → empty server list, no
crash, a one-line warning on the startup banner.

Shape:

```json
{
  "mcpServers": {
    "<server-name>": { "transport": "stdio" | "sse" | "streamable_http", ... }
  }
}
```

Per-transport fields:

```jsonc
// stdio
{ "transport": "stdio",
  "command": "npx",                              // required
  "args":    ["-y", "@x/server"],                // optional
  "env":     {"FOO": "${FOO}"},                  // optional
  "cwd":     "/some/dir"                         // optional
}

// sse
{ "transport": "sse",
  "url":     "https://a/sse",                    // required
  "headers": {"Authorization": "Bearer ${X}"}    // optional
}

// streamable_http
{ "transport": "streamable_http",
  "url":     "https://a/mcp",                    // required
  "headers": {"Authorization": "Bearer ${X}"}    // optional
}
```

`${ENV_VAR}` is expanded against the host process's environment at load
time. Missing vars become `""`. If `transport` is omitted, trendpower infers
`stdio` when `command` is present and `streamable_http` when only `url` is
present — same heuristic as Claude Desktop.

## Slash command reference

| command | behavior |
|---|---|
| `/mcp` | shows help + config path |
| `/mcp list` | markdown table: name / transport / status / tool count / error |
| `/mcp reload` | re-read config, tear down all sessions, reconnect in parallel |

After `/mcp reload`, *new* sessions are connected and the manager's tool
list is refreshed, but the **already-running agent still holds the toolset
that was passed to `create_coding_agent`** at startup. To make a freshly
added MCP server visible to the live agent, restart the TUI. This is a
deliberate trade-off: hot-swapping mid-conversation tools risks breaking
in-flight tool calls and the LLM's mental model of available capabilities.

## 安装一个新的 MCP server（实操手册）

> 这一节是写给「我只想把某个 MCP server 挂上去用」的人的，按步骤照做即可。
> 上面的章节解释「为什么这样实现」，这一节解释「怎么操作」。

### Step 0 — 准备运行环境

绝大多数社区 MCP server 是用下面两种方式之一发布的，先确认本机装了对应的运行器：

| server 发布形态 | 需要的命令 | 安装方式 |
|---|---|---|
| npm 包（最常见，命令通常是 `npx`） | `node` / `npx` | 装 [Node.js](https://nodejs.org)（自带 `npx`） |
| Python 包（命令通常是 `uvx` 或 `python -m`） | `uvx` / `python` | 装 [uv](https://github.com/astral-sh/uv) 或用现成 Python |
| 远程 HTTP 服务（别人已经跑好的） | 无 | 只要有 URL（和可能的 token）即可 |

验证：在终端敲 `npx -v` / `uvx --version`，能打印版本号就说明可用。
`stdio` 类型的 server 是 trendpower **自己拉起子进程**的，所以命令必须在 `PATH` 里能找到。

### Step 1 — 找到配置文件

trendpower 只读一个文件：

```
~/.trendpower/mcp_servers.json
```

如果设置了环境变量 `TRENDPOWER_HOME`，则改读 `$TRENDPOWER_HOME/mcp_servers.json`。
文件不存在不会报错（等于「没有配置任何 server」）。第一次配置时手动创建它：

```bash
mkdir -p ~/.trendpower
$EDITOR ~/.trendpower/mcp_servers.json
```

也可以在 TUI 里敲 `/mcp`，它会把当前生效的配置文件路径打印出来，照着那个路径建文件最保险。

### Step 2 — 按传输方式写一条 server 配置

文件外层固定是 `{ "mcpServers": { ... } }`，里面每个 key 是你给这个 server 起的**逻辑名**
（会变成工具名前缀，见 Step 6）。下面四个例子覆盖了几乎所有真实场景，直接抄改：

```jsonc
{
  "mcpServers": {

    // 例 1：本地文件系统 server（npx 拉起，stdio）
    //  - command/args 即「在终端会怎么敲这个命令」
    //  - 省略 transport 时，有 command 默认按 stdio 处理
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/Users/me/projects"]
    },

    // 例 2：GitHub server（stdio + 需要 token，用 env 注入）
    //  - ${GITHUB_TOKEN} 在加载时从当前进程环境变量展开；变量不存在则展开成空串
    "github": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": { "GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_TOKEN}" }
    },

    // 例 3：Python 系 server（uvx 拉起，stdio + 指定工作目录）
    "sqlite": {
      "command": "uvx",
      "args": ["mcp-server-sqlite", "--db-path", "/Users/me/data/app.db"],
      "cwd": "/Users/me/data"
    },

    // 例 4：远程 server（别人已经跑好的 HTTP 服务）
    //  - 只给 url、不写 transport 时，默认按 streamable_http（现代远程协议）
    //  - 老服务可能只支持 sse，那就把 transport 显式写成 "sse"
    "remote-tools": {
      "transport": "streamable_http",
      "url": "https://api.example.com/mcp",
      "headers": { "Authorization": "Bearer ${REMOTE_API_KEY}" }
    }

  }
}
```

字段速查：

- **stdio**：`command`（必填）、`args`（可选）、`env`（可选）、`cwd`（可选）。
- **sse** / **streamable_http**：`url`（必填）、`headers`（可选）。
- `transport` 可省略：有 `command` → 推断 `stdio`；只有 `url` → 推断 `streamable_http`。
- 任何字符串里的 `${VAR}` 都会在加载时用宿主进程的环境变量替换（找不到 → 空串）。

### Step 3 — 把密钥放进环境变量（不要硬编码）

例 2/4 里用了 `${GITHUB_TOKEN}` / `${REMOTE_API_KEY}`。把真实值放到你的 shell 环境，
而不是写死在 json 里（json 可能被你 commit 进 git）：

```bash
# 写进 ~/.zshrc 之类，保证启动 trendpower 的那个终端能读到
export GITHUB_TOKEN=ghp_xxx
export REMOTE_API_KEY=sk-xxx
```

注意：展开发生在 **trendpower 进程启动时**。所以改了环境变量后，要重启 TUI（或 `/mcp reload`）才会生效。

### Step 4 — 让 trendpower 连上去

二选一：

- **冷启动**：直接启动 TUI（`trendpower`）。启动时会并行连接所有 server，banner 上会出现一行
  类似 `MCP: 2 server(s) connected (17 tool(s)), 1 failed.`。
- **热重连**：TUI 已经开着时，敲 `/mcp reload`。它会重新读配置文件、断开旧连接、并行重连。

> ⚠️ 重要限制：`/mcp reload` 之后，**当前正在跑的 agent 会话仍然用启动时拿到的那套工具**。
> 想让新加的 server 对 agent 立刻可见，**重启 TUI** 最稳妥。这是故意的设计——
> 对话进行到一半热替换工具集会打乱模型对「自己有哪些能力」的认知。

### Step 5 — 验证连上了

敲 `/mcp list`，会打印一张表：

```
| name        | transport       | status     | tools | error |
|-------------|-----------------|------------|------:|-------|
| filesystem  | stdio           | connected  |    11 |       |
| github      | stdio           | connected  |    26 |       |
| remote-tools| streamable_http | failed     |     0 | Connection refused ... |
```

- `connected` + 工具数 > 0 → 成功。
- `failed` → 看 `error` 列，对照下面的排错表。
- 表里压根没有这一行 → 配置文件没被读到（路径 / JSON 语法问题）。

### Step 6 — 在对话里使用

连上之后，server 的工具会自动注入给模型，**工具名带 server 名前缀**，分隔符是 `__`：

```
filesystem__read_file
github__create_issue
remote-tools__search
```

加前缀是为了避免多个 server 撞名（很多 server 都有叫 `read` / `query` 的工具）。
你不用手动调用——正常用自然语言让 agent 干活，它会自己挑工具。

### 排错速查表

| 现象 | 大概率原因 / 解法 |
|---|---|
| `/mcp list` 里某行是 `failed`，error 写 `command not found` / `ENOENT` | `npx` / `uvx` 没装，或不在 `PATH`。先在终端单独跑一遍那条 `command + args`。 |
| `failed`，error 提到 auth / 401 / 403 | token 没设或设错。检查 `echo $GITHUB_TOKEN`，并确认设完后重启了 trendpower。 |
| `failed`，error 是 `Connection refused` / 超时 | 远程 server 没跑起来，或 URL / 传输方式不对（试试把 `streamable_http` 换成 `sse`）。 |
| 启动 banner 完全没有 MCP 那一行 | 配置文件不存在或路径不对。`/mcp` 看真实路径；`echo $TRENDPOWER_HOME` 确认有没有被改。 |
| 改了配置文件但没变化 | 没重连。`/mcp reload`；要让 live agent 看到则重启 TUI。 |
| 整个文件没生效，且有 warning | JSON 语法错（多了逗号、少了引号）。用 `python3 -m json.tool ~/.trendpower/mcp_servers.json` 校验。 |
| server 连上了但某个工具调用总报错 | 多半是 server 端参数校验失败。trendpower 不在本地校验，错误是 server 返回的 `isError`，原文会出现在工具结果里。 |

### 不经过 TUI，在自己的代码里挂 MCP

如果你在写脚本、不走 TUI，可以直接用 `community/mcp` 的 API：

```python
import asyncio
from trendpower.community.mcp import MCPManager, load_servers_from_file
from trendpower.coding.agents.lead_agent import create_coding_agent

async def main():
    cfgs = load_servers_from_file("~/.trendpower/mcp_servers.json")
    mgr = MCPManager(cfgs)
    try:
        mcp_tools = await mgr.connect_all()        # list[Tool]
        agent = await create_coding_agent(model=..., extra_tools=mcp_tools)
        # ... 跑 agent ...
    finally:
        await mgr.aclose()                         # 一定要关，否则子进程泄漏

asyncio.run(main())
```

也可以用 `load_servers_from_dict({...})` 直接传内联配置，不依赖文件。

### 已知边界 / 注意事项

- **工具名长度 / 字符**：前缀后的工具名是 `servername__toolname`。某些 provider（如 OpenAI）
  对工具名有 64 字符且 `[A-Za-z0-9_-]` 的限制。trendpower 会自动清洗——非法字符替换成 `_`，
  超长则截断并补一段哈希后缀保证唯一性（见 `tool_adapter._sanitize_tool_name`）。即便如此，
  给 server 起短英文名仍能让 `/mcp list` 更易读。
- **只支持 Tools**：MCP 的 Resources / Prompts / Sampling 暂未适配（见下一节）。
- **远程鉴权只支持静态 header**：OAuth 流程暂不支持，但大多数 Bearer-token 服务用 header 就够了。
- **只读用户级配置**：还没有项目级（`<cwd>/.trendpower/...`）配置叠加。

## Out of scope (for now)

- **Resources** and **Prompts** — MCP supports both; trendpower only adapts
  Tools today. ~95% of community MCP servers don't expose anything else.
- **Sampling** — letting the server ask the host's LLM to generate text for
  it. Niche, requires deeper agent integration.
- **OAuth** — remote servers can require OAuth; today trendpower only supports
  static headers (which work for most Bearer-token setups).
- **Project-local config overlays** — only the user-level config is read.

All four can be added without breaking the current API.

## File map

```
trendpower-py/trendpower/community/mcp/
├── __init__.py              public re-exports
├── config.py                pydantic configs + env-var interpolation
├── transports.py            open_transport() — stdio / sse / streamable_http
├── session.py               MCPSession — wraps ClientSession + lifecycle
├── tool_adapter.py          MCP Tool → FunctionTool (raw_input_schema)
├── toolset.py               MCPToolset — single server, dedicated task
├── manager.py               MCPManager — N servers, error isolation
└── tests/                   config / adapter / e2e (in-process stdio server)

trendpower-tui/trendpower_tui/mcp/
├── config_loader.py         locates and loads mcp_servers.json
└── lifecycle.py             MCPLifecycle — startup / shutdown / reload / status
```

## Extending

- **New transport.** Add a branch to `open_transport` in
  [`transports.py`](../trendpower-py/trendpower/community/mcp/transports.py) and a
  new config class in [`config.py`](../trendpower-py/trendpower/community/mcp/config.py).
- **Custom tool wrapping** (e.g. injecting middleware around every MCP
  call). Sublass or compose `MCPToolset` and override the `_tools` it caches
  after `connect()`.
- **Project-local overlays.** Change `default_mcp_config_path()` to merge a
  `<cwd>/.trendpower/mcp_servers.json` layer before returning.
- **Resources / Prompts.** Add `list_resources` / `read_resource` calls on
  `MCPSession` and expose them via a new agent middleware (resources don't
  fit the function-calling tool shape; they need a separate injection point).

## Writing your own MCP server (for testing)

trendpower ships a minimal one for tests at
[`trendpower/community/mcp/tests/_fake_stdio_server.py`](../trendpower-py/trendpower/community/mcp/tests/_fake_stdio_server.py).
It uses `FastMCP` from the SDK:

```python
from mcp.server.fastmcp import FastMCP

server = FastMCP("my-server")

@server.tool(description="Reverse a string")
def reverse(text: str) -> str:
    return text[::-1]

server.run("stdio")
```

Then in `~/.trendpower/mcp_servers.json`:

```json
{"mcpServers": {"mine": {"transport": "stdio", "command": "python",
                          "args": ["-m", "my_module"]}}}
```

`/mcp list` should show `mine | stdio | connected | 1`.
