# trendpower 的 Harness Engineering 与 Context Engineering 设计

> 这份文档讲的不是"哪个文件做什么"（那是 [architecture.md](architecture.md)），而是**为什么这样设计**：trendpower 作为一个 agent harness，在模型之外的那一圈工程上做了哪些决策，每个决策解决什么问题、放弃了什么。读完它你应该能回答："换我来设计，为什么也会这么做。"
>
> 引用代码用 `路径:符号` 的形式（行号会随改动漂移，符号名不会）。

---

## 0. 先把概念立住：什么是 harness，什么是 context engineering

一个 agent 产品 = **模型** + **harness**。

- **模型**是黑盒，你基本只能选型、调采样参数、开关 thinking。
- **harness** 是模型之外你能完全掌控的一切工程：怎么组织提示、怎么把工具暴露给它、怎么执行工具、怎么把观测喂回去、上下文涨了怎么办、出错了怎么办、长任务怎么收尾。

**同一个模型，harness 的好坏能决定它是玩具还是生产力工具。** 本文分两部分：

- **Part I — Harness Engineering**：循环、中间件、工具、并发、权限、子 agent、失败处理、provider 抽象。
- **Part II — Context Engineering**：在"每一步都要把整段对话重新发给模型"这个根本约束下，如何经营那块有限且昂贵的上下文窗口。

两者是一体两面：harness 决定了上下文里**会装进什么**，context engineering 决定了**怎么装才划算**。

---

# Part I — Harness Engineering

## 1. 核心循环：ReAct，并且是"流式生成器"形态

入口是 `agent/agent.py:Agent.stream`。一轮 step 做两件事——**think（让模型推理/决定调哪些工具）** 和 **act（执行工具、把结果喂回去）**——循环到模型某轮不再调工具为止：

```
for step in 1..maxSteps:
    think  → 得到 assistant 消息（可能含 tool_use）
    若无 tool_use → 结束返回
    act    → 并行执行工具，把 tool_result 追加进 transcript
```

**设计决策：整个循环是 `async generator`，逐事件 `yield`，而不是跑完再返回。**

- 合理性：agent 的价值有很大一部分在"过程可见"。流式产出 `progress`（思考中/正在跑某工具）和 `message`（助手回复、工具结果）事件，让 UI 能实时反馈，而不是转圈等几十秒。`_think` 把模型流的每个快照转成 `progress` 事件（`agent/agent.py:_derive_progress`）。
- 代价：调用方必须用 `async for` 消费，且要处理"中途取消"。这换来的实时性对交互式 agent 是值得的。

**单一职责边界**：循环本身只懂 think/act/中间件分发，**不懂任何 coding 细节**。它在 `agent/` 层，coding 相关的工具和提示在 `coding/` 层。这条边界让同一个循环能驱动任意领域的 agent。

## 2. 中间件架构：洋葱模型，而不是把逻辑焊死在循环里

循环在几个固定时点回调一串中间件钩子（`agent/agent.py`，`_before_model / _after_model / _before_agent_run / _after_agent_run / _before_agent_step / _after_agent_step / _before_tool_use / _after_tool_use`）。每个中间件是个鸭子类型对象，实现哪个钩子就挂哪个。

**设计决策：把"压缩历史、注入 skills、待办管理、工具审批"全部做成可插拔中间件，而不是写进循环。**

- 合理性一（关注点分离）：循环保持 ~150 行的纯逻辑；compaction、skills、todo、approval 各自独立演进、独立测试、可独立开关。
- 合理性二（顺序即语义）：中间件是**有序列表**，顺序本身携带设计意图。最典型的——compaction 中间件在 `coding/agents/lead_agent.py:create_coding_agent` 里被 `insert(0, ...)` **放到最前**，因为它要在其它 `beforeModel` 钩子（如 skills 注入）读到 transcript **之前**先把历史压实。
- 合理性三（可变上下文共享）：钩子返回的 dict 会被 merge 进共享的 `AgentContext`，中间件之间通过它通信而不必互相知道彼此存在。

这套 hook 的设计直接对应主流 agent 框架的"生命周期回调"，是经过验证的扩展点形态。

## 3. 工具系统：pydantic 作校验边界，结构化结果作通信契约

工具定义在 `foundation/tools.py`。`define_tool` 接收一个 **pydantic 模型类**作为参数 schema，并把用户的 `invoke` 包一层（`foundation/tools.py:define_tool` 内的 `wrapped`）：模型吐出的原始 dict 先 `model_validate` 再交给业务代码。

