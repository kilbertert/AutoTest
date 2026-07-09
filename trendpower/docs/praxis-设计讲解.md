# 从零理解一个 Coding Agent —— trendpower 设计讲解

如开头的演示所示，本文中的 Coding Agent 取名叫——🦌 **trendpower**（在希腊语里意为「付诸实践的行动」，正好对应它「想一步、做一步」的工作方式）。trendpower 具备：

- 多轮会话
- 规划与 Todo 列表
- 代码定位（仓库结构理解 + 内容检索）
- 代码生成与编辑
- 技能（Skill）与文档/最佳实践的渐进加载
- 子 Agent 任务分派
- MCP 集成

最后，它还附带了一个完全由 Textual + Rich 拼出来的终端控制台界面（甚至还有一个把「每轮发给模型的请求」实时投到浏览器里的可视化版本）。

对于不是 Python 技术栈的同学来说，也可以通过阅读本文，把这套工程的设计思路平移到 Node.js、Golang 等其它技术栈——它的核心其实和语言无关。

## Coding Agent 祖师爷——Claude Code

和业界许多 Coding Agent 前辈一样，trendpower 也受到 Claude Code 逆向工程的启发。考虑到国内外的编程模型大多针对 Claude Code 的工具形态做过许多「特殊训练」，因此本文的工具设计也尽量贴近它的抽象。

Coding Agent 的本质是一个 **ReAct 风格的 Agent**：它拥有自己的规划、感知和执行能力，先通过一组**只读的文件系统工具**了解仓库的结构和技术栈（Repo Structure Understanding），从而定位到与用户需求相关的文件和行号（Code Locating），再通过**文本编辑器工具**把代码写回仓库（Code Generating），全程用 **To-do 列表**对任务进行分解、规划与进度监督。一些现代化的 Coding Agent 还支持 MCP 扩展、`/` 命令扩展，以及自定义 Instructions（比如我们熟悉的 `.cursorrules`、`AGENTS.md`）来进一步扩展能力——这些 trendpower 也都有。

> **ReAct** 是 Reasoning and Acting 的缩写，是一种让 LLM「边思考边行动」的提示范式，核心思想是让模型交替进行 Reasoning（推理）和 Acting（行动）。

基本流程：

1. **Thought（思考）**：模型分析当前状态，决定下一步做什么
2. **Action（行动）**：执行具体操作（比如调用搜索 API、读文件）
3. **Observation（观察）**：获取行动结果
4. 重复 1–3，直到得出最终答案

举个例子：

```text
User: 北京今天天气怎么样？

Thought: 我需要查询北京的实时天气信息
Action: search("北京天气 今天")
Observation: 北京今天晴，温度 15–25°C

Thought: 已经获取到天气信息，可以回答了
Answer: 北京今天晴天，温度在 15–25°C
```

**为什么有用？**

- 传统 LLM 是「一次性输出」，ReAct 让模型能多步骤地解决复杂问题：它可以及时通过调用工具**感知**（retain）外部环境的变化，再紧接着通过工具**操纵**（mutate）外部环境，如此循环往复，直到问题被解决或因异常而终止。
- 可解释性强：每一步推理过程都可见。
- 适合需要外部工具调用的场景（搜索、读写文件、跑命令、查数据库等）。

在 trendpower 里，这个循环就是 `agent/agent.py` 里的 `Agent.stream`：一个 `for step in 1..maxSteps` 的异步生成器，每一步先 `_think`（调模型）、再 `_act`（并行跑工具），直到**模型不再请求调用任何工具**——这就是「任务完成」的信号。

### Single 还是 Multi-Agent？

关于 Coding Agent 应该是一个 Single Agent 还是 Multi-Agent，业界一直没有统一答案。

