# trendpower 基础知识与架构设计

> 本文是阅读 trendpower 源码前的**先修文档**。目标读者是有一定编程基础、但不熟悉 Python 异步生态与 Agent（智能体）系统设计的人。
>
> 全文分四部分，建议按顺序读：
>
> 1. **Python 先修知识** —— 读懂这套代码必须掌握的语言特性（异步、生成器、类型系统、闭包、异常处理）。
> 2. **整体架构** —— trendpower 由哪些部分组成、它们如何分层、一次请求如何流过整个系统。
> 3. **上下文的组成** —— 每一步真正发送给大模型的"上下文"由哪些部分拼成、为什么这样拼。
> 4. **Harness 与 Context Engineering 的设计** —— 支撑这套系统的工程设计原则，以及它们为何合理。
>
> 阅读约定：代码引用统一写成 `文件:符号` 的形式，例如 `agent/agent.py:Agent.stream`，指向 `trendpower-py/trendpower/` 下的对应位置。

---

## 第一部分 · Python 先修知识

这一部分只讲**读懂 trendpower 源码所必需**的语言特性。每个特性先给出准确定义，再说明它在 trendpower 中具体用在哪里。

### 1.1 同步、异步与事件循环

**同步（synchronous）执行**指代码一行一行顺序跑，遇到耗时操作（读文件、发网络请求、等子进程）时整个线程被**阻塞**，什么都干不了，直到该操作返回。

**异步（asynchronous）执行**的目标是：当一个任务在"等待外部结果"时，让出执行权，让同一个线程去推进其它任务，等结果就绪了再回来继续。它不靠多线程，而靠一个**事件循环（event loop）**在单线程内调度多个任务。

Python 用 `async`/`await` 表达异步：

```python
import asyncio

async def fetch(name: str) -> str:
    await asyncio.sleep(1)      # 模拟一次耗时 I/O；await 处让出执行权
    return f"{name} done"

async def main() -> None:
    # gather 同时驱动两个任务；总耗时约 1 秒而非 2 秒
    results = await asyncio.gather(fetch("a"), fetch("b"))
    print(results)              # ['a done', 'b done']

asyncio.run(main())             # 启动事件循环，跑到 main 结束
```

关键概念：

- **协程（coroutine）**：`async def` 定义的函数。调用它**不会**立即执行函数体，而是返回一个协程对象，必须被 `await` 或交给事件循环才会真正运行。
- **`await`**：只能出现在 `async def` 内。它的语义是"暂停当前协程，等右边的可等待对象完成，期间把执行权交还事件循环"。`await` 是异步代码里**唯一**的让出点——没有 `await`，再"异步"的函数也会一口气跑完、不给别人机会。
- **`asyncio.create_task(coro)`**：把一个协程包装成**任务（Task）**并立即排进事件循环。和 `await coro` 的区别是：`create_task` 不等待，马上返回一个句柄，于是多个任务可以**并发推进**。
- **`asyncio.Event`**：一个异步的"开关"。`await event.wait()` 会一直挂起，直到别处调用 `event.set()`。trendpower 用它实现"取消信号"（见 1.7 与 `foundation/abort_signal.py`）。

> **为什么 trendpower 通篇异步**：一个 Agent 的一步里充满了等待——等大模型流式返回、等 `bash` 子进程、等文件读写、等多个工具并行跑完。异步让这些等待互不阻塞、且能在单线程内并发，而无需引入多线程的复杂度。项目约定（见 `AGENTS.md`）就是"async-first"。

### 1.2 生成器与 `yield`

普通函数用 `return` 一次性交出全部结果。**生成器（generator）**用 `yield` **多次**交出结果，每次交出后函数在原地"冻结"，下次被请求时从冻结处继续。

```python
def count_up(n: int):
    for i in range(n):
        yield i          # 交出一个值，函数在此暂停
    # 函数自然结束时，迭代结束

for x in count_up(3):    # 0, 1, 2
    print(x)
```

生成器的价值是**惰性**和**流式**：值是"一边算一边吐"的，调用方拿到一个就能处理一个，不必等全部算完，也不必把全部结果攒在内存里。

### 1.3 异步生成器与 `async for`

把生成器和异步结合，就是**异步生成器**：用 `async def` + `yield` 定义，用 `async for` 消费。它表示"一个**异步地、逐个产出**的序列"——产出每个元素之间允许 `await`（即允许等待 I/O）。

```python
async def stream_chars(s: str):
    for ch in s:
        await asyncio.sleep(0.1)   # 产出之间可以等待
        yield ch                   # 异步地逐个产出

async def main():
    async for ch in stream_chars("hi"):
        print(ch)
```

**这是 trendpower 最核心的控制流。** Agent 主循环 `agent/agent.py:Agent.stream` 就是一个异步生成器：它一边推进"思考—行动"循环，一边把过程中的**事件**（模型在想、在调工具、产出了一条消息……）实时 `yield` 给前端，前端用 `async for` 接收并即时渲染。

#### 一个必须理解的技巧：用"哨兵值"模拟"流式产出 + 最终返回值"