**设计决策：把"不可信的模型输出"和"可信的工具实现"之间的校验边界，用 pydantic 固定下来。**

- 合理性：LLM 产生的工具参数是不可信输入（可能缺字段、类型错、幻觉出不存在的参数）。在边界上做一次强校验，业务代码就永远拿到类型正确的对象；校验失败自动变成一条工具错误喂回模型，让它自我修正，而不是抛异常崩掉。
- 逃生舱：`raw_input_schema` 允许直接塞 JSON Schema（MCP 工具用它把 server 的原始 schema 透传，不经 pydantic 往返），保证了对外部工具的兼容。

**结构化工具结果**（`foundation/tools.py:StructuredToolResult` + `agent/tool_result/runtime.py:normalize_tool_result`）：工具返回 `{ok, summary, data}` 或 `{ok:false, summary, error, code}`，再由 `infer_tool_error_kind` 把 `code` 归类成 `invalid_input / not_found / environment_missing / ...`。

- 合理性：这是 harness 和模型之间的**通信协议**。`summary` 给模型读、`data` 给程序用、`errorKind` 让模型能"按错误类型决策下一步"（系统提示里就明确要求它利用 error code）。比起返回一坨裸字符串，这让模型的纠错行为可预期得多。

## 4. 并行工具执行 + 取消竞速

一轮里若模型发起多个 `tool_use`，`agent/agent.py:_act` 用 `asyncio.create_task` **并行**跑，并额外起一个 `abort_task` 监听取消信号，用 `asyncio.wait(..., FIRST_COMPLETED)` 让两者竞速。

**设计决策：工具并发执行；取消必须能抢占式生效。**

- 合理性（并发）：模型常一次性发 3 个 grep/read，串行跑是纯浪费。并发把这轮的墙钟时间压到最慢的那个工具。
- 合理性（取消）：交互式 agent 必须能被用户随时打断。如果只是 `await gather(tasks)`，取消信号要等所有工具自然结束才生效——一个慢命令就让 Ctrl-C 失灵。竞速 `abort_task` 让取消**立刻**抛出 `AbortError`，未完成的工具 task 被 cancel。取消是用协作式的 `AbortSignal`（`foundation/abort_signal.py`）传播的，工具内部（如 bash 子进程）注册 listener 在取消时 kill。

## 5. 权限与审批：在 `beforeToolUse` 拦截，用 `__skip` 协议短路

`coding/permissions/coding_approval_middleware.py` 在 `beforeToolUse` 钩子里拦截需审批的工具（`requires_approval.py:CODING_TOOLS_REQUIRING_APPROVAL` = bash/write/str_replace/apply_patch/mkdir/move_path）。它弹给用户确认；用户拒绝时返回 `{"__skip": True, "result": ...}`，循环识别这个协议后**跳过真正执行**、直接把这条结果喂回模型。

**设计决策：把"危险操作要人确认"做成一个中间件 + 一个短路协议，而不是在每个工具里写审批。**

- 合理性：审批是横切关注点，散在每个工具里会重复且易漏。集中在一个中间件里，加一个工具进审批名单只是改一个列表。`__skip` 协议让"被拒绝"也能优雅地变成一条模型可读的观测（"用户拒绝了，请换方案或问清楚"），而不是异常。
- "总是允许"通过 `ApprovalPersistence` 落进项目设置，下次同名工具直接放行——把人类信任**沉淀**下来，减少打扰。

## 6. Sub-agent：用"上下文隔离"换主线的清爽

`coding/tools/task.py:create_task_tool` 提供一个 `task` 工具，主 agent 调用它时，`agent/subagent/runner.py:run_subagent` 会 **new 一个独立的 `Agent`**，在它**自己的 transcript** 里跑完一个子任务，**只把最终文字报告**回传主线。

**设计决策：把"广撒网的探索"从主循环里剥离到隔离的子 agent。**

