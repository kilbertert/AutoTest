# 第 1 课 · Python 基础（只讲 trendpower 用得到的）

这一课把 trendpower 代码里反复出现、但初学者容易卡住的几个 Python 机制讲清楚。**不求把 Python 讲全，只讲够你看懂 trendpower。**

每个概念都三步：**大白话 → 能跑的小例子 → 它在 trendpower 哪里用到**。

> 全教程的代码引用相对于 `trendpower-py/trendpower/`。

---

## A1 · 同步 vs 异步：为什么 agent 必须"异步"

### 大白话

一个 agent 大部分时间在**干等**：等模型回话（几秒）、等命令跑完、等文件读完。

- **同步**（普通写法）：等的时候，整个程序**卡住**，啥也干不了。
- **异步**（async）：等的时候，**让出去**，让程序去干别的，等好了再回来接着干。

打个比方：**烧水的时候你不会站在炉子前盯着**，你会去切菜——水开了再回来。异步就是这种"边等边干别的"的能力。

### 小例子

```python
import asyncio

async def boil_water():           # async def = 这是个"可以中途让出去"的函数
    await asyncio.sleep(3)        # await = 这里要等3秒，但别傻等，先让出去
    return "水开了"

async def main():
    result = await boil_water()   # await 一个异步函数 = 等它出结果
    print(result)

asyncio.run(main())               # 启动异步世界的入口
```

两个关键词：
- **`async def`**：声明一个异步函数（业内叫"协程"）。它和普通函数最大的区别是——它可以在 `await` 处**暂停、让出控制权**。
- **`await`**：意思是"这一步要等结果，等的期间把 CPU 让给别人"。**只能在 `async def` 里用。**

### 在 trendpower 哪里用到

几乎到处都是。最核心的是模型调用——它要发网络请求等模型回话，天然是异步的：

```python
# foundation/models.py
async def invoke(self, context):              # async
    params = self._build_provider_params(context)
    return await self.provider.invoke(params)  # await 等模型回话
```

整条 agent 主链路（`agent/agent.py:Agent.stream`）从头到尾都是 async，因为它一路都在"等模型、等工具"。

---

## A2 · asyncio 的几件武器

异步不只是"边等边干别的"，还能"**同时干好几件事**"。trendpower 用到这几件武器：

### 1）`create_task`：同时开跑多件事

```python
async def fetch(name):
    await asyncio.sleep(1)
    return f"{name} 拿到了"

async def main():
    # 三个任务"同时"开跑，不是排队
    t1 = asyncio.create_task(fetch("A"))
    t2 = asyncio.create_task(fetch("B"))
    print(await t1, await t2)   # 总共约1秒，而不是2秒

asyncio.run(main())
```

`create_task` 把一个协程"丢出去后台跑"，立刻返回一个 task 句柄，之后 `await` 它拿结果。

### 2）`asyncio.wait(..., FIRST_COMPLETED)`：谁先好用谁

等一组任务，**只要有一个先完成就立刻返回**（而不是等全部）。trendpower 用它做"工具执行"和"急停信号"的赛跑——任一个先到就先处理。

### 3）`asyncio.Event`：等一个"信号"

一个可以被"按下"的开关，别处可以 `await event.wait()` 一直等到它被按下。trendpower 的"急停按钮"就是用它做的。

### 4）`create_subprocess_exec`：跑外部命令

异步地启动一个外部进程（比如执行一条 shell 命令），等它的输出。

### 在 trendpower 哪里用到

`agent/agent.py:_act`（执行工具的那段）把上面几件武器全用上了——它给每个工具调用 `create_task` 并发跑，同时起一个"急停任务"，用 `wait(FIRST_COMPLETED)` 让它们赛跑：

```python
# agent/agent.py:_act（简化）
tasks = [asyncio.create_task(run_one(i, tu)) for i, tu in enumerate(tool_uses)]  # 并发
abort_task = asyncio.create_task(signal.wait())                                  # 急停
done, _ = await asyncio.wait({*tasks, abort_task}, return_when=asyncio.FIRST_COMPLETED)
```

跑命令的 `bash` 工具用 `create_subprocess_exec`（`coding/tools/bash.py`）。急停按钮用 `asyncio.Event`（`foundation/abort_signal.py`）。

---

## A3 · 生成器与 `yield`（trendpower 流式的灵魂）⭐

这一节最重要——理解了它，才能理解 trendpower 为什么能"实时显示进度"。

### 大白话：生成器 = "挤牙膏"的函数

普通函数 `return` 一次就结束了。**生成器**用 `yield` **吐一个值就暂停**，等你来要下一个，它再接着跑、再吐一个。

```python
def count_to(n):
    for i in range(1, n + 1):
        yield i          # 吐一个 i，然后"暂停"在这儿
        # 下次要值时，从这里继续

for x in count_to(3):    # 用 for 一个个取
    print(x)             # 1  2  3
```

