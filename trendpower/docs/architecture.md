# trendpower 架构全解 — 每个文件做什么、整体如何运转

这份文档的目标：**任何人读完后，都能清楚地说出 trendpower 每个代码文件的职责、各层如何协作、一次对话从输入到输出经历了什么。**

阅读顺序建议：先看「一、整体心智模型」和「三、一次对话的完整生命周期」建立全局观，再按需查「四～七」的逐文件说明。最后的「九、文件索引表」可当字典用。

---

## 一、整体心智模型

trendpower 是一个**构建 ReAct 风格（Reason + Act）agent 循环**的小型库。一句话概括它的运转：

> 模型「思考」（think）产出回复，如果回复里带工具调用就「行动」（act）执行工具，把结果「观察」（observe）后塞回对话，再让模型思考下一步，如此循环，直到模型不再调用工具为止。

整个系统分成**两个 Python 包 + 一份共享 skills 目录**：

```
helixentpy/
├── trendpower-py/        核心库（包名 trendpower）——— 不依赖任何 UI，可独立 import
│   ├── trendpower/foundation/    第 1 层：最底层原语（消息 / 模型 / 工具 / 取消信号）
│   ├── trendpower/agent/         第 2 层：通用 ReAct 循环 + 中间件 + 技能 + 待办
│   ├── trendpower/coding/        第 3 层：编码专用 agent、工具、权限审批
│   ├── trendpower/community/     第 4 层：第三方集成（OpenAI / Anthropic / MCP）
│   └── skills/               内置技能（每个是一个含 SKILL.md 的文件夹）
│
└── trendpower-tui/       终端 UI（包名 trendpower_tui）——— 基于 Textual，依赖 trendpower
    └── trendpower_tui/   App、widgets、配置、设置、MCP 生命周期、CLI
```

**最重要的分层原则（务必记住）：依赖只能从上往下。**

```
foundation  ← agent  ← coding  ← (community 作为可选适配器接到 foundation)
                                ↑
                         trendpower-tui 把它们组装起来
```

- `foundation` 不依赖任何其他层，是地基。
- `agent` 只依赖 `foundation`，且**保持通用**（不含任何编码相关逻辑）。
- `coding` 依赖 `foundation` + `agent`，把通用循环特化成「编码 agent」。
- `community` 是可选适配器，把外部 SDK（openai/anthropic/mcp）实现成 `foundation` 定义的接口。**不允许**让 `foundation`/`agent` 反过来依赖 community。
- `trendpower-tui` 在最外层做组装与人机交互。

> 设计来历：这套代码是一个 TypeScript 项目的忠实 Python 移植，所以你会在注释里频繁看到「mirrors `src/...ts`」。API 风格是 **async-first**，大量用 `AsyncGenerator`（对应 TS 的 `async function*`）。

---

## 二、技术栈与约定速记

- **语言/运行时**：Python ≥ 3.10，构建后端 Hatchling。
- **核心依赖**（trendpower-py）：`openai`、`anthropic`、`pydantic`、`python-frontmatter`、`aiofiles`、`mcp`、`jsonschema`。
- **TUI 依赖**（trendpower-tui）：`textual`、`rich`、`click`、`pydantic`、`pyyaml`。
- **测试**：`pytest` + `pytest-asyncio`（`asyncio_mode = "auto"`，配置在 `trendpower-py/pyproject.toml`）。
- **约定**：
  - 工具参数 schema 用 **pydantic**。
  - 文件操作用 **pathlib + aiofiles**；子进程用 **asyncio.create_subprocess_exec**。
  - 取消用自定义 **`AbortSignal`**（不是 `asyncio.CancelledError`）。
  - 一条 assistant 消息里若含工具调用，所有工具**并行**执行，结果作为 `tool_result` 消息追加后再继续。
  - 注释保持精简、聚焦意图；不做顺手的无关重构。

---

## 三、一次对话的完整生命周期（最关键的一节）

下面是用户在 TUI 里敲一句话、回车之后发生的**端到端流程**。看懂这个，整个框架就通了。

