# trendpower 后端设计文档

> 本文档聚焦 `trendpower-py/` 仓库（后端 / 核心库），梳理它支持的能力、Agent 系统是如何被组织起来的，以及各层之间的边界与协作方式。前端 TUI（`trendpower-tui/`）只在涉及"如何被消费"时简单提及，不在重点讨论之列。

---

## 1. 一句话概览

trendpower 是一个 **ReAct 风格** 的 Agent 循环框架，原本由 TypeScript 移植到 Python。
核心思想：用 **极简的核心 + 中间件 + 工具** 三件套，让任何 LLM 提供方都能驱动一个能"思考 → 调用工具 → 观察结果 → 继续思考"的智能体。

整个后端是一棵自下而上的四层结构：

```
foundation  →  agent  →  coding  →  community
  原语          通用 ReAct 循环   编码场景   厂商适配
```

---

## 2. 顶层目录

```
trendpower-py/
├── trendpower/
│   ├── foundation/      # 第 1 层：Model / Message / Tool / AbortSignal
│   ├── agent/           # 第 2 层：通用 ReAct Agent + 中间件 + skills / todos
│   ├── coding/          # 第 3 层：编码专用 Agent、工具与权限
│   └── community/       # 第 4 层：OpenAI / Anthropic ModelProvider
├── skills/              # 内置 SKILL.md：coding-plan / deep-research-plan
├── examples/            # basic_openai.py / basic_anthropic.py
└── pyproject.toml
```

设计意图：
- `foundation` 是稳定的契约层，几乎不会变；
- `agent` 与具体场景无关，只关心"如何完成一次推理 + 工具循环"；
- `coding` 是 trendpower 默认面向"写代码"这个垂直场景的封装；
- `community` 是可选适配，能扩展到任何兼容厂商。

---

## 3. Foundation 层：核心原语

文件：`trendpower/foundation/{messages.py, models.py, tools.py, abort_signal.py}`

这一层只定义 **数据类型** 和 **协议（Protocol）**，没有业务逻辑。

### 3.1 Message：统一对话脚本

`messages.py` 用 `TypedDict` 定义了一套"端到端一致"的对话结构，对应四种角色：

| 角色        | 内容元素                                                                          |
|-------------|------------------------------------------------------------------------------------|
| `system`    | `TextContent`                                                                      |
| `user`      | `TextContent` \| `ImageURLContent`                                                 |
| `assistant` | `TextContent` \| `ThinkingContent` \| `ToolUseContent`（可带 `usage` / `streaming`）|
| `tool`      | `ToolResultContent`                                                                |

关键点：
- `ThinkingContent` 携带可选的 `_anthropicSignature`，保证 Claude 的 thinking 块在多轮里能被原样回填。
- `ToolUseContent` 与 `ToolResultContent` 用 `id` ↔ `tool_use_id` 配对，整套结构跟 Anthropic / OpenAI 都能双向转换。
- `NonSystemMessage = UserMessage | AssistantMessage | ToolMessage`：Agent 内部只持有这三类，`system` 由 `Model` 在调用时再注入。

### 3.2 Model & ModelProvider：可插拔的"模型调用方"

```python
class ModelProvider(Protocol):
    async def invoke(self, params: ModelProviderInvokeParams) -> AssistantMessage: ...
    def stream(self, params: ModelProviderInvokeParams) -> AsyncGenerator[AssistantMessage, None]: ...

@dataclass
class Model:
    name: str
    provider: ModelProvider
    options: Optional[Dict[str, Any]] = None
```

- `Model` 持有 `provider`、模型名和 provider 特有的 `options`（如 `temperature`、`thinking`）。
- `Model.stream(context)` 把 `ModelContext` 翻译成 `ModelProviderInvokeParams`，并自动把 `prompt` 转成 `system` 消息塞到队首。
- 想接新厂商时，只要写一个实现 `ModelProvider` 协议的类（见 `community/`）即可，**Agent 层无需任何改动**。

### 3.3 Tool：基于 Pydantic Schema 的函数工具

```python
@dataclass
class FunctionTool(Generic[P, R]):
    name: str
    description: str
    parameters: Type[P]   # pydantic BaseModel 类
    invoke: Callable[[Dict[str, Any], Optional[AbortSignal]], Awaitable[Any]]

def define_tool(*, name, description, parameters, invoke) -> FunctionTool: ...
```