为什么有用：它**一边产、你一边用**，不用等全部算完。想象一个"边榨边喝"的榨汁机，而不是"榨满一大桶再端给你"。

### 异步生成器：`async def` + `yield` + `async for`

把生成器和异步合体——每吐一个值之前还能 `await`（等点什么）：

```python
import asyncio

async def ticker(n):
    for i in range(n):
        await asyncio.sleep(1)   # 等1秒
        yield i                  # 吐一个

async def main():
    async for t in ticker(3):    # 注意是 async for
        print("收到", t)         # 每隔1秒打印一个

asyncio.run(main())
```

### 在 trendpower 哪里用到

**这就是 trendpower 的心脏形态。** `Agent.stream` 是个异步生成器，它一边推进 agent 循环、一边 `yield` 事件（"正在思考""跑了某工具""助手回复了"），界面那头用 `async for` 实时接住、实时渲染：

```python
# agent/agent.py:Agent.stream（简化）
async def stream(self, message):
    ...
    for step in range(1, self.options.maxSteps + 1):
        async for ev in self._think():     # 想（内部也是异步生成器）
            yield ev                        # 把进度事件吐给界面
        ...
        async for ev in self._act(tool_uses):
            yield ev                        # 把工具结果吐给界面
```

界面侧（`trendpower-tui/.../tui/agent_runner.py`）就是 `async for event in self.agent.stream(...)` 一个个接。

> 一个进阶细节先混脸熟：`_think` 在吐完进度后，用一个**哨兵值** `{"type": "_think_done", "message": ...}` 把"最终的完整消息"传回给调用方。这是"异步生成器既要吐过程、又要返回最终结果"的常见技巧，第 04 课会细讲。

---

## A4 · 描述"数据长什么样"的三种方式

trendpower 里描述数据结构用了**三种**工具，各有分工。初学者常困惑"为什么不统一"，这里讲清楚。

### 1）`TypedDict`：给字典定个"形状"（零成本）

它本质还是个普通字典，只是**告诉编辑器/类型检查器"这个字典应该有哪些键、什么类型"**，运行时不做任何检查、没有额外开销。

```python
from typing import TypedDict

class TokenUsage(TypedDict):
    promptTokens: int
    completionTokens: int
    totalTokens: int

u: TokenUsage = {"promptTokens": 100, "completionTokens": 20, "totalTokens": 120}
```

### 2）`dataclass`：轻量的类（装配置/结果）

自动帮你生成 `__init__` 等样板，适合"一小撮带名字的字段"。

```python
from dataclasses import dataclass

@dataclass
class AgentOptions:
    maxSteps: int = 100

opts = AgentOptions()          # maxSteps 默认 100
opts2 = AgentOptions(maxSteps=30)
```

### 3）`pydantic` 的 `BaseModel`：带**运行时校验**

最重的一种，但它会**在运行时真的检查数据对不对**，类型不符还能自动转换或报错。专门用来对付"不可信的输入"。

```python
from pydantic import BaseModel, Field

class ReadFileParams(BaseModel):
    path: str = Field(description="要读的文件的绝对路径")

ReadFileParams.model_validate({"path": "/tmp/a.txt"})   # ✅ 通过
ReadFileParams.model_validate({})                       # ❌ 缺 path，抛错
```

### 为什么 trendpower 三种都用（关键）

| 用哪个 | 用在哪 | 为什么 |
|---|---|---|
| `TypedDict` | **对话消息** Message（`foundation/messages.py`） | 消息海量流动，要零成本、又要类型提示 |
| `dataclass` | 配置/结果，如 `AgentOptions`、`FunctionTool`、`SubagentResult` | 轻量、带默认值、够用 |
| `pydantic` | **工具的参数**，如 `read_file.py:_ReadFileParams` | 参数是**模型生成的、不可信**，必须运行时校验（A6/第05课会接着讲） |

一句话：**信得过的内部数据用轻的（TypedDict/dataclass），信不过的外部输入用重的（pydantic）。**

---

## A5 · 鸭子类型 / Protocol / SimpleNamespace

### 大白话："长得像就算数"

Python 有句老话："**如果它走起来像鸭子、叫起来像鸭子，那它就是鸭子。**" 意思是——不在乎你**是不是**某个类，只在乎你**有没有**需要的那几个方法/属性。

### `Protocol`：只规定"要有哪些方法"，不要求继承

```python
from typing import Protocol

class Greeter(Protocol):
    def hello(self) -> str: ...      # 只要求：有个 hello() 方法

class Cat:                            # 没有继承 Greeter
    def hello(self): return "喵"

def greet(g: Greeter):                # 接受任何"长得像 Greeter"的东西
    print(g.hello())

greet(Cat())                          # ✅ 可以，因为 Cat 有 hello()
```

### `SimpleNamespace`：临时拼一个"有指定属性的对象"

不用专门定义一个类，就地造一个带属性的对象：

```python
from types import SimpleNamespace

obj = SimpleNamespace(name="A", run=lambda: print("跑"))
print(obj.name)   # A
obj.run()         # 跑
```