```
用户输入 "帮我重构 foo.py"  （在 InputBox 里回车）
   │
   ▼
[trendpower_tui] app.on_command_submitted()         # app.py
   │  识别是不是 /slash 命令；不是 → 当作给 agent 的提问
   ▼
app.submit_user_text() → AgentRunner.submit()   # tui/agent_runner.py
   │  把 user 消息先回显到 UI；标记 streaming=True
   ▼
agent.stream(user_message)  ← 进入核心库       # agent/agent.py
   │
   │  ① _before_agent_run()  跑所有中间件的 beforeAgentRun
   │      └─ skills 中间件扫描 skills 目录，把技能列表放进 context
   │
   │  ② 进入 for step in 1..maxSteps 循环：
   │     │
   │     │  _before_agent_step()
   │     │
   │     │  ③ _think()：
   │     │     - _before_model() 跑中间件（skills 注入 <skill_system>；
   │     │       todo 中间件可能注入提醒）
   │     │     - model.stream(context)  调用模型          # foundation/models.py
   │     │         └─ provider.stream() 真正打 API        # community/openai|anthropic
   │     │             └─ StreamAccumulator 把流式分片拼成
   │     │                逐步完整的 AssistantMessage 快照  # */stream_utils.py
   │     │     - 每个带 streaming=True 的快照 → yield 一个 progress 事件
   │     │     - 流结束 → 拿到最终 AssistantMessage，append 进 transcript
   │     │
   │     │  ④ _after_model() 跑中间件
   │     │     yield {"type":"message", ...}  → UI 显示这条 assistant 消息
   │     │
   │     │  ⑤ 从 assistant 消息里抽 tool_use 块
   │     │     - 没有工具调用 → _after_agent_run()，return，本轮对话结束 ✅
   │     │     - 有工具调用 → 进入 _act()
   │     │
   │     │  ⑥ _act()：把所有 tool_use 并行跑
   │     │     对每个工具：
   │     │       - 按 name 在 self.tools 里找到对应 Tool
   │     │       - _before_tool_use() 跑中间件
   │     │           └─ 审批中间件：危险工具(bash/write...)→ 弹审批条，
   │     │              用户 deny 则跳过执行、把拒绝理由当结果返回
   │     │       - tool.invoke(input, signal) 真正执行
   │     │       - _after_tool_use() 跑中间件（todo 中间件刷新计步）
   │     │       - 结果经 format_tool_result_for_message() 规范化+截断
   │     │       - 包成 tool 消息 append 进 transcript
   │     │       - yield {"type":"message",...} → UI 显示工具结果
   │     │
   │     │  ⑦ _after_agent_step()，回到 ② 继续下一轮思考
   │     ▼
   └────── 循环直到模型不再调用工具（或到 maxSteps 报错）
   │
   ▼
[trendpower_tui] AgentRunner 把 message/progress 事件
   以 50ms 为窗口批量刷到 Textual            # tui/agent_runner.py
   │  streaming=False；清空 requested skill
   ▼
MessageHistory / TodoPanel / StatusFooter 重绘  # tui/widgets/*
```

几个要点：

- **transcript（对话记录）是唯一真相源**。它是一个 `Message` 列表，贯穿始终。模型每次调用都把「system prompt + 整个 transcript」发出去——agent 自身**无状态机**，状态就是这个列表。
- **中间件是横切关注点的挂载点**。skills、todos、权限审批全部是中间件，agent 核心循环对它们一无所知。
- **工具结果永远以字符串进 transcript**，但工具 `invoke` 可以返回结构化 dict，由 `tool_result.runtime` 统一规范化。

---

## 四、第 1 层 `foundation` — 核心原语

路径：`trendpower-py/trendpower/foundation/`。这是所有东西的地基，类型稳定、可复用。

### `messages.py` — 对话记录的类型
定义了贯穿全系统的**唯一 transcript 类型**。全部用 `TypedDict`，所以运行时就是普通 dict（和原 TS interface 一一对应）。
- 4 种角色：`system` / `user` / `assistant` / `tool`。
- 内容块（content block）：`TextContent`（文本）、`ImageURLContent`（图片）、`ThinkingContent`（思维链，含 Anthropic 专用 `_anthropicSignature`）、`ToolUseContent`（模型发起的工具调用：id+name+input）、`ToolResultContent`（工具返回：tool_use_id+content）。
- `TokenUsage`：promptTokens / completionTokens / totalTokens。
- 每种角色的消息允许哪些内容块由 `*MessageContent` 联合类型约束。

### `models.py` — 模型与提供方契约
- `ModelProvider`（Protocol）：任何提供方必须实现 `invoke()`（一次性）和 `stream()`（流式）。
- `Model`（dataclass）：`name + provider + options`。它的 `invoke/stream` 做一件关键的事——`_build_provider_params()`：把 `prompt` 包成一条 `system` 消息塞到 messages 最前面，再把 `options` 透传给 provider。**这就是 system prompt 进入请求的地方。**
- `ModelContext`：调用模型时传入的东西（prompt / messages / tools / signal）。

### `tools.py` — 工具定义
- `FunctionTool`（dataclass）：一个工具 = `name + description + parameters(pydantic 类) + invoke(协程) + raw_input_schema(可选)`。
- `raw_input_schema`：逃生舱口。正常工具的 JSON Schema 由 pydantic 的 `model_json_schema()` 生成；但 MCP 工具直接拿到 server 的原始 schema，用这个字段原样透传，避免 pydantic round-trip 破坏复杂 schema。
- `define_tool(...)`：**定义工具的标准工厂**。它把你写的「接收已校验 pydantic 实例」的 `invoke`，包装成「接收原始 dict、内部先 `model_validate` 再调用」的形式。所有编码工具都用它。
- `StructuredToolSuccess` / `StructuredToolError`：工具返回结构化结果的约定形状（`ok/summary/data` 或 `ok/summary/error/code/details`）。