- 参数使用 **pydantic** 描述（取代 TS 版本里的 zod）。
- `define_tool` 把原始 dict → 校验后的 pydantic 实例 → 调用业务 `invoke`。
- 业务侧可写 `(input)` 或 `(input, signal)` 两种签名，包装器自动适配。
- 工具结果有一种 **结构化协议**：

```python
StructuredToolSuccess = {"ok": True,  "summary": str, "data": ...}
StructuredToolError   = {"ok": False, "summary": str, "error": str, "code": str, "details": dict}
```

后续 `tool_result/runtime.py` 会把"任意返回值"归一化到这套结构上，让 UI 和模型都能拿到稳定的字段。

### 3.4 AbortSignal：协同取消

`abort_signal.py` 是 Web 平台 `AbortSignal/AbortController` 的 Python 复刻：

- `aborted` / `reason` / `throw_if_aborted()`
- `add_listener(cb)`：abort 时同步触发（被工具用于 kill 子进程）
- `wait()`：异步等待 abort，便于和 `asyncio.wait` 做"谁先完成"竞速

Agent 在每个循环步前后都会 `throw_if_aborted`；工具（如 `bash`, `grep_search`）则把 listener 接到子进程的 `kill()` 上。

---

## 4. Agent 层：ReAct 主循环

文件：`trendpower/agent/agent.py` 及周边。

### 4.1 主循环（Think → Act）

`Agent.stream(message)` 是一个 `async generator`，每次 `yield` 一个 `AgentEvent`：

```
for step in 1..maxSteps:
    1. _before_agent_step(step)
    2. _think():
         - _before_model(model_context)
         - model.stream(...)               # 一边收 snapshot 一边 yield "progress" 事件
         - 收到完整 AssistantMessage
         - _after_model(message)
         - 把 message 追加进 transcript
    3. yield {"type": "message", message}
    4. 没有 tool_use → _after_agent_run() 并返回
    5. _act(tool_uses):
         - 并行 asyncio.create_task 每个工具
         - 同时和 abort signal 竞速（FIRST_COMPLETED）
         - 每个完成的工具结果包装成 ToolMessage，append + yield
    6. _after_agent_step(step)
超出 maxSteps → 抛 "Maximum number of steps reached"
```

关键设计：
- **流式可视化**：`_derive_progress(snapshot)` 把模型流式中间态翻译成 `thinking` 或 `tool` 进度事件，TUI 可以做"实时打字 + 工具调用预览"。
- **并行工具调用**：Assistant 一次给出多个 `tool_use` 时全部 `asyncio.gather`，但用 `asyncio.wait(..., FIRST_COMPLETED)` 配合 `abort_task` 让取消能即时生效。
- **错误隔离**：单个工具异常会被包成 `"Error: ..."` 字符串作为 tool_result，不会让整个循环崩。
- **`prompt` 是可变属性**：`Agent.prompt` 有 setter，中间件可以在 `before_model` 里追加内容（Skills、Todos 都靠这个）。

### 4.2 AgentContext：贯穿一次 run 的可变共享态

```python
class AgentContext(TypedDict, total=False):
    prompt: str
    messages: List[NonSystemMessage]
    tools: Optional[List[Tool]]
    skills: Optional[List[SkillFrontmatter]]
    requestedSkillName: Optional[str]
```

Agent 内部把 context 暴露给所有中间件钩子，钩子返回的 dict 会被 `update` 合并回 context。这是中间件之间通信和状态共享的唯一约定方式。

### 4.3 Middleware：八个钩子的洋葱模型

`agent_middleware.py` 给出 8 个生命周期点：

| 钩子              | 时机                                            | 典型用途                          |
|-------------------|-------------------------------------------------|-----------------------------------|
| `beforeAgentRun`  | `stream()` 接到用户消息后、进入循环之前         | 加载磁盘资源（skills）            |
| `afterAgentRun`   | 没有更多 tool_use、即将返回                     | 落盘、统计                        |
| `beforeAgentStep` | 每一轮 think/act 开始前                         | 计数、限流                        |
| `afterAgentStep`  | 每一轮 think/act 结束后                         | 注入"步进提醒"                    |
| `beforeModel`     | 发请求前                                        | **改写 prompt**（skills/todos）   |
| `afterModel`      | 收到完整 Assistant 后                           | 改写 message、记录用量            |
| `beforeToolUse`   | 调工具前                                        | **审批 / 拦截**（见 4.5）         |
| `afterToolUse`    | 工具完成后                                      | 记录、缓存                        |

