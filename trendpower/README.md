# trendpower

一个用 Python 实现的 **ReAct 风格 agent loop**，由三个包组成：

| 目录          | 包名         | 角色                                                                 |
| ------------- | ------------ | -------------------------------------------------------------------- |
| `trendpower-py/`  | `trendpower`     | **核心库**：Messages / Models / Tools 原语 + ReAct agent loop + 编码 agent 与工具集。不依赖任何 UI，可嵌进脚本、服务、Notebook。 |
| `trendpower-tui/` | `trendpower-tui` | **终端 UI**：基于 [Textual](https://textual.textualize.io/) 的前端。依赖 `trendpower`，把 agent 事件流渲染成 TUI，并管理模型配置、斜杠命令、skills。安装后会注册全局命令 `trendpower`。 |
| `trendpower-web/` | `trendpower-web` | **调试用 Web 可视化**：终端 stdin 跑 REPL，浏览器同时看每一轮**真实喂给 LLM 的完整请求体**（system prompt / messages / tools / temperature / max_tokens 等）+ 流式响应 + tool 调用时间线。复用 `trendpower-tui` 的配置和 skill 发现。安装后注册全局命令 `trendpower-web`。|

> 简而言之：`trendpower-py` 是引擎，`trendpower-tui` 是日常使用的壳，`trendpower-web` 是调试/教学时看"LLM 到底吃到了什么"的壳。装 `trendpower-tui` 会顺带把 `trendpower` 一起拉进来，绝大多数用户只需要走"装 TUI"那一条路径。

仓库根目录的 `skills/` 存放默认 skill（`coding-plan`、`deep-research-plan`、`frontend-design`），运行时由 agent 加载，**不属于 Python 包**，需要单独让安装版找到（见下）。

### MCP 支持

trendpower 内置 [Model Context Protocol](https://modelcontextprotocol.io) 客户端，可以接任何第三方 MCP server（filesystem、GitHub、数据库……），不用改一行 Python。三种传输方式都支持：**stdio**（本地子进程）、**SSE**（旧版远程）、**Streamable HTTP**（现代远程）。

最简流程：在 `~/.trendpower/mcp_servers.json` 里写几行配置，重启 `trendpower`，远程工具就自动出现在 agent 工具列表里。`/mcp list` 查看连接状态，`/mcp reload` 重连。

详见 [`docs/mcp.md`](./docs/mcp.md) 和 [`trendpower-tui/README.md`](./trendpower-tui/README.md#mcp-servers)。

---

## 快速开始（推荐：用 uv 装成全局命令）

适用场景：你只想能在任意目录敲 `trendpower` 启动 TUI，不打算改源码。

### 1. 装 uv

[`uv`](https://docs.astral.sh/uv/) 是单文件二进制，自带 Python 版本管理和 `uv tool`（pipx 等价物）。

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
# 把 ~/.local/bin 加进 PATH（多数 shell 安装脚本已自动处理）
export PATH="$HOME/.local/bin:$PATH"
```

### 2. 装 Python 3.12（项目要求 ≥ 3.10）

```bash
uv python install 3.12
```

不会污染系统 Python，uv 把它放在 `~/.local/share/uv/python/` 下。

### 3. 用 `uv tool install` 注册全局 `trendpower`

在仓库根目录下（**推荐加 `--editable`**）：

```bash
uv tool install --editable ./trendpower-tui --with-editable ./trendpower-py --python 3.12
```

- `--editable ./trendpower-tui` 让安装的 `trendpower` 指回源码目录，而不是拷贝快照
- `--with-editable ./trendpower-py` 把核心库也以可编辑方式装进同一个隔离 venv，绕开 PyPI 上不存在的 `trendpower` 依赖
- `--python 3.12` 指定运行时

为什么要 `--editable`：这样 `trendpower` 能顺着包位置找回仓库根目录，从而**自动发现根目录的 `skills/`，零配置、改完即生效**（见第 4 步）；同时你改 `trendpower-py/trendpower/...` 的源码也不用重装。

完成后 `trendpower` 命令落在 `~/.local/bin/trendpower`，从任意目录都能调起：

```bash
cd /tmp && trendpower --help
```

### 4. skills 怎么被找到（通常不用配）

默认 skills 在仓库根目录的 `skills/`，**不在 wheel 里**。查找规则（命中即用）：

1. 若设了 `TRENDPOWER_SKILLS_DIR` → **只**用这个目录（手动指定时才需要）。
2. 否则扫 `<cwd>/skills` 以及 cwd 祖先里的 `skills/` → 从仓库内启动就能命中。
3. 否则顺着已安装的 `trendpower_tui` / `trendpower` 包位置往上找 `skills/` → **可编辑安装（第 3 步）时自动命中仓库根的 `skills/`**。

所以只要按第 3 步用 `--editable` 装，**什么都不用配**：往根目录 `skills/` 里加 / 改 skill，下次发消息即生效，无需重启或重装。

#### 可选：手动指定 `TRENDPOWER_SKILLS_DIR`

只有在你**不用可编辑安装**、又想从任意目录读某个固定 skills 目录时，才需要手动设这个变量（它会成为唯一搜索路径，覆盖上面 2、3）。每条命令里的「当前目录」都会在执行当下展开成你机器上的绝对路径并写死进配置，可以原样复制给任何人。**先 `cd` 进你自己 clone 的仓库根目录**，再按系统选一种：

**macOS / Linux**（zsh，默认）：

```bash
cd /path/to/your/trendpower        # 换成你 clone 的位置
echo "export TRENDPOWER_SKILLS_DIR=\"$(pwd)/skills\"" >> ~/.zshrc
source ~/.zshrc
```

> 用 bash 的把 `~/.zshrc` 换成 `~/.bashrc`；只想临时用一下就直接 `export TRENDPOWER_SKILLS_DIR="$(pwd)/skills"`。

**Windows（PowerShell）**：

```powershell
cd C:\path\to\your\trendpower      # 换成你 clone 的位置
# 永久（写进用户环境变量，需重开终端生效）：
[Environment]::SetEnvironmentVariable("TRENDPOWER_SKILLS_DIR", "$PWD\skills", "User")
# 只想当前窗口临时用：
$env:TRENDPOWER_SKILLS_DIR = "$PWD\skills"
```

**Windows（CMD）**：

```bat
cd C:\path\to\your\trendpower
setx TRENDPOWER_SKILLS_DIR "%CD%\skills"   :: 永久，需重开终端
set TRENDPOWER_SKILLS_DIR=%CD%\skills      :: 仅当前窗口
```

验证（macOS/Linux 用 `echo $TRENDPOWER_SKILLS_DIR` + `ls`，Windows PowerShell 用 `echo $env:TRENDPOWER_SKILLS_DIR` + `dir`）：应指向仓库的 `skills/`，里面能看到 `coding-plan` 等目录。

### 5. 配置一个模型

至少配置一个模型，TUI 才能跑 agent。以 DeepSeek 为例：

```bash
trendpower config model add \
  --name deepseek-chat \
  --provider deepseek \
  --api-key YOUR_DEEPSEEK_API_KEY
```

其它支持的 provider：`anthropic | openai | volcengine | volcengine_coding_plan | qwen | minimax | minimax_cn | minimax_global | glm | kimi | deepseek | other`。

用 `--provider other --base-url <url>` 接任何 OpenAI 兼容端点。

配置文件落在 `~/.trendpower/config.yaml`。

### 6. 启动 TUI

```bash
trendpower           # 无参 → TUI
trendpower config    # 有参 → CLI 子命令
trendpower diagnose  # 排错：分三步打实际的 model 请求
```

---

## 其它启动方式

### Web 可视化（看真实喂给 LLM 的 prompt）

调试 agent 最常想知道的就是"这一轮 LLM 实际收到的是什么"——系统提示（含 skills 注入）、完整 messages 历史、tools 的 JSON schema、`temperature` / `max_tokens` 等参数。TUI 看不到这些，`trendpower-web` 把它们抓出来、广播到浏览器。

**`trendpower-web` 跑起来就是原版 `trendpower` 的 TUI**——一样的界面、widget、`/help` 和 `/model` 斜杠命令、审批栏、模型管理器，全都在。唯一的区别是 TUI 顶部 banner 多打一行 `[trendpower-web] live view at http://...`，**并且**在同一个 asyncio loop 上额外跑了一个 HTTP server，浏览器打开后能看到每一轮真实送给 LLM 的请求体。

```bash
# 装（同样的 uv tool 套路，把 trendpower 和 trendpower-tui 也带进同一个隔离 venv）
uv tool install ./trendpower-web --with ./trendpower-py --with ./trendpower-tui --python 3.12

# 启动（沿用 ~/.trendpower/config.yaml 里的模型，跟 TUI 共用）
trendpower-web                       # 默认 http://127.0.0.1:8765
trendpower-web --port 9000
trendpower-web --host 0.0.0.0        # 局域网内别的设备也能打开
```

启动后**终端**就是熟悉的 TUI，照常输入。同时打开打印出来的 URL，每问一句，浏览器都会出现一个新 turn，展开能看到：

- **LLM request 面板**：那一步真正传给 `chat.completions.create(**...)` / `messages.create(**...)` 的完整 kwargs——system / messages / tools / model / temperature / max_tokens / thinking…
- **Timeline 面板**：assistant 文本、tool_use（名字 + 入参）、tool_result（结果片段）、progress 事件，时间序排列

**实现要点**（在 TUI 启动前装三个 hook，**不动 `trendpower-py` / `trendpower-tui` 一行**）：

1. monkey-patch `trendpower.community.openai.OpenAIModelProvider` 和 `trendpower.community.anthropic.AnthropicModelProvider`，换成会广播 `llm_request` 的子类（在调 SDK 之前把 `_base_params()` 结果通过 SSE 推到前端）
2. monkey-patch `trendpower_tui.tui.agent_runner.AgentRunner.submit`，让 agent 事件流同时也广播到浏览器
3. `trendpowerApp` 的 `on_mount` 末尾启一个 aiohttp server（同一个 asyncio loop）

> 不开浏览器、关掉网页都不影响 TUI 运行——`EventBroadcaster` 的订阅者集合为空时 `publish` 是 no-op。

### A. 开发模式（改源码立刻生效）

如果你打算修改 `trendpower-py/` 或 `trendpower-tui/` 的源码，用 venv + editable 安装比 `uv tool install` 顺手：

```bash
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -e ./trendpower-py -e ./trendpower-tui
trendpower                       # 走当前激活的 venv
python -m trendpower_tui         # 等价写法，显式锁定解释器
```

改 `trendpower-py/trendpower/**.py` 后无需重装，直接重跑。

### B. 升级已装的全局命令

`uv tool install` 默认是非 editable 的，改了源码要重装：

```bash
uv tool install ./trendpower-tui --with ./trendpower-py --python 3.12 --force --reinstall
```

或者一开始就装成 editable：

```bash
uv tool install --editable ./trendpower-tui --with ./trendpower-py --python 3.12
```

### C. 卸载

```bash
uv tool uninstall trendpower-tui
uv tool uninstall trendpower-web   # 如果之前装了
```

---

## 直接使用核心库（不要 TUI）

`trendpower-py` 可以脱离 TUI 嵌到自己的 Python 代码里：

```python
import asyncio
from trendpower.foundation import Model
from trendpower.community.openai import OpenAIModelProvider
from trendpower.coding import create_coding_agent

async def main():
    provider = OpenAIModelProvider()         # 读取 OPENAI_API_KEY
    model = Model("gpt-4o-mini", provider)
    agent = await create_coding_agent(model=model)
    async for event in agent.stream({
        "role": "user",
        "content": [{"type": "text", "text": "列出当前目录下的文件。"}],
    }):
        print(event)

asyncio.run(main())
```

更多见 `trendpower-py/examples/`。

---

## Skills 加载顺序

启动时的搜索规则：

1. 若设置了 `TRENDPOWER_SKILLS_DIR`，**只**扫描这个目录（推荐全局安装时用）。
2. 否则回退到 `<cwd>/skills`，以及 CWD 祖先目录里第一个长得像 skill 目录的 `skills/`（从仓库内运行即可命中根目录的 `skills/`）。

TUI 启动后顶部会打印命中数量。显示 `skills: 0` 时先确认 `TRENDPOWER_SKILLS_DIR` 指向了仓库根目录的 `skills/`。

---

## 常见问题

**`trendpower` 命令找不到** —— `~/.local/bin` 不在 PATH 上。临时：`export PATH="$HOME/.local/bin:$PATH"`；永久：写进 `~/.zshrc`（macOS 默认）或 `~/.bashrc`。

**`No models configured`** —— 跑一次 `trendpower config model add ...` 见上面第 5 步。

**改了 `trendpower-py/trendpower/...` 没生效** —— 全局装的是非 editable wheel。要么用上面 §B 的 `--editable`，要么 `--force --reinstall`。

**TUI 启动后说 `skills: 0`** —— 第 4 步的 `TRENDPOWER_SKILLS_DIR` 没设或指错了。`echo $TRENDPOWER_SKILLS_DIR` 应指向仓库根目录的 `skills/`，且 `ls "$TRENDPOWER_SKILLS_DIR"` 能看到 `coding-plan` 等目录。

更多细节（Windows 路径、各 provider 的 base URL、`/help` 等斜杠命令、`TRENDPOWER_HOME` 隔离）见 [`trendpower-tui/README.md`](./trendpower-tui/README.md)。

---

## 进一步阅读

- [`AGENTS.md`](./AGENTS.md) — 仓库分层、约定、设计意图
- [`trendpower-py/README.md`](./trendpower-py/README.md) — 核心库 API
- [`trendpower-tui/README.md`](./trendpower-tui/README.md) — TUI 详细配置、斜杠命令、迁移说明
- [`trendpower-web/README.md`](./trendpower-web/README.md) — Web 可视化的事件协议与扩展点