### `abort_signal.py` — 协作式取消
仿 Web 平台的 `AbortController`/`AbortSignal`。
- `AbortSignal`：`.aborted`、`.reason`、`throw_if_aborted()`、`add_listener(cb)`（注册取消回调，返回移除函数）、`wait()`（异步等待取消，用于和工具任务赛跑）。
- `AbortController`：持有一个 signal，`.abort(reason)` 触发。
- 用途：用户按 Esc/Ctrl+C → agent 调 `abort()` → 正在跑的 bash 子进程被 kill、循环抛 `AbortError`。

### `__init__.py`
统一 re-export 上述所有类型，外部 `from trendpower.foundation import ...` 即可。

---

## 五、第 2 层 `agent` — 通用 ReAct 循环

路径：`trendpower-py/trendpower/agent/`。这一层**只依赖 foundation**，且刻意保持通用（不含任何编码相关知识）。

### `agent.py` — 循环本体（最核心的文件）
`Agent` 类持有一个可变的 `AgentContext`（含 prompt / messages / tools / skills / requestedSkillName）。

- **`stream(user_message)`**：异步生成器，是整个对话的引擎。流程见上文「三」的 ②～⑦。要点：
  - `for step in 1..maxSteps`，超过 `maxSteps`（默认 100）抛错防死循环。
  - 每步先 `_think()` 拿模型回复，再 `_act()` 跑工具，全程在各阶段调用中间件钩子。
  - 没有工具调用就结束本轮。
- **`_think()`**：调 `model.stream()`，把流式快照中带 `streaming=True` 的转成 `progress` 事件 yield 出去，最终把完整 assistant 消息 append 进 transcript。用一个 `{"type":"_think_done"}` 哨兵把最终消息传回主循环（模拟 TS 的 `yield* + return value`）。
- **`_act(tool_uses)`**：为每个工具调用建一个 `asyncio.Task` **并行**执行，同时建一个 `signal.wait()` 任务和它们赛跑——一旦收到取消信号立即抛 `AbortError`。每个工具完成就把结果包成 `tool` 消息 append 并 yield。单个工具内部异常被捕获成 `"Error: ..."` 字符串结果（不会让整轮崩掉）。
- **中间件分发方法**：`_before_model/_after_model/_before_agent_run/_after_agent_run/_before_agent_step/_after_agent_step/_before_tool_use/_after_tool_use`。每个都按中间件数组顺序**依次** await 对应钩子；钩子返回的 dict 会被 merge 进共享 context。`_before_tool_use` 特殊：若某中间件返回 `{"__skip": True, "result": ...}`，则跳过该工具执行、直接用给定 result。
- 其他：`abort()`、`clear_messages()`、`set_requested_skill_name()`、`messages/prompt/tools` 属性。

### `agent_event.py` — 事件类型
循环 yield 出去的事件：`AgentMessageEvent`（type=message，携带一条 assistant 或 tool 消息）、`AgentProgressEvent`（type=progress，subtype=thinking 或 tool）。UI 据此更新。

### `agent_middleware.py` — 中间件契约
定义 `AgentMiddleware`（Protocol）的 8 个**可选**钩子，以及每个钩子的参数 TypedDict。约定：钩子按数组顺序顺序执行；返回 truthy dict 则 merge 进 context，返回 None 表示不改动。`_SkipResult` 是 `beforeToolUse` 用来跳过工具的哨兵形状。**所有中间件（skills/todos/审批）都实现这个鸭子类型接口**（实际用 `SimpleNamespace` 装几个函数即可，不必继承）。

### 工具结果处理流水线（3 个文件）
模型看到的工具结果质量直接影响后续推理，所以这里有专门处理：

- **`tool_result/policy.py`**：按工具名返回格式化策略。例如 `list_files/glob_search/grep_search` 等只保留 summary、丢弃 data、限长 1000 字符；`read_file` 允许 12000 字符；写类工具 4000；默认 4000。
- **`tool_result/runtime.py`**：核心函数 `format_tool_result_for_message(tool_name, result)`。把任意工具返回值**规范化**成统一形状（区分结构化成功/结构化错误/`"Error:"` 字符串/裸值），再按 policy 截断、序列化成进 transcript 的字符串。`infer_tool_error_kind()` 从 error code 推断错误类别（invalid_input / not_found / environment_missing 等）。`read_file` 结果是个特例，直接原样返回纯文本。
- **`tool_result/summary.py`**：`summarize_tool_result_text(content)`——把已序列化的工具结果字符串反解析成一行 UI 摘要（给前端展示用）。