笔者认为，目前相对比较理想的形态是 **Claude Code 的范式**：它从外观层看是一个 Single Agent，是一个标准的 ReAct loop；但当遇到复杂问题时，主 Agent 会调用一个 `task` 工具，该工具「裂变」出一个能力几乎和自己一模一样的 **Sub-agent**，分配一条受限的工具链，并被指派一个更明确的子任务。Sub-agent 可以用于未知的 Code RAG 探索、复杂逻辑的编写、文档编写等；它执行完后，**只把一句最终结论**并回主链路。Sub-agent 拥有独立的任务目标、规划与执行——这相当于分担了主 Agent 的任务和上下文，从而降低了对单个 Agent 能力上限的要求，提升了整体的能力天花板。

trendpower **采用了这一范式**，并把它收敛得很克制。子 Agent 由 `coding/tools/task.py` 的 `task` 工具发起，底层复用同一套 `Agent.stream` 循环（`agent/subagent/runner.py`），分两种：

| subagent_type | 工具集 | 审批 | 典型用途 |
|---|---|---|---|
| `explore` | 只读工具 | 免审批 | 跨多文件查资料、调研某功能怎么实现 |
| `general` | 完整工具 | 转发审批 | 子任务必须改文件 / 跑命令时才用 |

还有两条**写死的安全红线**，体现了「克制」二字：

- 子 Agent 的工具集里**永远不含 `task`**——杜绝无限套娃（`base_tools` 是在 append `task` 之前拍下的快照）。
- 也**不含 `ask_user_question`**——后台任务不该反过来弹窗打扰用户。

并发几乎是「白送」的：因为 `_act` 本就并行执行同一条助手消息里的所有工具，所以模型一次发 3 个 `task`，就是 3 个子 Agent 同时开工。

> **延伸阅读**：对 Claude Code 的子 Agent / Hand-off 机制感兴趣的同学，可以对照 Deep Research 里惯用的 Supervisor + Hand-off 设计模式来看——会发现 Coding Agent 这一套要简单许多。trendpower 的完整启动到回答的追踪见 [`docs/execution-flow.md`](execution-flow.md)。

---

## 设计

一个简单的 ReAct Agent，至少要包含**模型、System Prompt 和工具**三样东西，Coding Agent 也不例外。下面**从下往上**地拆解 trendpower 的设计。

### 鸟瞰：三个包 + 单向依赖

先看一眼整体。trendpower 仓库由三个 Python 包加一份共享 skills 目录组成，依赖关系**严格单向**——下层永不依赖上层：

```text
trendpower-web  ──依赖──▶  trendpower-tui  ──依赖──▶  trendpower (核心库 trendpower-py)
(浏览器可视化)          (终端界面)              (Agent 循环 / 工具 / 模型抽象，无上游依赖)
```

- **`trendpower`（核心库）**：Agent 循环、工具、模型抽象都在这里，它**不知道界面是否存在**，可以单独 import 使用。
- **`trendpower-tui`**：基于 Textual 的终端界面，只做「界面 + 事件桥接」，不含任何 Agent 逻辑。
- **`trendpower-web`**：复用整个 tui，额外把「每轮发给模型的请求」广播到浏览器做可视化。

单向依赖的回报是：核心库稳定、可独立测试、可被包装成任意形态的产品。这也呼应了下文「为何青睐 Console UI」那一节——界面只是最外面的一层壳。

核心库内部又分四层，依赖同样自上而下：`coding → agent → foundation`，外加一个横向供给集成的 `community`：

```text
┌────────────────────────────────────────────────┐
│ coding   编程领域的具体 agent 与工具             │
│          lead_agent / bash / read_file / …       │
├────────────────────────────────────────────────┤
│ agent    通用 ReAct 循环（不懂「编程」，只懂「想—做」）│
│          agent.py / 中间件 / 压缩 / 技能 / 子 agent │
├────────────────────────────────────────────────┤
│ foundation  最底层原语                            │
│          messages / models / tools / abort_signal │
└────────────────────────────────────────────────┘
   community：第三方集成（openai / anthropic / mcp）
```

关键纪律：`agent` 层**保持领域无关**——这套循环能驱动任意领域的 agent，不止编程；`coding` 才是编程专用的具体实现。

### 第三方库

从最下面看起，trendpower 用到的主要第三方库包括：