### 在 trendpower 哪里用到

- **`ModelProvider` 是个 Protocol**（`foundation/models.py`）：只要求一个对象有 `invoke` 和 `stream` 两个方法，就能当模型适配器用。所以接豆包/OpenAI/Anthropic，各写一个"长得像"的类即可，不用继承任何基类。
- **中间件是 `SimpleNamespace`**：每个中间件工厂就地拼一个带钩子的对象返回，比如压缩中间件结尾：
  ```python
  # agent/compaction/compaction.py 结尾
  return SimpleNamespace(beforeModel=before_model)   # 拼一个有 beforeModel 的对象
  ```
  而循环那头靠 `getattr(mw, "beforeModel", None)` **按名字找钩子**——有就调、没有就跳过。这就是鸭子类型：中间件"有哪个钩子"就参与哪个时点。

---

## A6 · 闭包与工厂函数

### 大白话："带记忆的函数"

一个函数里面再定义一个函数并把它返回，**里层函数会"记住"外层的变量**。外层就像一个"工厂"，按你给的配置，生产一个定制好的函数。

```python
def make_adder(n):           # 工厂：吃一个 n
    def add(x):              # 产品：里层函数
        return x + n         # 记住了外层的 n
    return add               # 把产品返回

add5 = make_adder(5)         # 造一个"加5"的函数
print(add5(10))              # 15  —— 它记住了 n=5
```

### 在 trendpower 哪里用到

trendpower 满屏的 `create_*` 都是这个套路——外层吃配置，返回一个记住了配置的内层函数：

```python
# coding/tools/task.py:create_task_tool（极简示意）
def create_task_tool(*, model, cwd, base_tools, ...):
    async def _invoke(params, signal=None):
        # 这里能直接用到 model / cwd / base_tools —— 被"记住"了
        ...
    return define_tool(name="task", ..., invoke=_invoke)
```

`create_compaction_middleware`、`create_skills_middleware`、`define_tool` 全是这个形态。好处：**配置在"造"的时候定好，用的时候随手就有，不用每次传一大堆参数。**

---

## A7 · 文件、清理、异常

### 1）`pathlib`：优雅地拼路径

```python
from pathlib import Path
p = Path("/tmp") / "logs" / "a.txt"   # 用 / 拼，跨平台
if p.exists():
    text = p.read_text(encoding="utf-8")
```

trendpower 的文件工具（如 `coding/tools/read_file.py`）都用 `pathlib`；异步读写大文件时用 `aiofiles`（pathlib 的异步版搭档）。

### 2）`try / finally`：无论如何都要清理

`finally` 里的代码，**不管前面是正常结束还是出错，都一定会执行**。专门用来"善后"——关文件、解绑监听、取消任务。

```python
def work():
    resource = open_something()
    try:
        do_stuff(resource)
    finally:
        resource.close()      # 哪怕 do_stuff 抛错，也保证关掉
```

trendpower 里到处是这种善后，比如 `agent/agent.py:_act` 结尾 `finally: abort_task.cancel()`（取消急停任务），`coding/tools/bash.py` 的 `finally: remove_listener()`（解绑急停监听）。

### 3）自定义异常

异常就是"出事了"的信号，可以自己定义一种专属的：

```python
class AbortError(Exception):     # 一种专门表示"被中止"的异常
    pass
```

trendpower 的 `foundation/abort_signal.py:AbortError` 就是这个——任务被用户取消时，就抛它，让上层能专门识别"哦，是被主动中止的，不是真出错"。

### 4）`from __future__ import annotations`

你会看到几乎每个文件开头都有这一行。它的作用（对初学者）：**让类型注解可以"超前引用"**还没定义的名字，并略微提速。**看到它知道是个技术性开关即可，不影响理解逻辑。**

---

## 本课小结

| 概念 | 一句话 | trendpower 用处 |
|---|---|---|
| async/await | 边等边干别的 | 整条主链路 |
| asyncio 武器 | 同时干多件事 + 赛跑 + 急停 + 跑命令 | `_act` 并发、bash、取消 |
| 生成器/yield ⭐ | 挤牙膏式"边产边用" | `Agent.stream` 实时吐事件 |
| TypedDict/dataclass/pydantic | 轻/中/重三种描述数据 | 消息 / 配置 / 工具参数校验 |
| Protocol/SimpleNamespace | "长得像就算数" | provider 适配、中间件 |
| 闭包/工厂 | "带记忆的函数" | 所有 `create_*` |
| pathlib/try-finally/异常 | 路径、善后、出事信号 | 文件工具、取消、收尾 |

这些就是后面读 trendpower 代码会反复撞见的全部"语法地基"。地基打好了，下一课我们就**站在高处俯瞰整个 trendpower**，再顺着一次提问走一遍主干道。

👉 下一课：[02 · 鸟瞰与全景路径](02-鸟瞰与全景路径.md)