### `skills/` — 技能系统
技能 = 一个含 `SKILL.md`（带 YAML frontmatter）的文件夹，用来给特定任务注入「最佳实践工作流」。
- **`types.py`**：`SkillFrontmatter`（name/description/path）。
- **`skill_reader.py`**：`read_skill_frontmatter(path)` 读一个 SKILL.md 并用 `frontmatter` 解析出元数据。
- **`list_skills.py`**：扫描多个技能目录，去重、按名排序，返回技能列表（被 TUI 的 `/help` 和命令注册表用）。
- **`skills_middleware.py`**：`create_skills_middleware(dirs)` 返回一个中间件——
  - `beforeAgentRun`：扫描所有技能目录，把技能列表写进 context。
  - `beforeModel`：把技能以 `<skill name=... path=...>desc</skill>` 形式拼进一个 `<skill_system>` 块，**追加到 system prompt**，告诉模型「匹配到任务就先 read_file 读对应技能文件」（渐进式加载）。若用户通过 `/skill名` 显式选了技能，还会额外注入 `<explicit_skill_invocation>` 强制先读那个技能。

### `todos/` — 待办系统
帮助 agent 跟踪多步任务的进度。
- **`types.py`**：`TodoItem`（id/content/status）、`TodoStatus`（pending/in_progress/completed/cancelled）。
- **`todos.py`**：`create_todo_system()` 返回 `(tool, middleware)`：
  - `tool` = `todo_write`，模型用它创建/更新待办列表（支持 merge 增量更新 或 全量替换）。列表存在闭包里的内存 `store`。
  - `middleware`：`beforeModel` 里若距上次写待办超过 10 步，就注入一段 `<todo_reminder>` 提醒模型更新；`afterToolUse` 里若刚调用过 todo_write 就重置计步。

### `compaction/` — 上下文压缩
长会话的 transcript 无上限增长,每次请求重发全量,迟早撑爆模型上下文窗口。这个子系统在快撑满时**摘要化对话中段、就地替换**,堵住这个正确性漏洞。
- **`compaction.py`**:`create_compaction_middleware(...)` 返回一个 `beforeModel` 中间件——
  - `estimate_tokens()`:优先用最近一条 assistant 消息的 `usage.promptTokens`(真实值),否则按字符数 /4 估算,取两者较大值。
  - 超过 `trigger_tokens`(默认 100k)就触发:`plan_compaction()` 把消息切成 `head(保留开头, 默认首条=任务/AGENTS.md) + middle(待摘要) + tail(保留最近 N 条)`。
  - **关键正确性不变式——工具配对**:绝不把 assistant 的 `tool_use` 和它的 `tool_result` 拆散(provider 会拒绝孤儿)。tail 边界会向前跳过开头的 `tool` 消息,head 边界会回退以免末尾留下 tool_use。
  - 摘要器可插拔:给了 model 就用 LLM 摘要(`make_llm_summarizer`,把中段扁平成纯文本喂给模型,规避配对问题),否则用确定性结构化摘要(`make_digest_summarizer`)。
  - 摘要失败不致命(只 warn,保持原样);成功则用一条 user 消息替换中段,并通过 `on_compaction` 回调上报 `CompactionEvent`(TUI 据此打一行提示)。
- 在 `lead_agent.py` 里默认开启(`enable_compaction=True`),用 agent 自己的 model 做摘要。

### `__init__.py`
re-export `Agent`、事件、中间件参数类型、`create_todo_system`、`create_compaction_middleware` 等。

---

## 六、第 3 层 `coding` — 编码专用 agent

路径：`trendpower-py/trendpower/coding/`。把通用循环特化成一个能读写代码的 agent。

### `agents/lead_agent.py` — 主编码 agent 的装配
`create_coding_agent(...)` 是**把一切组装起来的工厂函数**：
1. 默认 cwd=当前目录，skills_dirs 默认 `<cwd>/.agents/skills`。
2. 若 cwd 下有 `AGENTS.md`，自动读进来作为第一条 user 消息（项目说明自动入场）。
3. 创建 todo 系统（tool + middleware）。
4. 组装中间件链：`[skills 中间件, todo 中间件, (可选)审批中间件]`。
5. 拼出**编码 system prompt**（`<agent>` 角色定义 + `<working_directory>` + `<tool_usage>` 使用规范 + `<notes>`）。
6. 组装工具集：bash、file_info、list_files、glob_search、grep_search、mkdir、move_path、read_file、write_file、str_replace、apply_patch、todo_write，加上（可选）ask_user_question 和 `extra_tools`（**MCP 工具就是从这里注入的**）。
7. 返回配置好的 `Agent` 实例。