钩子按 middleware 数组顺序 **串行** 执行；返回 None 表示"不改"，返回 dict 会被合并进 context / model_context / message。`beforeToolUse` 还可以返回特殊形态：

```python
{"__skip": True, "result": <substitute>}
```

被识别为"跳过执行 + 用 substitute 顶替结果"，权限审批用这一机制把 deny 翻成普通 tool_result。

### 4.4 工具结果归一化：`tool_result/runtime.py` + `tool_result/policy.py`

工具实际返回的对象可能五花八门：str / dict / 结构化 ok / 结构化 error / "Error: ..." 前缀。
`format_tool_result_for_message(tool_name, result)` 做了三件事：

1. **归一化**：用 `_is_structured_success/error` 判断，否则按字符串/json 兜底，统一映射到 `NormalizedToolResult`，并从 `code` 推断 `errorKind`（`invalid_input` / `not_found` / `environment_missing` / `execution_failed`…）。
2. **按 tool 应用策略**：`get_tool_result_policy(tool_name)` 给每个工具一份"上下文友好"的策略：
   - `list_files` / `glob_search` / `grep_search` / `file_info` / `mkdir` / `move_path`：`preferSummaryOnly=True, maxStringLength=1000`，只把 summary 喂给模型，省 token；
   - `read_file`：`maxStringLength=12000`，能放更长内容；
   - 默认 4000 字符。
3. **超限降级**：先序列化完整 payload，超出就退回到只带 truncated summary 的版本，再不行就截断字符串。

`tool_result.summary.summarize_tool_result_text(content)` 则反向把"格式化后的字符串"再压成一行，用于 UI 展示。`read_file` 特殊处理：直接把文件内容当字符串原样塞进 tool_result，避免被 JSON 包一层。

### 4.5 内置中间件 1 —— Todos 系统

`agent/todos/todos.py` 提供一对 `(tool, middleware)`：

- **工具** `todo_write(todos[], merge)`：模型可以创建/合并/替换一份会话级 todo 列表。
- **中间件**：
  - `beforeModel`：每过 `_STEPS_SINCE_WRITE`（10）+ `_STEPS_BETWEEN_REMINDERS`（10）步还没动 todos，就向 prompt 追加 `<todo_reminder>...</todo_reminder>` 提醒。
  - `afterToolUse`：监听 `todo_write` 调用，重置计数器。

效果：长任务里模型不会"忘了 todo 列表"，但短任务里也不会被打扰。

### 4.6 内置中间件 2 —— Skills 系统

`agent/skills/skills_middleware.py`：

- `beforeAgentRun`：扫描传入的 `skills_dirs`，每个子目录读 `SKILL.md` 的 YAML frontmatter（`name`/`description`/`path`），去重后写入 `agentContext.skills`。
- `beforeModel`：把所有 skills 渲染成 XML 注入 prompt：

  ```xml
  <skill_system>
    <instructions>渐进加载模式：匹配到再 read_file 详细 SKILL.md ...</instructions>
    <skills>
      <skill name="coding-plan" path="…/SKILL.md">…description…</skill>
      ...
    </skills>
  </skill_system>
  ```

- 若调用方设置了 `requestedSkillName`（例如 TUI 中通过 slash command 显式选择），还会再插一段 `<explicit_skill_invocation>` 块，强制模型先读那个 SKILL.md。

**"渐进加载"** 是核心理念：只把 skill 的 *目录 + 描述* 放进 prompt，详细工作流让 Agent 自己用 `read_file` 取回，避免无意义膨胀上下文。

仓库内置两个 skill：
- `coding-plan`：只读 plan-mode，写一份 `plans/<name>.md` 出来，不动源码。
- `deep-research-plan`：研究型，配合搜索工具产出研究/文章计划。

---

