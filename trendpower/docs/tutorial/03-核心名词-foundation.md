# 第 3 课 · 核心名词（foundation 层）

主干道看完了，现在认识在它上面**流动的"基本粒子"**。这一课全是名词、不讲动作——就像学一门语言先背单词，后面才造句。

这些名词都住在最底层 `trendpower-py/trendpower/foundation/`。

---

## 一、Message：对话的"唯一真相"

### 设计：整个系统只有一种"对话"

一段 agent 对话，本质就是**一串消息**：你说的、模型说的、工具返回的，依次排开。trendpower 做了一个关键决定：

> **全系统只用一种消息类型 `Message`，它是"对话真相的唯一来源"。** 从你输入、到喂给模型、到存盘、到界面渲染，流动的都是同一种东西。

**为什么这样**：如果界面一种格式、模型一种格式、存盘又一种格式，转换来转换去到处是 bug。统一成一种，谁要用就在自己的边界上翻译一下（比如发给 Anthropic 前翻译成它的格式），内部永远干净。

### 代码：四种角色的消息

```python
# foundation/messages.py
class UserMessage(TypedDict):        # 你说的
    role: Literal["user"]
    content: UserMessageContent

class AssistantMessage(TypedDict, total=False):   # 模型说的
    role: Literal["assistant"]
    content: AssistantMessageContent              # 可能含文字、思考、工具调用
    usage: TokenUsage                             # 用了多少 token
    streaming: bool                               # 是否还在流式传输中

class ToolMessage(TypedDict):        # 工具返回的
    role: Literal["tool"]
    content: ToolMessageContent

class SystemMessage(TypedDict):      # 给模型的"总规矩"
    role: Literal["system"]
    content: SystemMessageContent
```

注意它们都是 **`TypedDict`**（第 1 课 A4）——本质是普通字典，零成本，只是标注了"该有哪些键"。

一条消息的 `content` 不是一段纯文字，而是**一串"块"**。块有几种类型：
- `text`（文字）、`thinking`（模型的思考过程）、
- `tool_use`（模型要求"调用某工具，参数是…"）、
- `tool_result`（工具返回的结果）。

**理解这个"块"很重要**：模型"想调工具"这件事，就是它在 `AssistantMessage` 里吐出一个 `tool_use` 块；工具跑完，结果就成为一个 `tool_result` 块装进 `ToolMessage`。第 4 课的循环就是围着这两种块转。

> 还有个 `NonSystemMessage` = user/assistant/tool 三种的合集（即"除了系统提示之外的对话"），后面常见到这个词。

---

## 二、Model 与 ModelProvider：大脑 + 插座转换头

### 设计：把"哪个模型"和"怎么跟它对话"分开

- **`Model`**：代表"我要用的那个模型"——它有名字（如 `claude-opus-4-8`）、一个 provider、和一些选项（温度等）。
- **`ModelProvider`**：真正"怎么跟某家 API 对话"的适配器。

**为什么分开**：今天用 Anthropic、明天换豆包，换的只是 provider 这个"插座转换头"，上层的 `Model` 用法不变（第 1 课 A5 的 Protocol 比喻）。

### 代码：Provider 是个"长得像就行"的 Protocol

```python
# foundation/models.py
class ModelProvider(Protocol):
    async def invoke(self, params) -> AssistantMessage: ...       # 要一次完整回答
    def stream(self, params) -> AsyncGenerator[AssistantMessage, None]: ...  # 流式边收边吐
```

任何对象，只要有这两个方法，就能当 provider 用——不需要继承任何基类。所以 `community/openai/` 和 `community/anthropic/` 各写一个就行（第 7 课细看）。

`Model` 自己很薄，它只做一件事：把内部统一的 `Message[]` 组装成 provider 要的请求，**并把系统提示作为一条 `system` 消息放到最前面**：

```python
# foundation/models.py:Model._build_provider_params（简化）
messages = []
if prompt:                                   # 系统提示（总规矩）
    messages.append({"role": "system", "content": [{"type": "text", "text": prompt}]})
messages.extend(context.get("messages"))     # 再接上整段对话
```