### `tools/` — 编码工具集
每个工具都遵循同一个模式：定义一个 pydantic 参数类 → 写 `async def _invoke(params)` → 用 `define_tool(...)` 包装导出。返回值要么是纯文本，要么是 `ok_tool_result/error_tool_result` 结构化 dict。

- **`bash.py`**：执行 shell 命令。跨平台解析 shell（`TRENDPOWER_BASH_SHELL` 覆盖 → zsh/bash/sh → Windows 回退 cmd.exe）。通过 `signal.add_listener` 在取消时 kill 子进程。非零退出码返回 `Error:` 文本。
- **`read_file.py`**：按绝对路径读文件，支持行范围切片和字符上限；整文件未截断时返回原文，否则返回带行号的片段。
- **`write_file.py`**：写文件（覆盖）。
- **`str_replace.py`**：精确字符串替换编辑。
- **`apply_patch.py`**：应用 patch 式的定向编辑（最复杂的编辑工具，prompt 里推荐优先用它）。
- **`list_files.py` / `glob_search.py` / `grep_search.py` / `file_info.py`**：目录列举 / 通配查找 / 内容搜索（grep 需要环境里有 ripgrep，缺失时返回 `RG_NOT_FOUND`）/ 文件信息。
- **`mkdir.py` / `move_path.py`**：建目录 / 移动路径。
- **`tool_utils.py`**：共享工具函数——`ensure_absolute_path`（强制绝对路径，跨平台用 `os.path.isabs`）、`ensure_directory_path`、`is_within_directory`（防越界）、`truncate_text`。
- **`tool_result.py`**：`ok_tool_result(summary, data)` / `error_tool_result(error, code, details)` 构造结构化结果。
- **`ask_user_question.py`**：一个特殊工具——让模型向用户提 1~4 个并行的选择题。pydantic schema 严格约束（每题 2~4 个选项、header≤12 字符等）。`create_ask_user_question_tool(callback)` 接收一个 host 提供的阻塞回调（TUI 用它弹出选择 UI 并等用户提交），返回结果前后校验 answers 与 questions 匹配。
- **`ask_user_question_manager.py`**：`AskUserQuestionManager`——一个队列+订阅管理器，把工具发起的提问请求路由到 UI。`ask_user_question()` 创建一个 future 入队并等待；UI 订阅后逐个处理，用户提交时 `respond_with_answers()` 兑现 future。导出全局单例 `global_ask_user_question_manager`。

### `permissions/` — 工具审批
危险工具执行前先征求用户同意。
- **`approval_types.py`**：`ApprovalDecision` = deny / allow_once / allow_always_project。
- **`requires_approval.py`**：`CODING_TOOLS_REQUIRING_APPROVAL` = [bash, write_file, str_replace, apply_patch, mkdir, move_path]。
- **`approval_persistence.py`**：`ApprovalPersistence`（Protocol）——定义 `load_allow_list(cwd)` 和 `persist_allowed_tool(cwd, name)` 两个方法名，供「记住本项目的放行」用。
- **`coding_approval_middleware.py`**：`create_coding_approval_middleware(...)` 返回一个 `beforeToolUse` 中间件——若工具在需审批名单且不在已放行列表里，就调 `ask_user(tool_use)` 阻塞等用户决定。deny → 返回 `__skip` 跳过执行；allow_always_project → 持久化到项目设置。
- **`approval_manager.py`**：`ApprovalManager`——和 AskUserQuestionManager 同构的队列+订阅管理器，把审批请求路由到 UI。导出全局单例 `global_approval_manager`。

> 注意：核心库只定义「审批要问谁」（`ask_user` 回调）和「放行清单从哪读写」（`ApprovalPersistence` 协议），**具体怎么弹窗、怎么存文件由 TUI 实现**。这是分层解耦的典范。

---

## 七、第 4 层 `community` — 第三方集成

路径：`trendpower-py/trendpower/community/`。可选适配器，把外部 SDK 实现成 foundation 的接口。

### `openai/` — OpenAI（及任何 OpenAI 兼容端点）
- **`model_provider.py`**：`OpenAIModelProvider` 实现 `ModelProvider`。`invoke` 一次性调用、`stream` 流式调用 `chat.completions.create`。`_base_params` 默认 `temperature=0`，把 `Model.options` merge 进请求（允许传 provider 特有参数）。流式时开 `stream_options.include_usage`。
- **`utils.py`**：消息/工具的双向转换。`convert_to_openai_messages`（trendpower 消息 → OpenAI 格式，含 thinking→reasoning_content、tool_use→tool_calls 的映射）、`parse_assistant_message`（响应 → trendpower AssistantMessage）、`convert_to_openai_tools`（工具 → OpenAI function 定义，**优先用 `raw_input_schema`**）。
- **`stream_utils.py`**：`StreamAccumulator` 把 OpenAI 的流式 chunk 累积成逐步完整的 AssistantMessage 快照。