异步生成器只能 `yield`，不能在 `yield` 的同时再 `return` 一个"最终结果"。但 trendpower 的内部方法 `_think` 既要**流式产出**中间进度，又要在结束时把"这一步最终的助手消息"交还给主循环。

解决办法是约定一个**哨兵（sentinel）事件**。看 `agent/agent.py:Agent._think`：

```python
async def _think(self):
    ...
    async for snapshot in self.model.stream(model_context):
        latest = snapshot
        if snapshot.get("streaming"):
            yield self._derive_progress(snapshot)     # 中途：产出"进度"事件
    ...
    self._append_message(latest)
    yield {"type": "_think_done", "message": latest}  # 结束：产出"哨兵"事件
```

主循环这样消费它（`Agent.stream` 内）：

```python
async for ev in self._think():
    if ev["type"] == "_think_done":
        assistant_message = ev["message"]   # 认出哨兵，取出最终结果，跳出
        break
    else:
        yield ev                            # 普通进度，原样向上转发
```

理解这个模式，就能看懂主循环里反复出现的"`async for` 子生成器 + 认哨兵"结构。它等价于其它语言里的"`yield*` 委托 + 末尾 `return value`"。

### 1.4 三种"结构化数据"的容器：TypedDict / dataclass / pydantic

Python 里描述"一个有固定字段的结构"有三种常见手段，trendpower **三种都用**，且分工明确——分清它们是读懂类型标注的前提。

| 手段 | 运行时本质 | 是否校验数据 | trendpower 中的用途 |
|---|---|---|---|
| `TypedDict` | 就是普通 `dict` | **不校验**，仅供类型检查器静态参考 | 描述**消息/事件**的形状（如 `AssistantMessage`、`ToolUseContent`） |
| `@dataclass` | 一个普通类，自动生成 `__init__` 等 | 不校验 | 描述**内部值对象**（如 `Model`、`AgentOptions`、`SubagentResult`） |
| `pydantic.BaseModel` | 一个类，但带强校验 | **运行时强制校验并转换** | 描述**工具参数**——模型传来的不可信输入的"入口闸门" |

#### TypedDict —— 形状标注，运行时还是 dict

`foundation/messages.py` 里所有消息类型都是 `TypedDict`：

```python
class ToolUseContent(TypedDict):
    type: Literal["tool_use"]
    id: str
    name: str
    input: Dict[str, Any]
```

它的意思是"一个带这些键的普通字典"。运行时 `msg["type"]` 就是普通取键，**不会**有任何校验。这样选择是因为消息要在系统里到处流动、要能直接序列化成 JSON 存档（`/resume`）、要和 TS 原版的 interface 形状一一对应——用普通 dict 最轻量。

> 注意 `total=False`：表示这些键**可选**。例如 `AssistantMessage` 的 `usage`、`streaming` 是可选的，只有模型返回了才有。

#### dataclass —— 内部值对象

```python
@dataclass
class Model:               # foundation/models.py
    name: str
    provider: ModelProvider
    options: Optional[Dict[str, Any]] = None
```

`dataclass` 用于系统**自己构造、自己使用**的可信对象，不需要校验，只想要简洁的"带字段的类 + 自动 `__init__`"。

#### pydantic.BaseModel —— 不可信输入的校验闸门

工具参数永远来自大模型的输出，是**不可信**的（字段缺失、类型不对、URL 不合法都可能）。pydantic 在这里充当"边界闸门"：声明期望的形状，运行时强制校验，校验不过直接抛错。

```python
from pydantic import BaseModel, Field

class _HttpGetParams(BaseModel):
    url: str = Field(description="要请求的 URL")   # description 会进 JSON Schema，作为给模型的字段说明
```

这条"所有工具输入都先过 pydantic"的设计是 trendpower 健壮性的关键一环，详见第四部分。

### 1.5 结构化类型：`Protocol`

`Protocol`（PEP 544）实现**结构化类型 / 鸭子类型的静态版**："只要一个对象具备这些方法，它就算这个类型"——**不需要显式继承**。

trendpower 用它定义"模型提供方"的契约（`foundation/models.py`）：

```python
class ModelProvider(Protocol):
    async def invoke(self, params: ModelProviderInvokeParams) -> AssistantMessage: ...
    def stream(self, params: ModelProviderInvokeParams) -> AsyncGenerator[AssistantMessage, None]: ...
```

任何类，只要实现了 `invoke` 和 `stream` 两个方法，就**自动**是一个合法的 `ModelProvider`，可以塞进 `Model`。`OpenAIModelProvider`、`AnthropicModelProvider` 都不需要继承 `ModelProvider`，只要"长得像"。

> **设计意义**：这就是 trendpower 能轻松接入新模型厂商的根基——core 只依赖这个抽象契约，不依赖任何具体厂商 SDK。换厂商 = 写一个满足该 Protocol 的新类。豆包、DeepSeek、Qwen 等因为兼容 OpenAI 接口，**连新类都不用写**，直接复用 `OpenAIModelProvider`。

### 1.6 闭包与工厂函数

