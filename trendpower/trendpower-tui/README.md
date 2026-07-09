# trendpower-tui

`trendpower-tui` 是 trendpower 的 Python 终端前端。它使用
[Textual](https://textual.textualize.io/) 渲染 UI，并调用
[`../trendpower-py`](../trendpower-py) 中的 Python 后端来跑实际的 agent loop、
模型 provider、编码工具、skills 与 todo 状态。

简而言之：

```text
trendpower-tui
  -> 读取 ~/.trendpower/config.yaml 中的模型配置
  -> 创建 DeepSeek / OpenAI / Anthropic 等 provider
  -> 创建 trendpower-py 的 coding agent
  -> 将 agent 事件流渲染到终端 UI
```

## 环境要求

- Python 3.10 或更高
- 至少一个可用的模型 API key（DeepSeek / OpenAI / Anthropic 等）

## 安装

推荐路径（macOS / Linux，全局命令）见仓库根 [`README.md`](../README.md)：

```bash
uv tool install ./trendpower-tui --with ./trendpower-py --python 3.12
```

开发模式（任何平台，改源码立刻生效）：

```bash
# macOS / Linux
uv venv --python 3.12 .venv && source .venv/bin/activate
uv pip install -e ./trendpower-py -e ./trendpower-tui

# Windows (PowerShell)
cd trendpower-tui
python -m pip install -e ..\trendpower-py -e .
```

安装完成后，下面两种启动方式都能用：

```bash
trendpower              # 全局命令（uv tool install 之后）
python -m trendpower_tui  # 走当前激活的 Python 环境（开发时优先）
```

## 配置模型

TUI 需要至少配置一个模型才能跑 agent。模型配置文件位于：

```text
C:\Users\<你>\.trendpower\config.yaml
```

PowerShell 查看：

```powershell
Get-Content $HOME\.trendpower\config.yaml
```

### DeepSeek

DeepSeek 是 OpenAI 兼容的接口，使用内置的 `deepseek` provider preset：

```powershell
cd trendpower-tui

python -m trendpower_tui config model add `
  --name deepseek-chat `
  --provider deepseek `
  --api-key YOUR_DEEPSEEK_API_KEY
```

`deepseek` preset 默认使用：

```text
https://api.deepseek.com/v1
```

如果你想用别的 DeepSeek 模型名，把它作为 `--name` 传入：

```powershell
python -m trendpower_tui config model add `
  --name deepseek-reasoner `
  --provider deepseek `
  --api-key YOUR_DEEPSEEK_API_KEY
```

### 自定义 OpenAI 兼容地址

使用 `--provider other` 加上 `--base-url`：

```powershell
python -m trendpower_tui config model add `
  --name deepseek-chat `
  --provider other `
  --base-url https://api.deepseek.com/v1 `
  --api-key YOUR_DEEPSEEK_API_KEY
```

本地网关、代理或其它兼容 provider 也是同样的模式：

```powershell
python -m trendpower_tui config model add `
  --name your-model-name `
  --provider other `
  --base-url https://your-openai-compatible-endpoint/v1 `
  --api-key YOUR_API_KEY
```

### OpenAI

```powershell
python -m trendpower_tui config model add `
  --name gpt-4o-mini `
  --provider openai `
  --api-key YOUR_OPENAI_API_KEY
```

### Anthropic

```powershell
python -m trendpower_tui config model add `
  --name claude-3-5-sonnet-latest `
  --provider anthropic `
  --api-key YOUR_ANTHROPIC_API_KEY
```

## 管理模型

列出已配置的模型：

```powershell
python -m trendpower_tui config model list
```

设置默认模型：

```powershell
python -m trendpower_tui config model set-default deepseek-chat
```

删除模型：

```powershell
python -m trendpower_tui config model remove deepseek-chat
```

注意：CLI 不允许删除最后一个已配置的模型。

## 启动 TUI

配置好模型之后：

```powershell
cd trendpower-tui
python -m trendpower_tui
```

然后输入一个任务，比如：

```text
列出当前目录文件
```

或者：

```text
读一下 README，告诉我这个项目怎么跑起来。
```

## TUI 内置斜杠命令

在 TUI 输入框里可以直接用斜杠命令：

```text
/help
/help <command>
/clear
/model
/exit
/quit
```

### `/model`

`/model` 会弹出模型管理窗，相当于在 TUI 里把 CLI 的 `config model list / add /
set-default / remove` 合到一个面板：

- ↑/↓ 选择
- Enter 把当前选中的模型设为默认，并自动重建 agent
- `a` 添加新模型（走 provider → API key → 模型名 → 确认 的向导）
- `d` 删除当前选中的模型（最后一个不允许删）
- Esc 关闭

添加或切换之后不需要重启 TUI，agent 会用新模型立刻重建。

如果在已配置的 skill 目录里发现了 skill，它们也会作为斜杠命令出现，并可以
在输入框里被显式触发（例如 `/coding-plan 帮我规划重构`）。

## skills 加载路径

默认 skills 在仓库根目录的 `skills/`。启动时按下列规则查找（命中即用）：

1. 若设了 `TRENDPOWER_SKILLS_DIR` → **只**扫这个目录（手动指定时才需要）。
2. 否则扫 `<cwd>/skills` 以及 cwd 祖先目录里第一个像 skill 目录的 `skills/`（从仓库内启动即可命中）。
3. 否则顺着已安装的 `trendpower_tui` / `trendpower` 包位置往上找 `skills/`。**可编辑安装（`uv tool install --editable`）时这一步会指回源码目录，自动命中仓库根的 `skills/`，零配置、改完即生效。**

启动后 TUI 顶部会打印实际命中的 skills 数量，便于排查。如果显示
「skills: 0」但你期望有 skill：用了可编辑安装就确认仓库根的 `skills/<name>/SKILL.md` 存在；否则确认 `TRENDPOWER_SKILLS_DIR` 指对了。

## 使用独立的配置目录

默认配置存于 `$HOME\.trendpower`。要做隔离测试或者按项目区分配置，可以
在 `add` 模型和启动 TUI 之前设置 `TRENDPOWER_HOME`：

```powershell
$env:TRENDPOWER_HOME="E:\git\tmp\trendpower\trendpower-home"

python -m trendpower_tui config model add `
  --name deepseek-chat `
  --provider deepseek `
  --api-key YOUR_DEEPSEEK_API_KEY

python -m trendpower_tui
```

此时配置文件位于：

```text
E:\git\tmp\trendpower\trendpower-home\config.yaml
```

## 直接使用后端库

`trendpower-py` 也可以脱离 TUI 直接使用：

```powershell
cd trendpower-py
python -m pip install -e .
$env:OPENAI_API_KEY="YOUR_OPENAI_API_KEY"
python examples\basic_openai.py
```

Anthropic：

```powershell
$env:ANTHROPIC_API_KEY="YOUR_ANTHROPIC_API_KEY"
python examples\basic_anthropic.py
```

## 常见问题

### `No models configured`

先添加一个模型：

```powershell
python -m trendpower_tui config model add `
  --name deepseek-chat `
  --provider deepseek `
  --api-key YOUR_DEEPSEEK_API_KEY
```

### `unexpected keyword argument 'thinking'`

更新到最新本地代码再重试。OpenAI 兼容 provider（包括 DeepSeek）不应当
收到 Anthropic 专属的 `thinking` 选项；当前版本已仅在 Anthropic 时下发。

### 用错了 Python 环境

在当前激活的环境里重新安装两个包：

```powershell
cd trendpower-tui
python -m pip install -e ..\trendpower-py -e .
python -m trendpower_tui
```

### Windows 下写入配置出现权限错误

将配置目录指定到不受保护的位置：

```powershell
$env:TRENDPOWER_HOME="E:\git\tmp\trendpower\trendpower-home"
python -m trendpower_tui config model list
```

### bash 工具报错 `[WinError 2] 系统找不到指定的文件`

之前 `bash` 工具写死调用 `zsh`，Windows 没装就抛这个错。已修：

- 优先使用 PATH 上的 `zsh / bash / sh`；
- 都没有时，自动走 `cmd.exe`（用 `create_subprocess_shell`，保留命令本身的引号）；
- 想强制走 PowerShell 或 Git Bash，可以在启动 TUI 之前设环境变量：

  ```powershell
  $env:TRENDPOWER_BASH_SHELL = "powershell -NoProfile -Command"
  # 或：
  $env:TRENDPOWER_BASH_SHELL = "bash -c"
  ```

如果还是看到这个错误，多半是把 `python xxx.py` 写成了多行（每行被 cmd 当成
独立命令）。把命令合并到一行即可。

### 启动后 `/help` 看不到 skill / Agent 说没有 skill

确认 skills 文件在前面「skills 加载路径」列出的某一个目录下，并且每个
skill 子目录里都有 `SKILL.md`。最稳妥的排查办法是设 `TRENDPOWER_SKILLS_DIR`
指向仓库根的 `skills/`（它会成为唯一搜索路径），或改用可编辑安装。

## MCP servers

trendpower TUI 可以挂任意第三方 [MCP](https://modelcontextprotocol.io) server，
让 agent 用上别人写好的工具（filesystem、git、GitHub、数据库 driver、SaaS API
等），不用改 trendpower 任何代码。三种传输方式都支持：

- **stdio**：本地子进程，最常见。TUI fork 一个 server 进程，通过 stdin/stdout 通信。
- **sse**：旧版远程 HTTP 协议（Server-Sent Events）。
- **streamable_http**：2025-03 起的新版远程 HTTP 协议，建议新部署用这个。

### 1. 创建配置文件

在 `~/.trendpower/mcp_servers.json`（或 `$TRENDPOWER_HOME/mcp_servers.json`）写入：

```json
{
  "mcpServers": {
    "filesystem": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/Users/me/work"]
    },
    "github": {
      "transport": "stdio",
      "command": "uvx",
      "args": ["mcp-server-github"],
      "env": { "GITHUB_TOKEN": "${GITHUB_TOKEN}" }
    },
    "company-api": {
      "transport": "streamable_http",
      "url": "https://api.example.com/mcp",
      "headers": { "Authorization": "Bearer ${COMPANY_API_KEY}" }
    },
    "legacy-saas": {
      "transport": "sse",
      "url": "https://legacy.example.com/sse"
    }
  }
}
```

字段速查：

| 字段 | stdio | sse | streamable_http |
|---|---|---|---|
| `transport` | `"stdio"`（可省略，有 `command` 时自动判断） | `"sse"` | `"streamable_http"`（仅给 `url` 时默认） |
| `command` | 必填，启动 server 的可执行文件 | — | — |
| `args` | 可选，启动参数 | — | — |
| `env` | 可选，子进程环境变量 | — | — |
| `cwd` | 可选，子进程工作目录 | — | — |
| `url` | — | 必填 | 必填 |
| `headers` | — | 可选 | 可选 |

字符串里的 `${ENV_VAR}` 会用当前 shell 环境变量替换；变量不存在则替换为空字符串。
JSON key（如上面的 `"filesystem"`、`"github"`）会作为工具名前缀，比如
`filesystem__read_file`、`github__create_issue`，避免不同 server 工具撞名。

### 2. 启动 / 检查

```bash
trendpower
```

启动 banner 里会多一行类似：

```
MCP: 2 server(s) connected (17 tool(s)), 1 failed.
```

在 TUI 里：

- `/mcp` —— 显示帮助
- `/mcp list` —— 表格：每个 server 的传输方式、连接状态、工具数、错误原因
- `/mcp reload` —— 重新读取配置文件并重连所有 server（**注意**：当前会话里
  agent 持有的工具列表是启动时构建的；reload 后想让 agent 立刻看到新工具，
  需要重启 TUI）

### 3. 在代码里直接调用 MCP（绕开 TUI）

```python
import asyncio
from trendpower.community.mcp import MCPManager, load_servers_from_file
from trendpower.coding import create_coding_agent
from trendpower.foundation import Model
from trendpower.community.anthropic import AnthropicModelProvider