- 合理性（这是最重要的能力台阶）：一次"在 repo 里找出所有调用 X 的地方"会产生几十条 grep/read 噪音。若留在主线，既烧 token，又稀释主 agent 的注意力，还会破坏缓存前缀（见 Part II）。子 agent 把这些噪音关进一个用完即弃的 transcript，主线只收到一句结论。**这是用一次额外的模型开销，换主线上下文的纯净度。**
- 分层落地：通用的"跑一个内层 agent"原语在 `agent/subagent/`（领域无关），具体"给哪些工具、什么提示、哪个模型"的接线在 `coding/tools/task.py`，严格遵守 `foundation→agent→coding` 的单向依赖。
- 两种风味：`explore`（只读工具集、免审批，安全且高价值）与 `general`（完整工具集、转发父级审批）。
- 安全不变量：子 agent **永不获得 `task` 工具**（`coding/tools/task.py:_NEVER_DELEGATE`，递归深度恒为 1）和 `ask_user_question`（不能反过来阻塞用户）。`base_tools` 快照在把 `task` 追加进主工具集**之前**截取，从源头杜绝自我递归。
- fan-out 白送：主循环的并行 act（见 §4）意味着模型一次发 3 个 `task` 就是 3 个子 agent 并发跑，各自独立 transcript。

## 7. 失败软着陆：撞上限不崩，而是交一份阶段性答卷

`agent/agent.py:_emit_step_limit_summary`：跑满 `maxSteps` 时，不再 `raise RuntimeError`，而是注入一条提示（`_STEP_LIMIT_PROMPT`）要求模型停止调工具、总结成果/遗留/下一步，并把这一轮的 `tools` 临时置为 `None` 强制只出文字，返回这份总结。

**设计决策：把"硬崩溃"换成"受控收尾"。**

- 合理性：一个跑了几分钟、改了一半文件的长任务，撞上限只甩一句报错、丢光进展，是最差的体验。软着陆把它变成"我做到这一步，剩下这些，建议接着这么做"——用户可据此续问或开新一轮。代价仅一次额外的模型调用。"强制 tools=None"保证收尾轮一定产出文字而不会又去调工具。

## 8. Provider 抽象：一个 Protocol，把模型后端关在 `community` 层

`foundation/models.py:ModelProvider` 是个 `Protocol`（只要求 `invoke` 和 `stream`）。具体实现（`community/openai`、`community/anthropic`）住在 `community/` 集成层。`foundation/models.py:Model._build_provider_params` 负责把内部统一的 `Message[]` 组装成请求，并把 system 提示作为独立的 `system` 角色消息前置。

**设计决策：核心层只依赖一个窄接口；每个真实后端是可替换的适配器。**

- 合理性：换模型/接新厂商（包括任意 OpenAI 兼容端点，如豆包/火山方舟）只是写一个新 provider，循环、工具、中间件一律不动。统一的 `Message` 类型是"对话真相的唯一来源"，provider 只在边界上做格式翻译（如 `community/anthropic/utils.py` 把 tool_result 翻译成 Anthropic 要求的 user 角色块）。

---

# Part II — Context Engineering

## 0. 根本约束：每一步都在重发整段对话

ReAct 循环里，模型是无状态的——**每一步 think 都要把 system 提示 + 整个 transcript + 工具 schema 全量发过去**（`foundation/models.py:Model._build_provider_params`）。这意味着：

- 上下文窗口是**有限**资源：transcript 无界增长，迟早撑爆。
- 上下文是**昂贵**资源：一个 30 步的任务，那段不变的前缀要被重新计费、重新 prefill 30 次。
- 上下文是**注意力**资源：塞进去的噪音越多，模型越容易被带偏。

Context engineering 就是在这三重压力下经营这块窗口。下面是 trendpower 的五个手段。

## 1. 稳定前缀：把不变的东西堆在最前面

请求的字节布局被刻意设计成"**越稳定的越靠前**"：

```
[ 工具 schema (整个 run 不变) ] [ system 提示 (不变) ] [ 增长的对话 ]
```

- system 提示由 `coding/agents/lead_agent.py:create_coding_agent` 拼成一个稳定字符串：agent 角色、工具使用守则、`<subagents>` 引导、以及 **`<project_instructions>`（即 AGENTS.md 内容）**。
- **设计决策：AGENTS.md 放进 system 提示，而不是当作第一条 user 消息。** 合理性有二：① 它是项目级框架信息，语义上属于 system；② 更关键——放进 system 就进入了"永不变动的前缀"，既能被缓存（见 §2），又**永远不会被 compaction 消耗**（compaction 只改写对话消息，不动 system 提示，见 §4）。
- skills 通过 `agent/skills/skills_middleware.py` 在 `beforeModel` 里把 `<skill_system>` 追加到 prompt 末尾——因为 `self.prompt` 基串不变、追加逻辑确定，所以每轮拼出的 system 字符串逐字节相同，可缓存。