**闭包（closure）**：内层函数"记住"并能访问外层函数的局部变量，即使外层函数已经返回。**工厂函数**就是利用闭包——一个函数返回另一个（带着被捕获配置的）函数。

```python
def make_adder(n: int):
    def add(x: int) -> int:
        return x + n        # add 记住了外层的 n
    return add

add5 = make_adder(5)
add5(10)                    # 15
```

trendpower 的**中间件**全用工厂函数构造。例如 `create_compaction_middleware(trigger_tokens=...)` 返回一个对象，对象里的钩子函数闭包捕获了 `trigger_tokens` 等配置。这样同一套中间件逻辑可以用不同配置实例化多份（见第二部分）。

### 1.7 异常与 `try/finally`：资源善后

`try/finally` 保证"无论 `try` 块是正常结束、还是中途抛异常，`finally` 块一定执行"。它用于**资源善后**：解绑监听、还原状态、取消任务。

trendpower 里两个典型用法：

**① 主循环结束时必须复位状态**（`agent/agent.py:Agent.stream`）：

```python
self._streaming = True
try:
    ...  # 整个循环
finally:
    self._streaming = False        # 无论正常结束还是抛错，都要复位
    self._abort_controller = None
```

**② 取消信号监听必须解绑**（`coding/tools/bash.py` 思路）：

```python
remove_listener = signal.add_listener(lambda: proc.kill())
try:
    await proc.communicate()
finally:
    remove_listener()              # 用完一定解绑，避免泄漏
```

#### 协作式取消（cooperative cancellation）

Python 不能"从外部强杀"一个协程。trendpower 用一个**自定义信号对象** `AbortSignal`（`foundation/abort_signal.py`）实现**协作式**取消：大家都监听同一个信号，被触发时各自优雅退出。它的三个核心能力：

```python
class AbortSignal:
    def throw_if_aborted(self):     # 若已取消则抛 AbortError —— 用于循环每步开头主动检查
        ...
    async def wait(self):           # 异步等待"被取消"这件事发生 —— 用于和其它任务赛跑
        await self._event.wait()
    def add_listener(self, cb):     # 注册"被取消时执行的回调" —— 用于让子进程/子 agent 联动退出
        ...
```

这三种用法（主动检查、赛跑、回调）会贯穿整个系统，第四部分会把它们串成一条完整的取消链路。

### 1.8 类型标注速记

读源码时还会频繁遇到这些标注，先建立直觉：

- `Optional[X]` = `X | None`，可能为空。
- `Union[A, B]` = 要么 A 要么 B。`NonSystemMessage = Union[UserMessage, AssistantMessage, ToolMessage]`。
- `Literal["text"]` = 这个字段的值只能是字面量 `"text"`，用于区分同族类型（如内容块的 `type`）。
- `List[X]` / `Dict[K, V]` = 列表 / 字典。
- `AsyncGenerator[Y, S]` = 异步生成器，产出 `Y` 类型的值。
- `Generic[P, R]` / `TypeVar` = 泛型，如 `FunctionTool[P, R]` 表示"参数类型 P、返回类型 R 的工具"。

至此，读懂 trendpower 源码所需的语言基础齐备。下面进入系统设计。

---

## 第二部分 · 整体架构

### 2.1 什么是 Agent，什么是 ReAct

一个**大模型（LLM）**本身只能做一件事：给它一段文字，它返回一段文字。它**没有记忆、不能执行动作**（不能读文件、不能跑命令、不能上网）。

**Agent（智能体）**就是套在大模型外面的一层程序，赋予它两样东西：

1. **行动能力**——把"读文件""跑命令"等封装成**工具（tool）**，让模型可以"请求调用"，由 Agent 实际执行并把结果喂回去。
2. **循环**——让"模型思考 → 调工具 → 看结果 → 再思考"反复进行，直到任务完成。

这个"思考与行动交替"的范式叫 **ReAct（Reason + Act）**。trendpower 的核心就是一个 ReAct 循环。

> 一个常用的类比：大模型是"大脑"，工具是"手脚"，Agent 循环是"神经系统"——让大脑的决策驱动手脚行动、再把行动结果反馈给大脑。

### 2.2 三个包与单向依赖

trendpower 仓库由三个 Python 包组成，依赖关系**严格单向**——下层永不依赖上层：

```
trendpower-web  ──依赖──▶  trendpower-tui  ──依赖──▶  trendpower (核心库 trendpower-py)
(浏览器可视化)          (终端界面)             (Agent 循环 / 工具 / 模型抽象，无上游依赖)
```

- **`trendpower`（核心库）**：Agent 循环、工具、模型抽象都在这里。它**不知道界面是否存在**，可单独使用。
- **`trendpower-tui`**：基于 Textual 的终端界面。只做"界面 + 事件桥接"，不含任何 Agent 逻辑。
- **`trendpower-web`**：复用整个 tui，额外把"每一轮发给模型的请求"广播到浏览器做可视化。