- **Agentic 内核**不依赖任何重型框架（没有 LangChain / LangGraph），ReAct 循环是手写的一个异步生成器——这样取消、中间件、流式产出的每个细节都完全可控。
- **模型 SDK**：`openai` 和 `anthropic`。任何兼容 OpenAI 接口的厂商（豆包、DeepSeek、Qwen、Kimi、GLM…）都直接复用 `OpenAIModelProvider`，**连新类都不用写**。
- **参数校验**：`pydantic`——所有工具参数的「入口闸门」。
- **控制台界面**：`textual` 和 `rich` 这两个控件库。

### 模型层

模型层的抽象只有两个东西（`foundation/models.py`）：

- **`ModelProvider`** 是一个 `Protocol`（结构化类型）：任何类只要实现了 `invoke`（一次性）和 `stream`（流式）两个方法，就**自动**是一个合法的 provider，**不需要显式继承**。这正是 trendpower 能轻松接入新厂商的根基——核心只依赖这个抽象契约，不绑定任何具体 SDK。
- **`Model`** 是一个 dataclass，持有 `name + provider + options`。它做一件关键的事——`_build_provider_params`：把系统提示拼成一条 `system` 消息塞到对话最前，再把完整对话和工具清单一起交给 provider。**这就是 system prompt 进入请求的地方。**

默认行为上，`OpenAIModelProvider` 把 `temperature` 默认设为 `0`（追求确定性），并允许把 `Model.options` 里的 provider 特有参数透传进去；`AnthropicModelProvider` 则会把 system 从 messages 里单独抽出来，并在开启 thinking 时自动按 `max_tokens * 0.8` 补上 `budget_tokens`。

### 工具层

这是 Coding Agent 的「手脚」，也是和 Claude Code 形态最接近的地方。与某些方案把读写合并成一个 `text_editor` 大工具不同，**trendpower 选择把工具拆得很细**——每个工具职责单一、参数 schema 清晰，模型更容易选对、也更容易从错误码里判断下一步。

每个工具都遵循同一个模式：定义一个 pydantic 参数类 → 写 `async def _invoke(params)` → 用 `define_tool(...)` 包装导出。`define_tool` 会自动加一层包装：**先用 pydantic 校验模型传来的原始 dict，再把校验后的实例交给执行体**——坏输入根本进不了业务逻辑。

#### 文件系统工具集（感知与定位）

| 工具 | 说明 |
|---|---|
| `list_files` | 列出指定目录下的子目录和文件，用于文件列举 |
| `glob_search` | 按 Glob 通配模式查找文件，用于按名字/路径模糊定位 |
| `grep_search` | 按字符串/正则在代码里检索内容，是「代码定位」的主力（底层需要环境里有 ripgrep，缺失时返回 `RG_NOT_FOUND`） |
| `file_info` | 查看单个文件的元信息（大小、类型等） |

#### 文本编辑器工具集（生成与编辑）

| 工具 | 说明 |
|---|---|
| `read_file` | 读取文件，支持行范围切片与字符上限；整文件未截断时返回原文，否则返回带行号的片段 |
| `write_file` | 创建/覆盖写入整个文件 |
| `str_replace` | 用新字符串精确替换文件中的特定字符串，用于小范围的精确编辑 |
| `apply_patch` | 应用 patch 式的定向编辑——最强的编辑工具，system prompt 里明确推荐「优先用它」，失败则回退到更安全的策略 |
| `mkdir` / `move_path` | 建目录 / 移动（重命名）路径 |

> 这里没有 `undo` 工具。原因和 Anthropic 当初的取舍一致：模型尚不能稳定理解「每次撤销的动作范围」，与其留一个会引发误操作的撤销，不如让模型「读—改—再读验证」。trendpower 同样不提供 undo。

#### 命令行工具

| 工具 | 说明 |
|---|---|
| `bash` | 执行 shell 命令，跨平台解析 shell（`TRENDPOWER_BASH_SHELL` 覆盖 → zsh/bash/sh → Windows 回退 cmd.exe）；取消时通过监听器 `kill` 子进程 |

#### To-do 列表工具