## 2. Prompt Caching：把"重发不变前缀"的成本和延迟压掉

`community/anthropic/model_provider.py:_apply_cache_control` 在请求前缀打 3 个 `cache_control: ephemeral` 断点：**最后一个工具**（缓存整个工具 schema 数组）、**system 块**、**最后一条消息的最后一个块**（让不断增长的对话也走增量缓存，下一轮命中）。

**设计决策：在三个稳定边界打缓存断点；并把缓存 token 折算回 `promptTokens`。**

- 合理性（成本/延迟）：前缀（工具 + system + AGENTS.md）是请求里最大的不变部分，命中缓存后输入 token 成本和 TTFT 都大幅下降。这是 harness 里 ROI 最高的单点改动。
- **一个易漏的耦合**：开缓存后，Anthropic 的 `input_tokens` 只统计**未命中**的 token，缓存命中部分单列在 `cache_read_input_tokens`/`cache_creation_input_tokens`。若不处理，`promptTokens` 会突然"变小"，导致 compaction（依赖它判断是否触发，见 §4）**永不触发 → 最终撑爆窗口**。所以 `_to_token_usage` 和 `stream_utils.py:StreamAccumulator` 都把这两项折算回 `promptTokens`，保持它"本轮 prompt 真实大小"的语义。
- 对 OpenAI 系（含豆包）这层是自动前缀缓存，无需打标记；且它们的 `prompt_tokens` 本就含缓存部分，所以上面的耦合 bug 不存在——§1 的稳定前缀设计同样让它们直接吃到缓存红利。

## 3. Tool-result 工程：决定"每条观测占多少上下文"

工具结果在进入 transcript 前，过一道 `agent/tool_result/runtime.py:format_tool_result_for_message`，按 `agent/tool_result/policy.py:get_tool_result_policy` 的**逐工具策略**裁剪。

**设计决策：不同工具的结果，按其信息密度分别对待。**

- `list_files/glob_search/grep_search/...` → `preferSummaryOnly`，只留一句摘要、丢弃原始 data（目录列表这种东西，模型要的是"找到了什么"，不是把整棵树背进上下文）。
- `read_file` → 保留内容，但上限 12000 字符（读文件本就是为了看内容，给得多）。
- 写类工具 → 中等上限。
- `task`（子 agent 报告）→ summary-only，上限 8000（报告是整个内层 run 的浓缩产物，值得多留）。

合理性：**喂回模型的每个 token 都是成本和注意力**。把"摘要 vs 原始数据 vs 截断长度"做成一等公民按工具配置，等于在源头控制上下文的增速和信噪比。

> （已知可改进项：bash 的超长输出目前"留头丢尾"，而测试/堆栈的关键信息常在结尾——这是 tool-result 工程里值得继续打磨的一处。）

## 4. Compaction：窗口要满时，摘要掉中段、保住两头

`agent/compaction/compaction.py:create_compaction_middleware` 是个 `beforeModel` 钩子：当 `estimate_tokens` 超过 `trigger_tokens`（默认 100k）时，把 transcript 切成 **head / middle / tail**，用模型把 middle 摘要成一段，原地替换。

**设计决策与其合理性：**

- **保头**（`keep_head_messages`）：开头是任务框架/项目信息，丢了模型就忘了"在干嘛"。
- **保尾**（`keep_recent_messages`）：最近几轮是"当前进行到哪"，必须逐字保留。
- **摘要中段**：中间的探索细节最适合压成"我们查过这些文件、得到这些结论"。摘要提示（`_SUMMARY_SYSTEM_PROMPT`）明确要求保留：目标、改过的文件及其状态、命令及结果、决策及理由、未解问题、下一步。
- **tool-pairing 不变量**（`plan_compaction`）：这是最容易踩的坑——一个带 `tool_use` 的 assistant 消息后面**必须**紧跟对应的 `tool_result`，provider 会拒绝落单的任何一半。所以切分时绝不让 head 收尾在一个其结果会被摘掉的 `tool_use` 上，也绝不让 tail 起始于一条孤儿 `tool` 消息。`plan_compaction` 用两个 while 循环把边界往安全处回退。
- **触发估算的稳健性**（`estimate_tokens`）：优先用最近一次模型响应的真实 `promptTokens`，回退到字符启发式（`len/4`），取两者较大值——这样"刚发生一波大工具结果"也能立刻触发，而不必等下一次模型响应。这条又把我们绕回 §2 的耦合：正因为 compaction 命脉系于 `promptTokens`，开缓存时才必须把缓存 token 折算回去。
- **失败安全**：摘要调用若抛错，记一条 warning 然后**不压缩继续跑**（`except ... return None`），绝不让 compaction 把一次正常的 run 搞崩。