> **单向依赖的回报**：核心库稳定、可独立测试、可被包装成任意形态的产品（终端、网页或别的）。例如 trendpower-web 想加"请求可视化"，只需在最薄的 provider 层"插一脚"，完全不碰循环、工具、中间件。

### 2.3 核心库的四层

核心库 `trendpower-py/trendpower/` 内部再分四层，依赖同样自上而下单向（`coding → agent → foundation`，`community` 横向供给集成）：

```
┌──────────────────────────────────────────────────────┐
│ coding   编程领域的具体 agent 与工具                    │
│          lead_agent / bash / read_file / write_file… │
├──────────────────────────────────────────────────────┤
│ agent    通用 ReAct 循环（不懂"编程"，只懂"想—做"）      │
│          agent.py / 中间件 / 压缩 / 技能 / 子 agent     │
├──────────────────────────────────────────────────────┤
│ foundation  最底层原语（所有东西的"基本粒子"）           │
│          messages / models / tools / abort_signal     │
└──────────────────────────────────────────────────────┘
   community：第三方集成（openai / anthropic / mcp），横向适配 foundation 的接口
```

分层的纪律是：

- `foundation` 是稳定、可复用的基本类型，不依赖任何上层。
- `agent` 层只依赖 `foundation`，且保持**领域无关**——这套循环能驱动任意领域的 agent，不止编程。
- `coding` 才是编程专用的具体实现。
- `community` 是可选适配器，不能反向污染 `foundation`/`agent`。

### 2.4 foundation：四个基本粒子

读循环代码前，先认识 foundation 定义的四类核心对象。

**① Message（消息）—— 对话的唯一真相**（`foundation/messages.py`）

整个系统只用一种"对话记录"类型在端到端流动。一条消息有 `role`（`system`/`user`/`assistant`/`tool`）和 `content`（内容块列表）。内容块按类型分为文本、图片、思考、工具调用（`tool_use`）、工具结果（`tool_result`）。

特别注意工具调用是**成对**出现的：助手发出 `ToolUseContent`（"我要调用 read_file，参数是…"，带一个 `id`），随后一条 `role="tool"` 的消息里有 `ToolResultContent`（"这是结果"，用 `tool_use_id` 指回那个 `id`）。**这一对必须同时存在**——这个约束在压缩时是个大坑，第四部分细讲。

**② Model 与 ModelProvider —— 模型抽象**（`foundation/models.py`）

- `ModelProvider` 是第 1.5 节那个 `Protocol`，定义"怎么调用一个模型厂商"。
- `Model` 是一个 dataclass，持有一个 provider 和模型名/选项，对外暴露 `invoke`（一次性）和 `stream`（流式）。
- `Model._build_provider_params` 负责把 Agent 的上下文**组装成发给厂商的请求**——这是第三部分的主角，请记住这个方法名。

**③ Tool —— 工具**（`foundation/tools.py`）

`FunctionTool` 有 `name`、`description`（给模型看的说明书）、`parameters`（pydantic 模型类）、`invoke`（异步执行体）。用 `define_tool(...)` 构造时，它会自动用一个 `wrapped` 包装 `invoke`：**先用 pydantic 校验模型传来的原始 dict，再把校验后的实例交给你的执行体**。这就是 1.4 节说的"输入闸门"。

还有一个逃生舱 `raw_input_schema`：MCP 外部工具用它直接透传自己的 JSON Schema，不经 pydantic 往返。

**④ AbortSignal —— 取消信号**（`foundation/abort_signal.py`，见 1.7）。

### 2.5 一次请求如何流过系统

把上面的零件串起来，一次"用户提问 → 得到答案"的主干如下：

```
用户输入
  │
  ▼  前端（tui/web）：AgentRunner 把核心"事件"翻译成"界面该画什么"
create_coding_agent(...)            coding/agents/lead_agent.py
  │  组装：系统提示 + 工具集 + 中间件 → 构造一个 Agent
  ▼
Agent.stream(user_message)          agent/agent.py  ← 心脏
  │  for step in 1..maxSteps:
  │    _think  ── 调 model.stream，流式拿回助手消息（含可能的 tool_use）
  │    若无 tool_use → 结束，返回答案
  │    _act    ── 并行执行所有 tool_use，结果作为 tool 消息追加回对话
  │  （全程穿插中间件钩子：压缩 / 技能 / 待办 / 审批）
  ▼
事件流（progress / message）被前端 async for 接收并实时渲染
```

逐句对照 `Agent.stream` 的骨架（已在第一部分见过完整源码）：

```python
for step in range(1, self.options.maxSteps + 1):
    self._abort_controller.signal.throw_if_aborted()   # ① 每步开头查取消
    await self._before_agent_step(step)                # ② 跑 beforeAgentStep 中间件
    async for ev in self._think():                     # ③ 思考：调模型
        if ev["type"] == "_think_done":
            assistant_message = ev["message"]; break
        else:
            yield ev
    await self._after_model(assistant_message)
    yield {"type": "message", "message": assistant_message}
    tool_uses = self._extract_tool_uses(assistant_message)
    if not tool_uses:                                  # ④ 模型不再调工具 → 任务完成
        await self._after_agent_run(); return
    async for ev in self._act(tool_uses):              # ⑤ 行动：并行执行工具
        yield ev
    await self._after_agent_step(step)
```