### `anthropic/` — Anthropic（Claude）
- **`model_provider.py`**：`AnthropicModelProvider`。结构同 OpenAI，但有 Anthropic 特性：把 system 从 messages 里抽出来单独传；开启 thinking 时自动按 `max_tokens*0.8` 补 `budget_tokens`；默认 `max_tokens=8192`。
- **`utils.py`**：`convert_to_anthropic_messages/tools`、`extract_system_prompt`、`parse_assistant_message`（工具定义优先用 `raw_input_schema`）。
- **`stream_utils.py`**：`StreamAccumulator` 处理 Anthropic 的事件协议（message_start / content_block_start / content_block_delta / message_delta），把 text/thinking/tool_use 三类块逐步拼好，并跟踪 input/output token。

### `mcp/` — Model Context Protocol 集成
把外部 MCP server 暴露成 trendpower 工具。**详见专门文档 [`docs/mcp.md`](mcp.md)**，这里只列文件职责：
- **`config.py`**：MCP server 配置的 pydantic 模型（stdio/sse/streamable_http 三种传输）+ `${ENV_VAR}` 展开 + 从 dict/file 加载。
- **`transports.py`**：`open_transport(cfg)`——把三种传输统一成 `(read, write)` 流，喂给官方 `mcp.ClientSession`。
- **`session.py`**：`MCPSession`——包一层 `ClientSession`，管 open/list_tools/call_tool/aclose 生命周期。
- **`toolset.py`**：`MCPToolset`——一个 server 一个专用 asyncio.Task（解决 anyio task scope 必须同 task 进出的限制），使 connect/aclose 可从任意 task 安全调用。
- **`tool_adapter.py`**：把 MCP 工具适配成 trendpower `FunctionTool`，工具名加 `servername__` 前缀防撞名，`_sanitize_tool_name` 保证符合严格 provider 的命名约束。
- **`manager.py`**：`MCPManager`——并行连接 N 个 server，故障隔离，聚合工具，提供 status/reload。
- **`tests/`**：config 解析、tool 适配、真实子进程 e2e 测试（含一个 `_fake_stdio_server.py`）。

---

## 八、`trendpower-tui` — 终端 UI 层

路径：`trendpower-tui/trendpower_tui/`。基于 **Textual**（Python 版的 Ink/React）。它的职责是**组装核心库 + 处理人机交互**，本身不含 agent 逻辑。

### 入口与顶层
- **`__main__.py`**：入口。有参数 → 走 click CLI 子命令；无参数 → 启动 Textual TUI。安装为命令行 `trendpower`。
- **`app.py`**：`trendpowerApp`（Textual App），**TUI 的中枢**。
  - `compose()` 声明所有 widget（消息历史、待办面板、流式指示器、命令列表、状态栏、输入框、审批条、提问条）。
  - `on_mount()`：启动时设置 TRENDPOWER_HOME、发现 skills 目录、加载命令、**启动 MCP**、创建 AgentRunner、订阅审批/提问管理器；无模型则拉起首次运行向导。
  - `_try_create_runner()`：读配置 → 据 provider 建 OpenAI/Anthropic provider → 建 Model（Anthropic 默认开 thinking）→ 调 `create_coding_agent(... extra_tools=mcp_tools)` → 包成 `AgentRunner`。
  - `on_command_submitted()`：分流 /clear、/exit、/help、/model、/mcp 等内建命令，否则提交给 agent。
  - 审批/提问的 UI 桥接：`_show_approval_screen`/`on_approval_decided`、`_show_ask_user_question_screen`/`on_answers_submitted` 把管理器的请求显示成底部 bar，并把用户决定回传给管理器（兑现 future）。
  - `/mcp` 命令实现（help/list/reload）、模型管理（增删改默认）、abort/quit。
- **`version.py`**：版本号。

### TUI 编排（`tui/`）
- **`agent_runner.py`**：`AgentRunner` 把 `agent.stream()` 的异步事件桥接成 Textual 消息。**以 50ms 为窗口批量刷新**（避免每个流式快照都重绘）；运行结束清 streaming 标志；把模型/工具错误转成 assistant 消息而非崩溃；吞掉用户主动取消的 `AbortError`。
- **`command_registry.py`**：slash 命令注册表。内建命令（clear/exit/help/mcp/model/quit）+ 把技能也注册成命令；提供命令过滤、内建命令解析、`/help` 渲染、以及把 `/技能名` 解析成 requested_skill_name。
- **`skill_paths.py`**：`discover_skills_dirs(cwd)`——从 cwd、TRENDPOWER_HOME、`~/.{agents,trendpower}/skills`、cwd 的祖先目录、以及包安装位置等多处发现技能目录（让 pip 安装的用户在任意目录都有合理默认）。
- **`todo_view.py`**：从消息历史**重放** todo_write 调用，重建每个时间点的待办快照（UI 展示用，与核心库的内存 store 独立）。
- **`token_usage.py`**：从消息里累计 token 用量（最近一次 input + 全会话 total）。