| 工具 | 说明 |
|---|---|
| `todo_write` | 让 Agent 主动创建并不断更新 To-do 列表（支持增量 merge 或全量替换） |

`todo_write` 本身**不具备任何实际副作用**，是一个典型的「Pseudo Tool」——它存在的唯一意义，是不断「启发」Agent 去做 Planning。配套的中间件还会在「距上次更新待办超过 10 步」时注入一段 `<todo_reminder>`，提醒模型刷新进度。

#### 询问用户工具

| 工具 | 说明 |
|---|---|
| `ask_user_question` | 让模型向用户提 1～4 个并行的选择题（每题 2～4 个选项），用于在分叉处征求决策 |

#### 子 Agent 工具

| 工具 | 说明 |
|---|---|
| `task` | 裂变一个隔离的子 Agent（`explore` / `general`）去做受限子任务，只回收一句结论（见上文「Single 还是 Multi-Agent」） |

#### MCP 工具加载器

trendpower 还能加载 `~/.trendpower/mcp_servers.json` 里配置的 MCP server，把它们暴露的工具适配成本地 `FunctionTool`（加 `servername__` 前缀防撞名），通过 `create_coding_agent` 的 `extra_tools` 参数注入。这部分原理见 [`docs/mcp.md`](mcp.md)。

#### 工具结果的「规整 + 裁剪」

值得单独一提的是：工具跑完之后，结果**不会原样塞回对话**。`agent/tool_result/` 会先把任意返回值**规整**成统一形态（成功 `{ok, summary, data}` / 失败 `{ok, summary, error, code}`），再按工具类型分级**裁剪**（列目录只留摘要、读文件可留 12000 字符、子 Agent 报告偏向只留 summary……）。这本质上是在控制「每条观测占多少上下文预算」，是上下文工程的一部分。

### System Prompt（精心分块的指令）

System Prompt 不是一段随意的话，而是用 XML 风格的标签**结构化分块**的指令（`coding/agents/lead_agent.py`）：

```text
<agent name="trendpower" role="leading_agent" description="A coding agent"> … </agent>
<working_directory dir="…/" />
<tool_usage>  …如何使用工具的规则（先看目录、读后再改、优先 apply_patch…）  </tool_usage>
<notes>       …注意事项（别起本地服务、简单问候就简单回答、多步任务先 todo_write）  </notes>
<subagents>   …是否启用子 agent 的指引  </subagents>
<project_instructions>  …项目根目录的 AGENTS.md，开场自动读入  </project_instructions>
```

这里有一个关键设计决定：项目自带的 **`AGENTS.md` 被放进 System Prompt**，而不是当作第一条用户消息。因为放在 System Prompt 里，它既能进入「稳定前缀」被缓存，又永远不会被压缩误删（压缩只改写对话，从不动系统提示）。

### Agent 层（把一切组装起来）

`agent/agent.py` 的 `Agent` 类把模型、提示、工具、中间件组装成一个引擎。它的核心是异步生成器 `stream`：

```python
for step in range(1, maxSteps + 1):
    signal.throw_if_aborted()          # ① 每步开头查取消
    await self._before_agent_step(step)
    async for ev in self._think():     # ② 思考：调模型，流式 yield 进度
        if ev["type"] == "_think_done":
            assistant_message = ev["message"]; break
        else: yield ev
    yield {"type": "message", "message": assistant_message}
    tool_uses = self._extract_tool_uses(assistant_message)
    if not tool_uses:                  # ③ 模型不再调工具 → 任务完成
        return
    async for ev in self._act(tool_uses):  # ④ 行动：并行跑所有工具
        yield ev
```

它有几个值得记住的设计点：