`_act` 的并发是"白送"的：它用 `asyncio.create_task` 为每个 `tool_use` 起一个任务，`asyncio.wait(..., FIRST_COMPLETED)` 收割。所以模型一次发 N 个工具调用，N 个工具**真正并行**执行。同时它和一个"取消任务"赛跑——一旦取消信号先到，立即 `throw_if_aborted()` 中止整轮。

### 2.6 中间件：可插拔的横切行为

主循环本身只管"想—做"。所有**横切关注点**（压缩、技能注入、待办提醒、审批）都做成**中间件**，在循环的固定节点被调用。

中间件就是一个带若干**钩子方法**的对象（用 `SimpleNamespace` 鸭子类型构造）。Agent 在六个节点广播事件（见 `agent/agent.py` 的 `_before_model`/`_after_model`/`_before_agent_run`/`_after_agent_run`/`_before_agent_step`/`_after_agent_step`/`_before_tool_use`/`_after_tool_use`）：

```python
async def _before_model(self, model_context):
    for mw in self.middlewares:
        hook = getattr(mw, "beforeModel", None)   # 没有这个钩子就跳过
        if hook is None: continue
        result = await hook({"modelContext": model_context, "agentContext": self._context})
        if result:
            model_context.update(result)          # 钩子可返回"要修改的字段"
```

设计要点：

- **鸭子类型**：用 `getattr(mw, "beforeModel", None)` 探测——中间件只需实现它关心的钩子，其余不用管。
- **顺序即语义**：中间件按列表顺序依次调用。例如压缩中间件被 `insert(0)` 插到最前，确保"在任何读取对话的中间件之前先把对话压好"（`lead_agent.py`）。
- **返回值即修改**：钩子返回一个 dict，主循环就把它合并进上下文/消息——这是中间件影响主流程的唯一途径，边界清晰。

核心库自带的四个中间件：

| 中间件 | 钩子 | 作用 |
|---|---|---|
| 压缩 compaction | `beforeModel` | 对话超阈值时，把中段历史总结压缩（第四部分详述） |
| 技能 skills | `beforeAgentRun`/`beforeModel` | 开场扫描技能目录，把"技能目录"注入系统提示 |
| 待办 todos | `beforeModel`/`afterToolUse` | 维护任务清单并适时提醒模型 |
| 审批 approval | `beforeToolUse` | 危险工具执行前弹窗请求用户批准 |

---

## 第三部分 · 上下文的组成

这一部分回答一个具体问题：**每走一步，trendpower 究竟把什么发给大模型？** 这就是"上下文（context）"，理解它的组成是理解后面所有优化的前提。

### 3.1 根本约束：模型无状态，每步重发全部上下文

大模型是**无状态的**——它不记得上一次调用聊了什么。因此 Agent 每走一步 `_think`，都必须把**完整的上下文重新发送一遍**，模型才知道"在干什么、进行到哪了"。

这个"完整上下文"由三块构成，组装发生在 `foundation/models.py:Model._build_provider_params`：

```python
def _build_provider_params(self, context):
    messages = []
    prompt = context.get("prompt") or ""
    if prompt:                                # ① 系统提示，作为第一条 system 消息
        messages.append({"role": "system", "content": [{"type": "text", "text": prompt}]})
    messages.extend(context.get("messages") or [])   # ② 从头到现在的完整对话
    return {
        "model": self.name,
        "options": self.options,
        "messages": messages,
        "tools": context.get("tools"),        # ③ 可用工具清单
        "signal": context.get("signal"),
    }
```

所以**一次请求 = 系统提示 + 完整对话历史 + 工具清单**。字节顺序大致是：`工具清单 → 系统提示 → 对话历史`（越靠前越稳定，这个顺序对缓存至关重要，见第四部分）。

随着对话变长，每一步要重发的"对话历史"越来越大。一个走了 7 步的任务，开头那段"系统提示 + 工具清单"会被**一字不差地重发 7 次**。这个事实直接导出第四部分的全部优化。

### 3.2 三块上下文各自的组成

#### ① 工具清单（tools）

就是这次允许模型调用的工具列表。每个工具向模型呈现为"名字 + 描述 + 参数 JSON Schema"。整轮对话中工具集通常不变，所以它是请求里最稳定的部分。

> 一个例外用法：`maxSteps` 软着陆时，Agent 故意把 `tools` 设为 `None`，强制模型只能输出文字总结、不能再调工具（`agent/agent.py:_emit_step_limit_summary`）。

#### ② 系统提示（system prompt）—— 精心分块的指令

系统提示不是一段随意的话，而是**结构化分块**的指令。看 `coding/agents/lead_agent.py` 如何拼装：