## 5. Coding 层：默认的编码 Agent

文件：`trendpower/coding/{agents,tools,permissions}`。

### 5.1 `create_coding_agent`

`agents/lead_agent.py::create_coding_agent` 是工厂函数，组合出"开箱即用的编码 Agent"：

1. 默认 `cwd = os.getcwd()`；如果 `AGENTS.md` 存在，作为 **第一条 user 消息** 自动注入（"已自动加载，内容如下…"）。
2. 默认 `skills_dirs = [<cwd>/.agents/skills]`，叠加 4.6 的 skills 中间件。
3. `create_todo_system()` → 拿到 todo 工具 + 提醒中间件。
4. 如果调用方传了 `ask_user`（人审回调），叠加 `coding_approval_middleware`。
5. 如果调用方传了 `ask_user_question`（结构化提问回调），把对应工具加进 toolset。
6. 系统 prompt：

   ```
   <agent name="trendpower" role="leading_agent" .../>
   <working_directory dir="…"/>
   <tool_usage>… 一组工具使用守则 …</tool_usage>
   <notes>不要起本地服务器；简单问候简单回答 …</notes>
   ```

7. 默认 toolset：`bash, file_info, list_files, glob_search, grep_search, mkdir, move_path, read_file, write_file, str_replace, apply_patch, todo_write (+ ask_user_question 可选)`。

整个 Agent 就是 **`Agent(model, prompt, messages, tools, middlewares)`** 的精心组装。

### 5.2 编码工具一览

| 工具          | 输入要点                                                                                                                          | 备注                                                                                  |
|---------------|------------------------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------|
| `bash`        | `description`, `command`                                                                                                           | 跨平台 shell 解析：`$TRENDPOWER_BASH_SHELL` → `zsh/bash/sh` → Windows fallback to cmd.exe |
| `file_info`   | `path` 绝对路径                                                                                                                    | 返回 kind/size/mtime/ctime                                                            |
| `list_files`  | `path`, `recursive?`, `maxDepth?`, `limit?`, `maxChars?`                                                                           | 默认深度 3，限 200 项 / 12000 字符                                                    |
| `glob_search` | `path`, `pattern`, `limit?`, `maxChars?`                                                                                           | 基于 `Path.glob`                                                                      |
| `grep_search` | `path`, `pattern`, `glob?`, `caseSensitive?`, `limit?`, `maxChars?`                                                                | 调用 `rg`；缺失时返回 `RG_NOT_FOUND` 让模型清楚环境问题                               |
| `mkdir`       | `path`, `recursive?`                                                                                                               | 默认递归                                                                              |
| `move_path`   | `from`, `to`（注意 `from_` 别名）                                                                                                  | `shutil.move`                                                                         |
| `read_file`   | `path`, `startLine?`, `endLine?`, `maxChars?`                                                                                      | 整文件读且未截断 → 返回原文；否则返回 `n: line` 形式                                  |
| `write_file`  | `path`, `content`                                                                                                                  | 自动创建父目录                                                                        |
| `str_replace` | `path`, `old`, `new`, `count?`                                                                                                     | `old` 必须非空；找不到 → `NOT_FOUND`                                                  |
| `apply_patch` | `patch`（unified diff，**header 必须是绝对路径**）                                                                                 | 自实现 hunk 解析；不支持 `+++ /dev/null` 删除                                         |
| `todo_write`  | `todos[], merge`                                                                                                                   | Agent 层内置工具，详见 4.5                                                            |
| `ask_user_question` | 1–4 个并行问题，每题 2–4 个选项、`multi_select`                                                                            | 由宿主 UI 提供 callback；结果带校验                                                   |

所有路径**强制绝对路径**（`ensure_absolute_path`）。Windows 兼容是显式考虑过的：`bash` 解析、`is_within_directory`、`os.path.isabs` 等都做了跨平台处理。

### 5.3 权限 / 审批系统

`coding/permissions/` 是一个完整的"工具执行需用户拍板"机制：

```
CODING_TOOLS_REQUIRING_APPROVAL = [bash, write_file, str_replace, apply_patch, mkdir, move_path]
```

`create_coding_approval_middleware(cwd, requires_approval, ask_user, approval_persistence?)`：