### Widgets（`tui/widgets/`）—— 界面组件
- **`brand_header.py`**：顶部品牌头，显示模型名/就绪状态/技能数。
- **`message_history.py`**：可滚动的对话记录主区，渲染各类消息和工具结果摘要。
- **`todo_panel.py`**：待办列表面板。
- **`streaming_indicator.py`**：「Thinking… / Running xxx…」状态指示。
- **`command_list.py`**：输入 `/` 时的命令自动补全下拉。
- **`status_footer.py`**：底部状态栏（模型 + token 统计）。
- **`input_box.py`**：文本输入框，发出 `CommandSubmitted` / `CommandInputChanged` 消息。
- **`approval_bar.py`**：工具审批条（allow once / allow always / deny），发出 `ApprovalDecided`。
- **`ask_user_question_bar.py`**：多选题交互条，发出 `AnswersSubmitted`。
- **`first_run_wizard.py`**：首次运行配置模型的向导屏。
- **`model_manager.py`**：`/model` 的模型管理屏（列出/切换默认/增/删）。

### 配置与设置
两套独立的持久化，别混淆：

- **`config/`** —— **模型配置**，存 `~/.trendpower/config.yaml`（YAML）。
  - `schema.py`：`ModelEntry`（name/baseURL/APIKey/provider）、`trendpowerConfig`（models + defaultModel，并校验默认模型存在）。
  - `store.py`：TRENDPOWER_HOME 解析、load/save（save 用临时文件原子替换）、`is_trendpower_setup_complete()` 等。
- **`settings/`** —— **行为设置**（主要是工具放行清单），存 `settings.json`，分层叠加。
  - `settings.py`：`Settings`/`PermissionsSettings` schema + `append_tool_to_allow_list` 纯函数。
  - `settings_loader.py`：`SettingsLoader` 按 用户级 → 项目级 → 项目本地 三层加载并合并（allow 清单取并集）；`load_allow_list(cwd)`。
  - `settings_writer.py`：`SettingsWriter` 把放行的工具原子写入项目本地 `settings.local.json`。
  - `approval_persistence.py`：`SettingsApprovalPersistence`——把 loader/writer 适配成核心库期望的 `load_allow_list`/`persist_allowed_tool` 接口名。**这就是 `coding` 层审批协议在 TUI 侧的落地实现。**
- **`model_providers.py`**：内置 provider 预设列表（Anthropic/OpenAI/火山/通义/Minimax/GLM/Kimi/DeepSeek/Other），给配置流程提供 baseURL 和类型默认值。

### CLI 与 MCP 生命周期
- **`commands/__init__.py`**：click 命令树。`trendpower config model {list,add,remove,set-default}` 管理模型；`trendpower diagnose` 分三档（裸调用 / 加流式flags / 加工具）逐层定位某个模型端点在哪一步出问题——排查「模型连不上/不支持工具调用」的利器。
- **`mcp/config_loader.py`**：定位并解析 `~/.trendpower/mcp_servers.json`（坏文件不崩，只 warn）。
- **`mcp/lifecycle.py`**：`MCPLifecycle`——给 App 提供 `startup/shutdown/reload/status` 四个钩子，内部持有一个 `MCPManager`。

---

## 九、关键设计模式总结

1. **分层 + 单向依赖**：foundation←agent←coding，community 作可选适配器，TUI 在最外层组装。改一层不波及下层。
2. **transcript 即状态**：agent 无独立状态机，整个对话状态就是 `Message[]` 列表，每次请求重发全量。
3. **中间件做横切**：skills/todos/审批都是中间件，核心循环对它们零感知。新增横切能力 = 加一个实现若干钩子的对象。
4. **闭包路由工具**：每个工具的 `invoke` 是个闭包，自带它要调用的资源（如 MCP session），agent 只按名字找工具、调 invoke，不关心背后是本地函数还是远程 server。
5. **Protocol 解耦实现**：`ModelProvider`、`ApprovalPersistence` 等用 Protocol 定义契约，核心库只依赖契约，具体实现（openai SDK、文件读写）放在 community/TUI。
6. **队列+订阅桥接 UI**：需要问用户的场景（审批、选择题）用「管理器持有 future 队列 + UI 订阅」模式，把同步的 UI 交互接进异步的 agent 循环。
7. **结构化工具结果 + 策略化格式化**：工具返回结构化 dict，经 policy 截断/规范化后再进 transcript，控制喂给模型的信息量。

---

## 十、扩展指南（我以后想加东西怎么办）