```python
prompt = (
    f'<agent name="trendpower" role="leading_agent" description="A coding agent">\n'
    f"Use the given tools and skills to ... solve the user's problem ...\n"
    f"</agent>\n\n"
    f'<working_directory dir="{cwd}/" />\n\n'
    f"<tool_usage>\n  ...如何使用工具的规则...\n</tool_usage>\n\n"
    f"<notes>\n  ...注意事项...\n</notes>\n"
    f"{subagents_section}"        # 是否启用子 agent 的指引块
    f"{agents_section}"           # 项目自带的 AGENTS.md（见下）
)
```

- 用 XML 风格的标签（`<agent>`、`<tool_usage>`、`<notes>`…）分块，是为了让模型清晰区分不同类别的指令。
- **`<project_instructions>`（即项目根目录的 `AGENTS.md`）被放进系统提示**，而不是当作第一条用户消息。这是个关键设计决定：放在系统提示里，它既能进入"稳定前缀"被缓存，又永远不会被压缩误删（压缩只改写对话，从不动系统提示）。详见第四部分。
- 技能中间件还会在 `beforeModel` 时把"技能目录"追加进系统提示（见 2.6）。

#### ③ 对话历史（messages）—— 不断增长的事件流

这是从任务开始到当前的**完整 transcript**：用户消息、助手消息（含思考、文字、工具调用）、工具结果消息，按时间顺序排列。它是唯一不断增长的部分，也是上下文管理（缓存、压缩、裁剪）主要作用的对象。

其中工具结果消息的内容是被**裁剪过**的——不是工具的原始输出，而是经过"按工具类型分级裁剪"后的结构化结果（见第四部分 4.4）。

### 3.3 上下文的"三重压力"

把上下文当作发给模型的"一桌纸"，它有三个固有压力，是后面所有设计的动因：

| 压力 | 含义 | 后果 |
|---|---|---|
| **有上限** | 模型一次能处理的 token 数有限 | 对话堆满就"看不全"，请求失败 |
| **很贵** | 按 token 计费，重复的前缀重复计费 | 长任务成本飙升 |
| **会乱** | 内容越多噪音越多 | 模型注意力被无关信息稀释，质量下降 |

> **token**：模型计费与计量的最小单位，约等于"一小段文字"（英文约 4 字符/token）。token 越多，越贵、越慢、越容易触上限。

第四部分讲的所有"上下文工程"手段，本质都是在缓解这三重压力。

---

## 第四部分 · Harness 与 Context Engineering 的设计

前三部分讲了"是什么"，这一部分讲"为什么这样设计、为什么合理"。两个术语先定义清楚：

- **Harness Engineering（载体工程）**：设计**包裹大模型的那层程序**——循环怎么转、工具怎么定义与执行、出错与取消怎么处理、健壮性如何保证。它决定了 Agent 是"一出错就崩"还是"稳稳兜住"。
- **Context Engineering（上下文工程）**：经营"每步发给模型的那段上下文"——怎么省钱（缓存）、怎么防撑爆（压缩）、怎么控噪音（裁剪、隔离）、怎么把内容放对位置。

### 4.1 Harness 设计原则一：ReAct 循环作为骨架

为什么是"想—做"循环而不是别的结构？因为任务在执行前**无法预知**需要哪些步骤——读到文件 A 才知道要不要读 B，跑了测试才知道要不要改代码。所以必须"看一步、做一步、再根据结果决定下一步"。`Agent.stream` 的 `for step in range(...)` 正是这个骨架，循环的退出条件是"模型不再请求调用任何工具"（`if not tool_uses: return`）——即模型认为任务已完成。

### 4.2 Harness 设计原则二：工具的"校验—执行—规整—裁剪"四段式

模型的输出**不可信**，所以工具执行被设计成一条带闸门的流水线：

1. **校验（boundary）**：`define_tool` 的 `wrapped` 用 pydantic 校验模型传来的原始 dict。参数不合法直接抛错，**坏输入进不了执行体**。
2. **执行（invoke）**：执行体只在"输入已合法"的前提下干活，逻辑得以简化。
3. **规整（structure）**：执行结果统一规整成结构化形态——成功是 `{ok: True, summary, data}`，失败是 `{ok: False, summary, error, code}`（`foundation/tools.py` 的 `StructuredToolResult`）。模型据此稳定地判断成败与原因。
4. **裁剪（trim）**：结果按工具类型分级裁剪后才进对话（见 4.4）。

这四段把"不可信输入 + 任意副作用 + 体量不可控的输出"驯化成"可信、稳定、可控"的一条 `tool` 消息。

### 4.3 Harness 设计原则三：端到端的协作式取消

交互式 Agent 必须能随时打断，且**立即**生效。trendpower 用 1.7 节那个 `AbortSignal` 把"打断"从用户一路传到最底层：

```
用户按 Ctrl+C
  → AgentRunner.abort()          (前端)
  → agent.abort()                → AbortController.abort() → 信号触发
       ├─ 循环每步开头 signal.throw_if_aborted() → 抛 AbortError，中止循环
       ├─ _act 里 abort_task 赢得 asyncio.wait 赛跑 → 立即 throw_if_aborted()
       ├─ bash 工具注册的 add_listener(proc.kill) 回调被触发 → 杀子进程
       └─ 子 agent 的 add_listener(inner.abort) → 子 agent 循环一并停止
```