- **transcript 即状态**：Agent 自身**没有独立状态机**，整个对话状态就是那个不断增长的 `Message[]` 列表。模型无状态，所以每一步都要把「System Prompt + 完整对话 + 工具清单」**重新发一遍**。
- **中间件做横切**：主循环只管「想—做」。所有横切关注点——**压缩、技能注入、待办提醒、文件变更追踪、工具审批**——全做成中间件，在循环的固定钩子点被调用。核心循环对它们一无所知；加一个新横切能力 = 加一个实现若干钩子的对象。
- **失败分级、绝不连累主任务**：单个工具异常被捕获成一条 `"Error: …"` 结果**喂回模型让它自愈**，而不是掀翻整个循环；撞到 `maxSteps` 不报错，而是**软着陆**——注入一句「请总结进度」并把 `tools` 临时设为 `None`，逼模型用现有信息交一份总结；连辅助功能（压缩）失败也只是记一条 warn、退化继续。
- **端到端协作式取消**：用户按 Ctrl+C → 一个自定义的 `AbortSignal` 被触发，循环每步开头主动检查、`_act` 里和工具任务赛跑、bash 子进程被 kill、子 Agent 一并停止——没有谁被「强杀」，所有人监听同一个信号、各自优雅退出。

至于**为什么要缓存、为什么要压缩**：因为每步重发整段上下文，长任务里开头那段「工具 + 系统提示 + AGENTS.md」会被一字不差重发很多次。于是 trendpower 把不变内容堆在最前形成「稳定前缀」并打上缓存断点（`community/anthropic/model_provider.py`），又在对话逼近阈值（默认约 10 万 token）时把中段历史「保头、保尾、摘中段」地压缩掉。这些上下文工程手段，在 [`docs/trendpower-基础与设计.md`](trendpower-基础与设计.md) 第四部分有完整推导，这里不再展开。

### 技能：另一种上下文节流

最后还有一个轻量但好用的扩展点——**技能（Skill）**。技能就是一个含 `SKILL.md`（带 YAML frontmatter）的文件夹。技能中间件在开场时把「技能**目录**」（只有名字 + 一句描述）注入 System Prompt，模型判断任务相关时才用 `read_file` 去读技能正文。

这是一种「**渐进式披露**」：系统提示里只放索引、不放正文，按需才付费加载——和子 Agent 的「事前隔离」一样，都是在为有限的上下文预算精打细算。

---

## 为何 Coding Agent 如此青睐 Console UI 设计？

你可能不禁要问：为何几乎所有的 Coding Agent 都清一色地选择了命令行 CUI（Console UI）/ CLI 呢？trendpower 也不例外——它的默认界面是一个 Textual 终端 App。原因有这么几条：

- **轻量与低开发成本**：对比图形化界面（GUI），Console UI 不需要处理复杂的窗口管理、按钮渲染、事件监听等，简单布局一下，在保持一定「程序员审美」的同时，开发效率高很多。
- **跨平台兼容性**：终端几乎是所有开发环境的「公共语言」，无论是 Linux、macOS 还是 Windows 都能跑。
- **适合持续集成工作流**：可以被轻松集成到 CI/CD 流程。
- **可移植性与低资源占用**：Console UI 占用内存和 CPU 极小，非常适合在远程服务器、容器或嵌入式设备上运行，还可以通过 SSH 远程控制。
- **渐进式增强**：可以先用 Console UI 实现 MVP，再推出 IDE 插件、Web 界面、桌面 App 等。

最后这一条，trendpower 自己就是个现成例子——正因为核心库和界面是**单向解耦**的，`trendpower-web` 才能在几乎不碰循环、工具、中间件的前提下，复用整个 TUI、再加一层「把每轮 LLM 请求投到浏览器」的可视化。这恰恰印证了开头那句话：**界面只是最外面的一层壳，真正的 Agent 全在核心库里。**

---

## 附：进一步阅读

- 基础与设计的完整推导（Python 先修 + 架构 + 上下文工程）：[`docs/trendpower-基础与设计.md`](trendpower-基础与设计.md)
- 每个文件做什么、一次对话的完整生命周期：[`docs/architecture.md`](architecture.md)
- 启动到回答的执行追踪：[`docs/execution-flow.md`](execution-flow.md)
- MCP 集成原理 + 安装新 server 实操：[`docs/mcp.md`](mcp.md)
- 源码入口：`trendpower-py/trendpower/agent/agent.py`（循环心脏）、`trendpower-py/trendpower/coding/agents/lead_agent.py`（组装现场）