> 记住这段——第 7 课讲"为什么每步都要重发整段对话"时，就是从这里开始的。

---

## 三、Tool：模型伸向世界的"手"

### 设计：工具 = 一个有名字、有参数说明、能被调用的功能

模型本身只会输出文字。"读文件"对它来说，是输出一个 `tool_use` 块说"我要调用 `read_file`，参数 path=…"。trendpower 收到后真正去读，把内容作为 `tool_result` 递回去。**工具就是大脑和真实世界之间的传话筒。**

### 代码：FunctionTool 的形状

```python
# foundation/tools.py
@dataclass
class FunctionTool:
    name: str                 # 工具名，模型靠它指名调用
    description: str          # 给模型看的"这个工具干嘛、怎么用"
    parameters: Type[BaseModel]   # 参数的形状（pydantic，能校验！）
    invoke: Callable          # 真正执行的函数
    raw_input_schema: ... = None  # 逃生舱，MCP 工具用（第7课）
```

三个要点：
1. **`description` 是写给模型读的。** 工具好不好用，一半看这段描述写得清不清楚——它是你对模型的"说明书"。
2. **`parameters` 用 pydantic**（第 1 课 A4）——因为参数是模型生成的、不可信，必须能在运行时校验。
3. **`invoke`** 是真正干活的异步函数。

### 结构化结果：工具怎么"汇报"

工具返回的不是裸字符串，而是一个约定好的结构：

```python
# foundation/tools.py
class StructuredToolSuccess(TypedDict):   # 成功
    ok: bool        # True
    summary: str    # 一句话摘要（给模型读）
    data: Any       # 详细数据（可选）

class StructuredToolError(TypedDict):     # 失败
    ok: bool        # False
    summary: str
    error: str
    code: str       # 错误码，如 "FILE_NOT_FOUND"
```

**为什么不用裸字符串**：这是"手脚"和"大脑"之间的**通信协议**。`summary` 给模型读、`data` 给程序用、`code` 让模型一眼看出"哦是文件没找到"从而决定下一步。比甩一坨乱七八糟的报错可控得多。第 5、6 课会看到这套结果怎么被裁剪、喂回。

---

## 四、AbortSignal：全局急停按钮（先混脸熟）

最后一个名词，先认识、第 8 课细讲。

### 设计：一个能"按下去"的全局停止信号

交互式 agent 必须能被随时打断。`AbortSignal`（中止信号）就是那个红色急停按钮——按下后，正在跑的工具（比如一个 bash 子进程）会被通知"停"。

### 代码：信号 + 按钮

```python
# foundation/abort_signal.py
class AbortSignal:        # 信号本身：能查"按了没"、能 await 等它被按
    @property
    def aborted(self) -> bool: ...
    async def wait(self): ...                 # 一直等到被按下（第1课A2的Event）
    def add_listener(self, cb): ...           # 注册"被按下时执行的回调"

class AbortController:    # 配套的"按钮"
    def abort(self): ...                      # 按下去
```

用法预告：循环持有一个按钮，工具拿到信号；用户 Ctrl+C → 按钮按下 → 信号触发 → 工具的 `add_listener` 回调被调、子进程被 kill。`AbortError` 是被中止时抛的专属异常（第 1 课 A7）。

---

## 五、本课小结

| 名词 | 一句话 | 文件 |
|---|---|---|
| **Message** | 对话的唯一真相，一串带"块"的消息 | `foundation/messages.py` |
| **Model** | "我要用哪个模型" | `foundation/models.py` |
| **ModelProvider** | "怎么跟这家 API 对话"的插座转换头（Protocol） | `foundation/models.py` |
| **Tool** | 模型的手，含名字/说明书/pydantic参数/执行函数 | `foundation/tools.py` |
| **结构化结果** | 工具汇报的协议：ok/summary/data/code | `foundation/tools.py` |
| **AbortSignal** | 全局急停按钮 | `foundation/abort_signal.py` |

单词背完了。下一课进入**发动机本身**——把这些名词组装起来"动"起来的 ReAct 循环。

👉 下一课：[04 · ReAct 循环（心脏）](04-react循环-心脏.md)