设计精髓在于**协作式**：没有任何一方被"强杀"，所有人都监听**同一个信号**，被触发时各自做优雅退出（中止循环、杀子进程、解绑监听）。1.7 节那三种用法（主动检查 / 赛跑 / 回调）在这里各司其职、汇成一条完整链路。

### 4.4 Harness 设计原则四：失败分级处理（不崩、自愈、优雅收尾）

不同的"出错"用不同态度对待，这是成熟度的体现：

- **工具出错 → 不崩，喂回模型自愈**。`_act` 的 `run_one` 用 `try/except` 把任何工具异常变成一条 `"Error: ..."` 结果（`agent/agent.py`），规整成带 `errorKind` 的结构化错误喂回模型，让它**看到错误并自我修正**，而非掀翻整个循环。
- **撞步数上限 → 不崩，软着陆**。防死循环设了 `maxSteps=100`。撞到时不报错，而是 `_emit_step_limit_summary` 注入一句"请总结进度"的提示、并把 `tools` 临时设为 `None`，让模型用现有信息交一份"做了什么 / 还差什么 / 下一步建议"的总结。
- **辅助功能（压缩）失败 → 不崩，退化继续**。压缩的总结步骤若抛错，记一条日志、`return None` 继续不压缩（`agent/compaction/compaction.py`），**绝不让辅助功能反而搞挂主任务**。

共同哲学：**辅助功能绝不连累主任务；可恢复的错变成信息喂回去让模型自愈；实在到头了优雅交卷而非崩溃。** 前端 `AgentRunner` 还在最外层再兜一层：`AbortError` 静默（用户主动取消不算错），其它异常变成一条友好的错误消息而非让界面崩。

### 4.5 Context Engineering 手段一：稳定前缀 + 提示缓存

由 3.1 知道：开头那段（工具 + 系统提示 + 项目说明）每步都被一字不差重发。对策两步：

1. **把所有不变内容堆在最前**，形成"每次一模一样的前缀"。
2. **提示缓存（prompt caching）**：告诉模型厂商"这段前缀上次发过、这次没变，复用上次的计算结果并打折"。

Anthropic 需要显式打"缓存断点"。trendpower 在三个稳定边界打标记（`community/anthropic/model_provider.py:_apply_cache_control`）：

```python
if anthropic_tools:
    anthropic_tools[-1]["cache_control"] = _EPHEMERAL   # ① 缓存整个工具清单
if anthropic_messages:
    anthropic_messages[-1]["content"][-1]["cache_control"] = _EPHEMERAL  # ③ 缓存到"对话最后一块"
# ② 系统提示的缓存标记在 _base_params 处单独打
```

- ① 缓存工具清单（整轮不变）；② 缓存系统提示（含 AGENTS.md）；③ 缓存到"对话最新一块"，让不断增长的对话也走**增量缓存**——这一轮写进缓存，下一轮命中。

> 对豆包/OpenAI 这类**自动缓存**的厂商，无需手动打断点，但"稳定前缀"原则同样有效：开头不变，它们就自动命中。这也是为什么 AGENTS.md 必须放进稳定的系统提示。

### 4.6 一个必须理解的隐藏耦合：缓存会让压缩失灵

这是整套设计里**最隐蔽、最能体现"牵一发动全身"**的地方，必须单独讲。

开启缓存后，厂商返回的 `input_tokens` **只统计未命中缓存的部分**，命中的部分单列在 `cache_read_input_tokens`。而后面 4.7 的**压缩**靠 `promptTokens` 判断"对话是不是太长了"。如果 `promptTokens` 因为缓存而"虚假地变小"，压缩就**永远不触发 → 最终撑爆上下文窗口**。

对策：统计时把缓存的 token **加回去**，保持 `promptTokens` = "这次实际发送的真实大小"（`community/anthropic/model_provider.py:_to_token_usage`，流式路径 `stream_utils.py` 同样处理，两处保持一致）：

```python
prompt_tokens = input_tokens + cache_read + cache_creation   # ★缓存部分加回来★
```

> **设计教训**：缓存（4.5）和压缩（4.7）看似无关，却通过 `promptTokens` 这个共享量耦合在一起。"远处两块通过一个共享数值纠缠"，是真实工程里最容易漏、最难查的 bug 来源。

### 4.7 Context Engineering 手段二：压缩

对话逼近阈值（默认约 10 万 token）时触发压缩（`agent/compaction/compaction.py`），策略是"保头、保尾、摘中段"：

- **保住开头**：那是任务目标，丢了就忘了在干嘛。
- **保住最近几轮**：那是"当前进行到哪了"，必须原样保留。
- **把中间一大段**交给模型**总结成一小段**，原地替换。

```python
async def before_model(params):
    messages = params["agentContext"]["messages"]
    if estimate_tokens(messages) < trigger_tokens:
        return None                              # 没到阈值，不动
    head, middle, tail = plan_compaction(messages, keep_head, keep_recent)
    summary_text = await summarizer(middle, signal)
    messages[:] = [*head, 一条装着summary的消息, *tail]   # 原地替换中段
```