- `beforeToolUse` 钩子：
  1. 若工具不在白名单要求，直接放行。
  2. 否则先从 `approval_persistence.load_allow_list(cwd)` 拿到"项目级已批准列表"。
  3. 命中即放行。
  4. 否则调 `ask_user(tool_use)` 等待 UI 给出 `ApprovalDecision`：
     - `deny` → 返回 `__skip` + "用户拒绝执行 …"（模型据此换策略）。
     - `allow_once` → 仅本次放行。
     - `allow_always_project` → 调 `persist_allowed_tool(cwd, tool_name)` 把名字写进项目 allow list。

`ApprovalManager` + `global_approval_manager` 是把"异步审批请求"路由给 UI 的队列管理器：

- 最多挂 20 个请求，超出直接 deny；
- 同一时刻只暴露 `_current_request` 给订阅者（典型订阅者：TUI 弹窗）；
- UI 通过 `respond(decision)` 回写结果，触发 `future.set_result()`，于是 `ask_user` 协程恢复执行。

`ApprovalPersistence` 是 `Protocol`：宿主自行决定怎么存（YAML、SQLite 都行）；后端只关心两个方法。

`ask_user_question` 工具走同一套模式（`AskUserQuestionManager` + `global_ask_user_question_manager`）：模型主动问、宿主 UI 应答、Agent 协程被解锁。

---

## 6. Community 层：厂商适配

文件：`trendpower/community/{openai,anthropic}/{model_provider.py,utils.py,stream_utils.py}`。

每个 provider 必须实现 `ModelProvider` 协议的两个方法：`invoke` 和 `stream`。流程都是：

```
ModelProviderInvokeParams
   ↓ utils.convert_to_<vendor>_messages / convert_to_<vendor>_tools
厂商 SDK 调用（一次性 or 流式）
   ↓ stream_utils.StreamAccumulator.push(event) → snapshot()
   ↓ utils.parse_assistant_message
AssistantMessage（含 usage）
```

### 6.1 OpenAI

- 用 `AsyncOpenAI`；默认 `temperature=0`，再用 `options` 覆盖。
- `convert_to_openai_messages` 把 `thinking` 收进 `reasoning_content`、`tool_use` 拼进 `tool_calls`。
- 工具用 `model_json_schema()` 转成 OpenAI function schema。
- 流式时打开 `stream_options.include_usage` 以拿到 token 用量。

### 6.2 Anthropic

- 用 `AsyncAnthropic`；`extract_system_prompt` 把 `system` 消息单独抽出来作为 API 参数（Anthropic 风格）。
- 自动管理 `thinking.budget_tokens`：未指定时取 `max_tokens * 0.8`。
- `tool_result` 在 Anthropic 里要塞回 `user` 角色 — 转换函数已经处理好。
- `_anthropicSignature` 在 transcript 里被保留，下一轮回填时不会失效。

### 6.3 StreamAccumulator（两边都有，但实现不同）

把厂商的流式增量（chunk / event）拼成一个完整 `AssistantMessage`，`snapshot()` 返回当前累计状态，并标 `streaming=True`。Agent 拿到这些 snapshot 后只用其推导进度事件，不会重复入库——只有最后的"非 streaming"消息才进 transcript。

---

## 7. 后端能力清单（一句话总结）

- **统一的对话脚本** —— 多模态、tool_use/tool_result、thinking，跨厂商互通。
- **可流式、可取消、可观测的 ReAct 循环** —— 进度事件、并行工具、abort 协同、maxSteps 上限。
- **8 个生命周期钩子的中间件系统** —— 改 prompt / 改消息 / 拦工具 / 替结果都行。
- **结构化工具协议 + 输出归一化与策略化截断** —— 上下文友好、错误可分类。
- **Skills（渐进加载）+ Todos（提醒）** —— 长任务可控、可扩展。
- **完整的工具集 + 编码 Agent** —— bash / 文件 / 搜索 / patch / mkdir / move 一应俱全。
- **细粒度审批与一次/项目级白名单** —— 执行危险动作前可暂停人审。
- **结构化提问工具** —— 让模型用受控选项问用户问题，宿主 UI 异步答复。
- **多厂商可插拔** —— OpenAI 兼容（含 Ark/OpenRouter 等）+ Anthropic（含 thinking / signature）。
- **跨平台** —— shell 解析、绝对路径、Windows 兜底全部考虑。

