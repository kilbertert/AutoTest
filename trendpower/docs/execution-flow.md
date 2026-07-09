# 执行路径：从 `trendpower` 启动到回答一个问题

本文追踪一次完整的运行：你在终端敲下 `trendpower`，到你提一个问题、agent 调用工具、结果显示回界面，中间到底经过了哪些文件。文件引用格式为 `路径:行号`。

> 三个包的依赖与分工见文末 [包之间的关系](#包之间的关系)。

---

## 阶段 0：进程入口（main 函数在哪）

入口是一个 console script，注册在 `trendpower-tui/pyproject.toml`：

```toml
[project.scripts]
trendpower = "trendpower_tui.__main__:main"
```

敲 `trendpower` → 调用 `trendpower-tui/trendpower_tui/__main__.py` 的 `main()`：

```
main()  (__main__.py:11)
  ├─ len(sys.argv) > 1  → CLI 模式: from .commands import cli; cli()   # 例: trendpower config model add
  └─ 否则               → TUI 模式: from .app import trendpowerApp; trendpowerApp().run()
```

- **CLI 分支** → `commands/__init__.py` → `commands/cli.py`（Click 命令树）。
- **TUI 分支**（无参数，最常用）→ `app.py` 的 `trendpowerApp`。下文均按 TUI 分支。

---

## 阶段 1：启动初始化（`trendpowerApp().run()` → `on_mount`）

`trendpowerApp` 是一个 Textual App。`run()` 后 Textual 先调用 `compose()` 摆放控件，再调用 `on_mount()` 做初始化。

**① `compose()`**（`app.py:76`）——只摆 UI 控件，涉及 `tui/widgets/*`：
`BrandHeader`、`MessageHistory`、`TodoPanel`、`StreamingIndicator`、`CommandList`、`StatusFooter`、`InputBox`、`ApprovalBar`、`AskUserQuestionBar`。

**② `on_mount()`**（`app.py:90`）——核心启动流程：

| 步骤 | 代码位置 | 涉及文件 |
|---|---|---|
| 设环境变量 `TRENDPOWER_HOME` | `app.py:91` | `config/store.py` |
| 发现 skills 目录 | `app.py:94` | `tui/skill_paths.py` |
| 加载斜杠命令 + 统计 skills | `app.py:95` | `tui/command_registry.py` |
| 启动 MCP servers | `app.py:98` | `mcp/lifecycle.py` → `mcp/config_loader.py` → `trendpower/community/mcp/*` |
| **创建 agent** | `app.py:102` → `_try_create_runner()` | 见下方展开 |
| 订阅审批/提问管理器 | `app.py:103` → `_subscribe_to_managers()` | `trendpower/coding/permissions/*`、`coding/tools/ask_user_question_manager.py` |
| 没配置模型则起首次向导 | `app.py:109` | `tui/widgets/first_run_wizard.py` |

**③ `_try_create_runner()`**（`app.py:264`）——TUI 与核心库 `trendpower` 的接合点：

```
_try_create_runner()  (app.py:264)
  ├─ is_trendpower_setup_complete() / load_config()        → config/store.py + config/schema.py
  ├─ 按 entry.provider 选 provider:
  │    anthropic → trendpower.community.anthropic.AnthropicModelProvider   (community/anthropic/model_provider.py)
  │    其它      → trendpower.community.openai.OpenAIModelProvider          (community/openai/model_provider.py)
  ├─ model = Model(name, provider, options)            → foundation/models.py:37
  ├─ approval_persistence = SettingsApprovalPersistence()  → settings/approval_persistence.py
  └─ agent = await create_coding_agent(...)            → coding/agents/lead_agent.py:38   ★关键★
        ↓
     self.runner = AgentRunner(agent, target=self)     → tui/agent_runner.py:53
```

**④ `create_coding_agent()`**（`coding/agents/lead_agent.py:38`）——组装真正的 `Agent`，把整个核心库串起来：

- 读 `cwd/AGENTS.md`（若存在）塞进首条消息（`lead_agent.py:59`）；
- 建 todo 系统 → `agent/todos/todos.py`；
- 拼装 **middlewares**（顺序关键）：
  1. `agent/compaction/compaction.py`（`create_compaction_middleware`，插在最前，`lead_agent.py:86`）
  2. `agent/skills/skills_middleware.py`（`create_skills_middleware`）
  3. todo middleware
  4. `coding/permissions/coding_approval_middleware.py`（`create_coding_approval_middleware`）
- 注册 **12 个内置工具** + ask_user_question + MCP 工具（`lead_agent.py:125`）：
  `bash / file_info / list_files / glob_search / grep_search / mkdir / move_path / read_file / write_file / str_replace / apply_patch / todo`，均在 `coding/tools/*.py`；
- 拼系统 prompt（`lead_agent.py:104`）；
- `return Agent(model, prompt, messages, tools, middlewares)` → `agent/agent.py:40`。

启动结束，界面等待输入（`app.py:112` 聚焦 `InputBox`）。

---

## 阶段 2：你输入一个问题并回车

```
InputBox 回车
  → CommandSubmitted 消息                       (tui/widgets/input_box.py)
  → app.on_command_submitted(event)             (app.py:388)
        ├─ resolve_builtin_command(text)         (tui/command_registry.py)
        │     /clear /exit /help /model /mcp → 各自分支，不进 agent
        └─ 普通问题:
              build_prompt_submission(text, commands)   (command_registry.py)
              → self.submit_user_text(text, requested_skill)   (app.py:423, @work 后台协程)
                  → self.runner.submit(...)              (tui/agent_runner.py:60)
```

**`AgentRunner.submit()`**（`agent_runner.py:60`）：

1. 把用户消息 echo 到界面；
2. 发 `StreamingChanged(True)` → 显示「思考中」指示器；
3. `async for event in self.agent.stream(user_message)` —— 进入核心循环，并以 50ms 窗口批量刷新 UI（`agent_runner.py:69`）。

---

## 阶段 3：核心 ReAct 循环（`Agent.stream`）

全部在 `agent/agent.py:100`。每轮 step 做 **think → act**：

```
Agent.stream(message)                          agent/agent.py:100
  ├─ 追加 user 消息, 跑 _before_agent_run()  →  遍历 middleware.beforeAgentRun
  └─ for step in 1..maxSteps(100):
       ├─ _before_agent_step(step)
       │
       ├─ THINK:  _think()                     agent/agent.py:141
       │     ├─ 组 ModelContext{prompt,messages,tools,signal}
       │     ├─ _before_model(ctx)             → middleware.beforeModel（compaction 压缩历史 / skills 注入 <skill_system>）
       │     └─ async for snapshot in self.model.stream(ctx):   foundation/models.py:48
       │            model.stream → provider.stream               community/openai|anthropic/model_provider.py
       │                ↑ provider 真正发 HTTP 到 LLM，边收边吐 AssistantMessage 快照
       │            每个 streaming 快照 → yield progress 事件 → UI 显示 "Thinking..."/"Running xxx..."
       │     完整 assistant 消息 append 到 transcript
       │
       ├─ _after_model(msg)
       ├─ yield {"type":"message", msg}        → UI 渲染助手回复
       │
       ├─ tool_uses = 提取 tool_use 块          agent/agent.py:171
       ├─ 若无工具调用 → _after_agent_run() → return（对话结束）★
       │
       └─ ACT:  _act(tool_uses)                agent/agent.py:174  （多工具 **并行** asyncio.create_task）
             ├─ 对每个 tool_use:
             │    ├─ 按 name 找 Tool
             │    ├─ _before_tool_use(tu)       → 审批 middleware 拦截!
             │    │       coding_approval_middleware.py: 需审批的工具 → ask_user
             │    │         → approval_manager → 弹 ApprovalBar 等确认
             │    │         （"总是允许"持久化 → settings/approval_persistence.py）
             │    ├─ result = await tool.invoke(input, signal)   foundation/tools.py:91
             │    │       → coding/tools/<tool>.py （bash 跑子进程 / read_file 读盘 / apply_patch 改文件 …）
             │    └─ _after_tool_use(tu, result)
             │
             └─ 每个结果:
                  format_tool_result_for_message(name, result)   agent/tool_result/runtime.py
                    （按 tool_result/policy.py 策略截断/精简）
                  → 包成 tool_result 消息 append 到 transcript
                  → yield {"type":"message"} → UI 渲染
       │
       └─ _after_agent_step(step) → 回到循环顶部，把工具结果喂回模型继续 think
```

**退出条件**：某一轮模型不再发起工具调用（`agent.py:125` `if not tool_uses: return`）。否则一直「think → 调工具 → 喂回结果 → 再 think」，直到任务完成或撞 `maxSteps=100`。

---

## 回到 UI：结果如何显示

`Agent.stream` 每 `yield` 一个事件，`AgentRunner.submit`（`agent_runner.py:79`）接住：

- `type=="message"` → `AgentMessageEvent` → `app.on_agent_message_event`（`app.py:487`）→ `MessageHistory.append_message`（`tui/widgets/message_history.py`，用 `tool_result/summary.py` 的 `summarize_tool_result_text` 把工具结果压成一行展示）。
- `type=="progress"` → `AgentProgressEvent` → 更新 `StreamingIndicator`。
- 循环结束 → `finally` 发 `StreamingChanged(False)`，指示器消失。

---

## 一句话串联

```
trendpower  →  __main__.main  →  trendpowerApp.run
   →  on_mount  →  _try_create_runner  →  create_coding_agent(lead_agent.py)  =>  Agent + 工具 + 中间件
   →  [提问]  →  on_command_submitted  →  AgentRunner.submit  →  Agent.stream
        →  循环{ think: model.stream→provider→LLM ; act: tool.invoke + 审批 }  直到模型不再调工具
   →  事件流回 AgentRunner  →  trendpowerApp  →  MessageHistory 渲染
```

---

## 包之间的关系

仓库有三个独立可安装的 Python 包，依赖是**单向**的：

```
trendpower-web  ──depends──▶  trendpower-tui  ──depends──▶  trendpower  (trendpower-py)
   (trendpower_web)              (trendpower_tui)              (核心库, 无上层依赖)
```

依据各自的 `pyproject.toml`：

| 包 | 目录 / 导入名 | 依赖 | 角色 |
|---|---|---|---|
| `trendpower` | `trendpower-py/` → `trendpower` | openai, anthropic, pydantic, **mcp**, jsonschema, … | 核心 ReAct 库：foundation / agent / coding / community。**不依赖任何上层。** |
| `trendpower-tui` | `trendpower-tui/` → `trendpower_tui` | **trendpower**, textual, rich, click, pyyaml | 终端 UI + CLI。把核心库接到 Textual 界面上。 |
| `trendpower-web` | `trendpower-web/` → `trendpower_web` | **trendpower**, **trendpower-tui**, aiohttp | 终端 REPL + 浏览器实时可视化每轮发给 LLM 的 prompt。 |

- **`trendpower-tui` 依赖 `trendpower`**：是的（`trendpower-tui/pyproject.toml` 把 `trendpower` 列为依赖）。TUI 只做「界面 + 事件桥接」，真正的 agent 循环、工具、provider 全在核心库里。反向不成立——`trendpower` 不知道 TUI 的存在。
- **`trendpower-web` 依赖 `trendpower` 和 `trendpower-tui`**：复用 TUI 的组件，再叠加 `instrumented_providers.py` 拦截发给 LLM 的请求，通过 `broadcaster.py` + aiohttp `server.py` 推到浏览器 `static/`。

### 为什么 MCP 代码分布在两处

MCP 看起来"在 tui 目录下"，其实是**实现**和**接线**分开放了：

| 位置 | 内容 | 性质 |
|---|---|---|
| `trendpower-py/trendpower/community/mcp/` | `MCPManager`、`MCPServerConfig`、`session`、`transports`、`tool_adapter`、`toolset`、`load_servers_from_file` | **真正的 MCP 协议客户端**。可复用、与界面无关，所以放在核心库的 `community`（第三方集成）层。 |
| `trendpower-tui/trendpower_tui/mcp/` | `lifecycle.py`（`MCPLifecycle`）、`config_loader.py` | **进程级接线胶水**：到哪找 `mcp_servers.json`（`$TRENDPOWER_HOME` / `~/.trendpower`）、把一个 `MCPManager` 绑到 Textual 的 mount/unmount 生命周期、支撑 `/mcp` 斜杠命令。 |

也就是说，`trendpower_tui/mcp/` 不是 MCP 的实现，它 `from trendpower.community.mcp import MCPManager, ...`（见 `lifecycle.py:15`、`config_loader.py:17`），只是**在 TUI 进程里调度核心库那套 MCP**。配置路径解析、生命周期、斜杠命令这些本来就是前端/进程特有的关注点，所以留在前端包，而不污染可复用的核心库。这正是 `foundation/agent/coding/community` 分层想要的效果：核心库保持通用，集成细节下沉到 `community`，进程相关的胶水留在前端。