async def main():
    cfgs = load_servers_from_file("~/.trendpower/mcp_servers.json")
    mgr = MCPManager(cfgs)
    try:
        mcp_tools = await mgr.connect_all()
        model = Model("claude-sonnet-4-6", AnthropicModelProvider())
        agent = await create_coding_agent(model=model, extra_tools=mcp_tools)
        # ... 跑 agent ...
    finally:
        await mgr.aclose()

asyncio.run(main())
```

### 4. 排错

| 症状 | 处理 |
|---|---|
| `/mcp list` 显示 `failed` | 看 `error` 列。常见：命令找不到（`npx` / `uvx` 没装）、API key 未设、URL 错误。 |
| 启动 banner 没有 MCP 行 | 配置文件不存在或路径不对。`echo $TRENDPOWER_HOME` 看一下。 |
| 工具不出现在 agent 工具列表 | 大概率 server 没连上，先 `/mcp list`。 |
| 编辑配置后 reload 仍是旧的 | reload 重读了文件但当前 agent session 引用的还是启动时的列表；重启 TUI。 |
| 远程 server 401/403 | 检查 `headers` 里的 token，确认环境变量已 export。 |

更多设计细节、协议层原理、扩展指南见仓库根 [`docs/mcp.md`](../docs/mcp.md)。

## 迁移指南

完整的 Ink/React → Textual 移植计划见
[MIGRATION.md](./MIGRATION.md)。