---

## 8. 一次请求的端到端时序

下面以"用户消息 → 模型决定调用 `read_file` → 再总结"为例，把流程串一遍：

```
User UI ──user_msg──▶ Agent.stream(user_msg)
                       │
                       ├─ beforeAgentRun()                # skills 中间件加载 SKILL.md
                       │
                       ├─ Step 1: beforeAgentStep(1)
                       │   ├─ beforeModel(ctx)            # skills/todos 改 prompt
                       │   ├─ model.stream(ctx)           # 厂商 SDK 流式
                       │   │     │ snapshot...            ─►  yield progress(thinking|tool)
                       │   │     ▼
                       │   │   AssistantMessage(tool_use=read_file)
                       │   ├─ afterModel(msg)
                       │   ├─ append + yield message
                       │   │
                       │   ├─ _act(tool_uses)
                       │   │   ├─ beforeToolUse(tu)       # approval 中间件: ask_user → allow
                       │   │   ├─ tool.invoke(input, signal)
                       │   │   ├─ afterToolUse(tu, result)
                       │   │   └─ tool_result.runtime.format(…) → ToolMessage
                       │   └─ append + yield message
                       │
                       ├─ Step 2: beforeAgentStep(2)
                       │   ├─ beforeModel → ... → AssistantMessage(只含 text)
                       │   ├─ 没有 tool_use
                       │   └─ afterAgentRun() → return
                       ▼
                  AsyncGenerator 结束
```

整个循环里：
- **任何一步都可被 `agent.abort()` 中断**（透过 `AbortSignal` 传到 SDK / 子进程）。
- **任何工具失败** 都被包成普通 `tool_result`（含 `code` / `errorKind`），让模型自行决定下一步。
- **任何中间件** 都可以悄悄拦截、改写、跳过——这是 trendpower 扩展能力的主入口。

---

## 9. 想加点东西时该改哪儿？

| 需求                                  | 推荐位置                                        |
|---------------------------------------|-------------------------------------------------|
| 新增一个 LLM 厂商                     | `community/<vendor>/` 实现 `ModelProvider`      |
| 新增一个通用工具                      | `agent/`（如果跨场景）或 `coding/tools/`        |
| 给所有 Agent 加日志 / 限流 / 缓存     | 写一个 middleware，在工厂里挂上                 |
| 自定义"危险操作要不要批准"            | 改 `requires_approval.py` 的列表 + 实现 `ApprovalPersistence` |
| 给模型多塞点上下文                    | middleware 的 `beforeModel` 改 `prompt`         |
| 新增一种 skill 工作流                 | 在 `skills/<name>/SKILL.md` 写 frontmatter      |
| 改变 tool 输出在上下文里的占用        | `tool_result/policy.py` 改策略                  |

---

## 10. 还没做 / 可能要做

读源码时能观察到一些"留白"：

- `apply_patch` 不支持 `+++ /dev/null` 删除文件——计划性放弃，希望模型用 `bash rm` 或新工具完成。
- 没有 retry / 限流中间件，模型层调用失败直接抛。
- ToolResult 的策略表是硬编码的，没暴露成参数。
- `Agent.options` 目前只有 `maxSteps`，没有 backoff、并发上限之类。
- `community/` 只有 OpenAI / Anthropic 两个适配，按设计目的 Bedrock / Vertex / 本地 vLLM 都可以另写。

这些都是后续可扩展的方向，但目前的边界已经足以驱动一个完整的 TUI 编码 Agent（即 `trendpower-tui/trendpower`）。