两个关键细节：

**① `estimate_tokens` 取真实值与粗算的较大值**：优先用模型上次返回的真实 `promptTokens`（精确），没有就用"字符数 ÷ 4"粗算，**取两者较大值**。这样"刚发生一波大工具结果"也能立刻触发压缩，不必等下一次模型响应。（这正是 4.6 那个坑的另一端——它命脉系于 `promptTokens` 的真实性。）

**② 压缩绝不能劈开"问答对"**（最易翻车处）：3.2 节说过，`tool_use`（问）和 `tool_result`（答）必须成对存在，否则厂商拒绝整个请求。压缩要砍掉中段，万一切口正好把某对问答劈成两半（保住"问"、把"答"压进总结），就留下一个落单的半截，请求作废。`plan_compaction` 因此调整切口，保证头不结束在 `tool_use`、尾不起始于孤儿 `tool` 消息：

```python
while head_end > 0 and _has_tool_use(messages[head_end - 1]):
    head_end -= 1                                # 头不能停在"问"上（它的"答"会被压走）
while tail_start < n and messages[tail_start]["role"] == "tool":
    tail_start += 1                              # 尾不能从孤儿"答"开始（它的"问"被压走了）
```

### 4.8 Context Engineering 手段三：工具结果裁剪

并非所有工具结果都同等重要。`agent/tool_result/policy.py` 为每类工具定义裁剪策略：列目录只留摘要、读文件可以留多一些、子 agent 报告（`task`）`preferSummaryOnly` 且 `maxStringLength` 8000。这本质是**控制每条观测占用多少上下文**——直接缓解"会乱"和"有上限"两重压力。它和压缩是同一件事的两个侧面：压缩是**事后**缩，裁剪是**入场前**就控好每条的大小。

### 4.9 Context Engineering 手段四：子 Agent 隔离

压缩是"噪音已经堆上桌了再补救"。更彻底的办法是**根本不让噪音上主桌**：把"在整个项目里查清楚某功能怎么实现"这类会翻几十个文件、产生大量中间噪音的脏活，**派给一个独立的子 Agent** 去做，它有自己的对话和受限工具集，干完只把**一句结论**汇报回主线，中间过程主线一概看不到。

实现为一个 `task` 工具（`coding/tools/task.py`），底层复用同一套循环（`agent/subagent/runner.py:run_subagent`）。两种子 agent：`explore`（只读工具、免审批，专做查资料）和 `general`（完整工具但转发审批）。两条写死的安全红线：子 agent 工具集**永不含 `task`**（杜绝无限套娃）、也**不含 `ask_user_question`**（后台任务不能反过来弹窗问用户）。并发是白送的——`_act` 本就并行，模型一次发 3 个 `task` 就是 3 个子 agent 同时干。

> 这是"事前隔离"，和压缩的"事后补救"互补。技能系统（2.6）则是另一种上下文节流：系统提示只放"技能目录"，模型判断相关才 `read_file` 读正文——按需付费的"渐进披露"。

### 4.10 贯穿全局的三条设计纪律

最后把整套设计升华成三条纪律：

1. **分层 + 单向依赖**（第二部分）：边界划清，每块都能独立替换、独立测试、独立演进。核心不知道界面存在，所以能包成多种产品；`agent` 层不懂编程，所以能驱动任意领域。
2. **把上下文当预算经营**（第三、四部分）：上下文是有限、昂贵、承载注意力的预算，每个决策都在回答"这笔预算花得值不值"——缓存省钱、裁剪控增长、压缩兜底、隔离防污染、渐进披露按需付费。
3. **辅助功能绝不连累主任务**（4.4）：健壮性不是事后补的，是每个零件设计时就带的态度——可恢复的错喂回自愈、辅助失败就退化、到头了优雅交卷。

理解了这三条，你不只是"看懂了 trendpower"，而是能回答最根本的问题——**"换我来设计，为什么也会这么做"**：因为要看一步做一步，所以有 ReAct 循环；因为有横切行为，所以有可插拔中间件；因为模型输出不可信，所以工具有校验闸门；因为每步重发整段上下文，所以要缓存、裁剪、压缩、隔离；因为会出错会被打断，所以有取消信号和失败分级。每一个"为什么"，都是一个真实约束逼出来的合理工程决策。这就是 Harness Engineering 与 Context Engineering 的全部。

---

## 附：进一步阅读

- 完整的"启动到回答"执行追踪：[`docs/execution-flow.md`](execution-flow.md)
- 仓库与分层约定：根目录 `AGENTS.md`
- MCP 实战：[`docs/mcp.md`](mcp.md)、[`docs/mcp-playwright.md`](mcp-playwright.md)
- 源码入口：`trendpower-py/trendpower/agent/agent.py`（循环心脏）、`trendpower-py/trendpower/foundation/`（基本粒子）、`trendpower-py/trendpower/coding/agents/lead_agent.py`（组装现场）