- **加一个本地工具**：在 `coding/tools/` 下新建文件，定义 pydantic 参数类 + `_invoke` + `define_tool` 导出，再在 `lead_agent.py` 的 tools 列表里加上它。若是危险操作，把工具名加进 `requires_approval.py`。
- **接一个新模型提供方**：在 `community/` 下新建目录，实现 `ModelProvider`（invoke + stream + 一个 StreamAccumulator + 消息/工具转换 utils），再在 TUI 的 `_try_create_runner` 和 `model_providers.py` 里接上。
- **加一个横切行为（如日志、限流、自动重试）**：写一个带相应钩子（beforeModel/afterToolUse…）的对象（`SimpleNamespace` 即可），加进 `create_coding_agent` 的 middlewares 列表。
- **加一个技能**：在某个被发现的 skills 目录下建文件夹 + `SKILL.md`（带 name/description frontmatter）。会自动出现在 `/help` 和 system prompt 里。
- **挂一个 MCP server**：编辑 `~/.trendpower/mcp_servers.json`，详见 [`docs/mcp.md`](mcp.md) 的实操手册。
- **加一个 TUI widget / slash 命令**：在 `tui/widgets/` 加组件并在 `app.compose` 里 yield；在 `command_registry.py` 的 `BUILTIN_COMMANDS` 加命令并在 `app.on_command_submitted` 里分流处理。

---

## 十一、文件索引表（速查字典）

### trendpower-py / 核心库

| 文件 | 一句话职责 |
|---|---|
| `foundation/messages.py` | 对话记录（transcript）的全部类型定义 |
| `foundation/models.py` | `Model` / `ModelProvider` 契约；把 prompt 拼成 system 消息 |
| `foundation/tools.py` | `FunctionTool` + `define_tool` 工厂 + 结构化结果类型 |
| `foundation/abort_signal.py` | 协作式取消 `AbortSignal`/`AbortController` |
| `agent/agent.py` | **ReAct 循环本体**（think/act/observe + 中间件分发） |
| `agent/agent_event.py` | 循环 yield 的 message/progress 事件类型 |
| `agent/agent_middleware.py` | 中间件 8 个钩子的契约 |
| `agent/tool_result/policy.py` | 按工具名决定结果格式化策略 |
| `agent/tool_result/runtime.py` | 把工具返回值规范化+截断成进 transcript 的字符串 |
| `agent/tool_result/summary.py` | 把结果字符串反解析成一行 UI 摘要 |
| `agent/skills/*` | 技能加载与 `<skill_system>` 注入（middleware + reader + list + types） |
| `agent/todos/*` | `todo_write` 工具 + 提醒中间件 + 类型 |
| `agent/compaction/*` | 上下文压缩中间件（token 估算 + 工具配对安全切分 + LLM/启发式摘要） |
| `coding/agents/lead_agent.py` | **装配编码 agent**（prompt + 工具 + 中间件） |
| `coding/tools/*` | bash/读写/补丁/搜索/提问等编码工具 + 工具辅助函数 |
| `coding/permissions/*` | 危险工具审批（中间件 + 管理器 + 持久化协议 + 名单） |
| `community/openai/*` | OpenAI provider + 消息/工具转换 + 流式累积 |
| `community/anthropic/*` | Anthropic provider（system 抽离、thinking 预算）+ 转换 + 流式 |
| `community/mcp/*` | MCP 集成（配置/传输/会话/工具集/适配/管理）→ 见 docs/mcp.md |

### trendpower-tui / 终端 UI

| 文件 | 一句话职责 |
|---|---|
| `__main__.py` | 入口：有参→CLI，无参→TUI |
| `app.py` | **Textual App 中枢**：组装、生命周期、命令分流、UI 桥接 |
| `tui/agent_runner.py` | 把 agent 异步事件批量桥接成 Textual 消息 |
| `tui/command_registry.py` | slash 命令注册/解析/帮助 |
| `tui/skill_paths.py` | 多路径发现技能目录 |
| `tui/todo_view.py` | 从消息重放重建待办快照（UI 用） |
| `tui/token_usage.py` | 累计 token 用量 |
| `tui/widgets/*` | 各界面组件（历史/待办/输入/审批条/提问条/向导/模型管理…） |
| `config/*` | 模型配置（`~/.trendpower/config.yaml`）schema 与读写 |
| `settings/*` | 行为设置（settings.json）分层加载/写入/审批落地 |
| `model_providers.py` | 内置 provider 预设（baseURL + 类型） |
| `commands/__init__.py` | click CLI：模型管理 + `diagnose` 端点诊断 |
| `mcp/config_loader.py` | 定位/解析 mcp_servers.json |
| `mcp/lifecycle.py` | MCP 启停/重载/状态生命周期 |

---

如需更深入某一块，配套文档：
- [`docs/mcp.md`](mcp.md) — MCP 集成原理 + 安装新 server 实操手册
- [`docs/backend-design.md`](backend-design.md) — 后端设计
- 各包根目录的 `README.md`