后续优化方向
一、核心范式:从 prompt engineering → context engineering → harness engineering
  
  业界已经形成共识:"agent 在生产里失败,几乎都是 harness 设计差,而不是模型弱。" Harness =
  模型外面那层脚手架:工具、上下文管理、控制流、验证回路、权限、记忆、编排。当下的亮点集中在 8 个方向:

  ┌─────┬──────────────┬────────────────────────────────────────────────────────────────────────────────────────────┐
  │  #  │   亮点方向   │                                 业界 state-of-the-art 做法                                 │
  ├─────┼──────────────┼────────────────────────────────────────────────────────────────────────────────────────────┤
  │ 1   │ 上下文压缩   │ 摘要时保留架构决策/未解 bug/实现细节,丢弃冗余工具输出;"清空旧工具结果"是最轻量的压缩;先求  │
  │     │              │ 全(recall)再求精(precision)                                                                │
  ├─────┼──────────────┼────────────────────────────────────────────────────────────────────────────────────────────┤
  │ 2   │ 持久记忆/笔  │ agent 在上下文窗口之外维护记忆文件(memory tool /                                           │
  │     │ 记           │ claude-progress.txt),跨会话累积知识、记录进度                                              │
  ├─────┼──────────────┼────────────────────────────────────────────────────────────────────────────────────────────┤
  │ 3   │ 按需检索(JIT │ 上下文里存引用(文件路径/查询/链接)而非内容,运行时用工具动态加载;渐进式披露                 │
  │     │ )            │                                                                                            │
  ├─────┼──────────────┼────────────────────────────────────────────────────────────────────────────────────────────┤
  │ 4   │ 工具设计 =   │ 工具要自包含、抗错、参数无歧义;忌臃肿工具集——"人类工程师都说不清该用哪个工具,agent 更不行" │
  │     │ agent 的 UX  │                                                                                            │
  ├─────┼──────────────┼────────────────────────────────────────────────────────────────────────────────────────────┤
  │ 5   │ 验证/反馈回  │ agent 要像用户一样测(浏览器自动化);实现新功能前先跑 e2e;用                                 │
  │     │ 路           │ feature-list(pass/fail)防止"假装做完"                                                      │
  ├─────┼──────────────┼────────────────────────────────────────────────────────────────────────────────────────────┤
  │ 6   │ 规划/任务分  │ plan-and-execute 分离;plan mode;一次只做一个 feature + 标准化的会话启动清单                │
  │     │ 解           │                                                                                            │
  ├─────┼──────────────┼────────────────────────────────────────────────────────────────────────────────────────────┤
  │ 7   │ 子 agent/多  │ 子 agent 用隔离的上下文窗口,只回传 1–2k token 的蒸馏摘要;三 agent                          │
  │     │ agent 编排   │ harness(规划/生成/评估,GAN 式生成器+评判器)                                                │
  ├─────┼──────────────┼────────────────────────────────────────────────────────────────────────────────────────────┤
  │ 8   │ 意图级权限 + │ 权限按意图而非命令名(filesystem_delete/network_outbound);两级分类器(快速门 +               │
  │     │  可观测性    │ 仅对可疑项推理);结构化 trace + evals                                                       │
  └─────┴──────────────┴────────────────────────────────────────────────────────────────────────────────────────────┘

  ---
  二、trendpower 现状对照(我按代码逐项打分)
  
  ┌───────────────┬──────────────────────────────────────────────────────────────────────────┬──────────────────────┐
  │     方向      │                               trendpower 现状                                │         评价         │
  ├───────────────┼──────────────────────────────────────────────────────────────────────────┼──────────────────────┤
  │ 1 上下文压缩  │ 刚加的 agent/compaction/                                                 │ ✅                   │
  │               │                                                                          │ 有了,但还是"基础版"  │
  ├───────────────┼──────────────────────────────────────────────────────────────────────────┼──────────────────────┤
  │ 2 持久记忆    │ 只有启动时读 AGENTS.md;todos 是纯内存,关掉就丢                           │ ❌ 大缺口            │
  ├───────────────┼──────────────────────────────────────────────────────────────────────────┼──────────────────────┤
  │ 3 按需检索    │ 有 read_file/grep/glob,但没有"存引用不存内容"的纪律                      │ 🟡 半                │
  ├───────────────┼──────────────────────────────────────────────────────────────────────────┼──────────────────────┤
  │ 4 工具设计    │ 工具有结构化错误 +                                                       │ ✅ 偏强              │
  │               │ 按工具名的结果格式化策略(tool_result/policy.py),这点很到位               │                      │
  ├───────────────┼──────────────────────────────────────────────────────────────────────────┼──────────────────────┤
  │ 5 验证回路    │ 完全没有。bash 能跑测试,但没有任何机制逼它验证/防止"假完成"              │ ❌ 最大缺口          │
  ├───────────────┼──────────────────────────────────────────────────────────────────────────┼──────────────────────┤
  │ 6 规划        │ 有 coding-plan 等 skill,但无强制 plan mode                               │ 🟡 半骨架            │
  ├───────────────┼──────────────────────────────────────────────────────────────────────────┼──────────────────────┤
  │ 7 子 agent    │ 单 agent,无委派                                                          │ ❌ 缺口              │
  ├───────────────┼──────────────────────────────────────────────────────────────────────────┼──────────────────────┤
  │ 8 权限        │ 有审批中间件,但按工具名(requires_approval.py 里                          │ 🟡 偏粗              │
  │               │ bash/write_file/...)。批准一次 "bash" = 放行所有 bash                    │                      │
  ├───────────────┼──────────────────────────────────────────────────────────────────────────┼──────────────────────┤
  │ — 可观测性    │ 无结构化 trace,无 evals                                                  │ ❌                   │
  ├───────────────┼──────────────────────────────────────────────────────────────────────────┼──────────────────────┤
  │ —             │ ask_user_question + 审批条                                               │ ✅ 有                │
  │ human-in-loop │                                                                          │                      │
  └───────────────┴──────────────────────────────────────────────────────────────────────────┴──────────────────────┘

  一句话总结:trendpower 的"输入侧"(工具质量、结构化结果、人机交互、刚补的压缩)做得不错,但"控制侧"(验证、记忆、规划强制、子 
  agent、意图权限)基本空白——而后者正是当下 harness engineering 最值钱的部分。

  ---
  三、后续优化方向(按 ROI 排序)
  
  Tier 1 — 立刻能拉高"任务完成质量"

  ① 验证/反馈回路(最高优先级)
  这是业界反复强调、trendpower 完全没有、且直接决定"任务到底做没做对"的环节。具体落地:
  - 一个 afterToolUse/afterAgentStep 中间件:检测到写类工具(write/str_replace/apply_patch)后,提示/引导跑测试或 
  e2e,而不是让模型自己决定要不要验证。
  - 一个 definition_of_done / feature-checklist 工具(对标 Anthropic 的 200+ feature JSON):把任务拆成可验收项,每项
  pass/fail,未全绿不许声称完成——直击"premature completion"。

  ② 持久记忆 + 进度文件
  - memory 工具 + 记忆目录(跨会话);外加 .trendpower/progress.md 模式(每步追加"做了什么/下一步"),长任务断点续作。
  - todos 从纯内存升级成可落盘,关闭 TUI 不丢。

  ③ 子 agent / Task 工具
  - 隔离上下文跑子任务,只回传 1–2k token 摘要。和压缩天然互补(子 agent 是"空间隔离",压缩是"时间压缩")。agent.py
  已足够通用,作为一个工具即可。
  
  Tier 2 — 把已有能力升级到 state-of-art

  ④ 压缩精修:在我做的基础上加"清空旧工具结果"这一更轻的档位(只删冗余 tool_result,保留对话),作为全量摘要前的第一道;摘要
  prompt 已经在保留决策/待办,可再强化。

  ⑤ Plan mode 强制化:只读规划 → 用户批准 → 解锁写工具(复用现有审批管理器)。骨架已在 skills 里。

  ⑥ 意图级权限:把审批从"工具名"升级为"参数/意图"感知——例如对 bash
  做轻量分类:读类命令(ls/cat/grep)自动放行,写/删/网络类才弹审批。当前粒度太粗,要么烦要么不安全。

  Tier 3 — 工程化/可持续

  ⑦ 可观测性 + evals:结构化 run trace(便于调试)+ 一个小 eval 集(防回归)。没有度量就无法持续优化 harness。
  ⑧ 工具 UX 审计:随着 MCP 工具注入,工具集会膨胀。定期审计 token
  成本、去重语义重叠的工具、确保描述能让模型明确"何时用哪个"。

  ---
  我的建议:先做 ①验证回路(最直接提升"完成质量",且 trendpower 零基础收益最大),再做 ②记忆/进度 和 ③子
  agent。这三个补齐后,trendpower 就从"能跑 ReAct 循环"进化到"能可靠完成长任务"。
  