## 5. Sub-agent 作为上下文工程手段（从 context 视角再看一次）

§I.6 从能力角度讲了子 agent，这里从上下文角度补一刀：**子 agent 本质是一种"上下文隔离的 compaction"**。compaction 是事后有损压缩主线已经积累的噪音；子 agent 是**事前**就让噪音根本不进主线。两者互补：

- 该用子 agent：任务一开始就知道"这是一大段探索"，直接委派，噪音从不污染主线。
- 该靠 compaction：噪音已经在主线里了（比如一长串交互式调试），事后摘要兜底。

## 6. Progressive Disclosure：skills 只先给目录，用时再展开

`agent/skills/skills_middleware.py` 在系统提示里只注入每个 skill 的 **frontmatter（名字 + 一句描述 + 路径）**，不注入正文。模型判断某个 skill 与当前任务相关时，才用 `read_file` 按路径把正文读进来。

**设计决策：能力清单常驻、能力细节按需加载。**

- 合理性：若把所有 skill 的完整正文都塞进每轮 prompt，skill 一多就把上下文挤爆，且大部分内容当前任务用不到。"先给一行目录、用时再 `read_file`"是经典的渐进披露——让模型自己决定何时为某个 skill 付出上下文代价。这与子 agent、tool-result policy 是同一种哲学：**上下文是预算，按需支付。**

---

# Part III — 设计哲学一句话总览

| 关注点 | 决策 | 一句话合理性 |
|---|---|---|
| 循环 | ReAct + async generator | 过程可见、可取消 |
| 扩展 | 有序中间件洋葱 | 关注点分离，顺序即语义 |
| 工具入参 | pydantic 校验边界 | 不可信模型输出在边界被驯服 |
| 工具结果 | 结构化 + errorKind | harness↔模型的可预期通信协议 |
| 并发 | 并行 act + 取消竞速 | 省墙钟时间，打断立即生效 |
| 权限 | beforeToolUse + __skip | 横切审批集中化，拒绝也优雅 |
| 隔离 | sub-agent | 用一次开销换主线纯净 |
| 失败 | maxSteps 软着陆 | 崩溃→阶段性答卷 |
| 后端 | ModelProvider Protocol | 换厂商不动核心 |
| 前缀 | 稳定前缀 + 缓存断点 | 把重发不变前缀的成本压掉 |
| 观测 | 逐工具结果策略 | 每个 token 都是成本和注意力 |
| 历史 | 保头保尾摘中段 + tool-pairing | 满窗时有损压缩而不破坏配对 |
| 能力 | skills 渐进披露 | 上下文是预算，按需支付 |

**贯穿全文的一条主线**：把"上下文窗口"当成一种**有限、昂贵、且承载注意力**的预算来经营——稳定前缀省钱、缓存省钱、逐工具策略控增速、compaction 兜底、子 agent 隔离、渐进披露按需付费。harness 的每个决策，最终都落回"这块预算花得值不值"。

---

# Part IV — 仍在演进的方向

这套设计已经覆盖了一个生产级 harness 的主干，以下是清单上待做/可深化的项（不影响上述设计的成立，是锦上添花）：

- **bash 工具加固**：执行超时（防永久挂起）、stdout+stderr 双路捕获、超长输出"留头+留尾"、结构化 exit code。
- **Provider 重试退避**：对 429/5xx/网络抖动做指数退避，避免一次瞬时错误崩掉长 run。
- **Compaction 提速降本**：用更便宜的模型做摘要、或后台预压缩，避免阻塞当轮。
- **可观测性 / tracing**：per-step 落盘（prompt 大小、工具调用、延迟、token、缓存命中率），支撑离线 eval 迭代提示。
- **联网工具**：补 web_search/web_fetch，让研究类 skill 名副其实。
- **环境上下文块**：在 system 前缀里加稳定的 `<env>`（cwd 树/git 状态/平台/日期），帮模型更快定向（且进缓存、零额外成本）。

> 这些项的优先级与现状见仓库的优化 backlog；本文聚焦"已成立的设计为什么成立"。
