# trendpower TUI 迁移指南：Ink/React → Textual

把 `src/cli/*`（TypeScript + Ink + React）移植到 `trendpower_tui/*`（Python + Textual）的完整步骤。

---

## 0. 核心思路

| | TS 前端 | Python 前端（要做的） |
|---|---|---|
| 框架 | **Ink**（React 跑在终端）| **Textual**（Python 原生 TUI） |
| 编程范式 | JSX + Hooks | Widget 类 + reactive 属性 |
| 样式 | Ink 的 props（borderColor、flexDirection 等）| Textual CSS（`.tcss` 文件）|
| Markdown | `ink-markdown` + `marked-terminal` | Textual 内置 `Markdown` 控件 |
| 异步事件 | React `useEffect` + AsyncGenerator | `asyncio` + `@work` 装饰器 |
| 状态共享 | React Context | Textual 的 reactive 属性 / messages |
| CLI 子命令 | `commander` | `click` |

**重要**：你的核心 agent loop（`trendpower-py`）**完全不动**。这里只是写一个新的"壳"消费它的事件流。

---

## 1. 目录结构对应

整体一一对应，TS 的 `.tsx` 文件大致对应 Python 的一个或多个 `.py` 文件：

```
src/cli/                              trendpower_tui/
├── index.tsx                         ├── __main__.py
├── version.ts                        ├── version.py
│
├── bootstrap/                        ├── bootstrap/
│   ├── integrity.ts                  │   ├── integrity.py
│   ├── first-run-wizard.tsx          │   ├── first_run_wizard.py
│   └── model-wizard.tsx              │   └── model_wizard.py
│
├── commands/                         ├── commands/
│   └── config/                       │   └── config/
│       └── model/                    │       └── model/
│           ├── add.ts                │           ├── add.py
│           ├── list.ts               │           ├── list.py
│           ├── remove.ts             │           ├── remove.py
│           ├── set-default.ts        │           ├── set_default.py
│           └── prompt-select-...     │           └── prompt_select_model.py
│
├── config/                           ├── config/
│   ├── schema.ts                     │   └── schema.py
│
├── settings/                         ├── settings/
│   ├── settings.ts                   │   ├── settings.py
│   ├── settings-loader.ts            │   ├── settings_loader.py
│   └── settings-writer.ts            │   └── settings_writer.py
│
├── model-providers.ts                ├── model_providers.py
│
└── tui/                              └── tui/
    ├── app.tsx                           ├── app.py                  (主 App 类)
    ├── index.ts                          ├── __init__.py
    ├── command-registry.ts               ├── command_registry.py
    ├── message-text.ts                   ├── message_text.py
    ├── todo-view.ts                      ├── todo_view.py
    ├── token-usage.ts                    ├── token_usage.py
    ├── input-editor.ts                   ├── input_editor.py
    ├── themes/                           ├── theme.tcss              (CSS 替代)
    │
    ├── hooks/                            ├── agent_runner.py         (合并 hooks)
    │   ├── use-agent-loop.ts             │   (核心：跑 agent.stream → 投递 Textual messages)
    │   ├── use-approval-manager.ts       │
    │   ├── use-ask-user-question-...     │
    │   ├── use-command-input.ts          │
    │   ├── use-input-history.ts          │
    │   └── use-animation-frame.ts        │
    │
    └── components/                       └── widgets/
        ├── header.tsx                        ├── header.py
        ├── footer.tsx                        ├── footer.py
        ├── input-box.tsx                     ├── input_box.py
        ├── highlighted-input.tsx             ├── highlighted_input.py
        ├── command-list.tsx                  ├── command_list.py
        ├── message-history.tsx               ├── message_history.py
        ├── streaming-indicator.tsx           ├── streaming_indicator.py
        ├── todo-panel.tsx                    ├── todo_panel.py
        ├── approval-prompt.tsx               ├── approval_prompt.py
        ├── ask-user-question-prompt.tsx      ├── ask_user_question_prompt.py
        └── markdown.tsx                      └── markdown_view.py
```

**重大概念变化**：TS 的 `hooks/` 目录在 Python 版被**折叠**成一个 `agent_runner.py`，因为 Textual 不用 hooks 模式——逻辑直接挂在 App / Widget 类的方法上。

---

## 2. Ink → Textual 概念翻译表

记住下面这张表，写代码时反复对照：

| Ink / React | Textual | 备注 |
|---|---|---|
| `<Box flexDirection="column">` | `Vertical` 容器 / CSS `layout: vertical` | Textual 用容器组件 + CSS |
| `<Text>...</Text>` | `Static("...")` 或 `Label("...")` | |
| `useState` | `reactive(initial_value)` 类属性 | 改值会自动重渲染 |
| `useEffect` | `on_mount()` / `watch_<name>()` 方法 | 监听某个 reactive 变更 |
| `useMemo` | 直接 Python 属性 + `@property` | 没必要缓存得太狠 |
| `useContext` | App 单例 `self.app`，或自定义 message 总线 | |
| Event listener / onSubmit | `on_input_submitted(self, event)` 等 | 命名约定 `on_<event>` |
| `useStdout().write` | `self.write(...)`（在 RichLog 或 ScrollView 里） | |
| `process.exit(0)` | `self.app.exit()` | |
| Ink JSX 子组件 | `compose()` 方法 `yield` 子 widget | |
| 重新渲染 | reactive 自动 / `self.refresh()` 手动 | |
| `useInput((input, key) => ...)` | `on_key(self, event)` | |
| AsyncGenerator 消费 | `@work(thread=False)` 装饰的 async 方法 | |
| React Context Provider | App 实例本身（widget 用 `self.app.<attr>`） | |

---

## 3. 推荐迁移顺序（10 阶段）

每个阶段都能跑——不要一次性写完所有东西再调。

### 阶段 1：最小可运行 Hello World（30 分钟）

目标：`trendpower` 命令能启动一个空 Textual 窗口，按 Ctrl+C 退出。

```python
# trendpower_tui/__main__.py
from trendpower_tui.app import trendpowerApp

def main() -> None:
    trendpowerApp().run()

if __name__ == "__main__":
    main()
```

```python
# trendpower_tui/app.py
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static

class trendpowerApp(App):
    CSS_PATH = "tui/theme.tcss"
    BINDINGS = [("ctrl+c", "quit", "Quit")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("hello, trendpower")
        yield Footer()
```

```css
/* trendpower_tui/tui/theme.tcss */
Screen { background: $surface; }
```

跑：`pip install textual && python -m trendpower_tui`

---

### 阶段 2：Config + Settings 持久化层（1-2 小时）

把 `src/cli/config/schema.ts` 和 `src/cli/settings/*` 翻成 Python。这一层**纯逻辑、没 UI**，最简单也最该先做。

- `config/schema.py` — 用 `pydantic` 定义 model 配置 schema
- `settings/settings_loader.py` — 读 `~/.trendpower/settings.json` + `<cwd>/.trendpower/settings.json`
- `settings/settings_writer.py` — 原子写入（写临时文件 + rename）

参考点：TS 用 Bun 的文件 API，Python 直接用 `pathlib + json`。注意 `loadAllowList` / `appendAllowedTool` 这两个接口是给 `trendpower-py` 的 `ApprovalPersistence` Protocol 用的——确保签名一致。

测试：写一个小脚本读你现有的 `~/.trendpower/settings.json`，看能不能正常 parse。

---

### 阶段 3：CLI 子命令（`trendpower config model add` 等）（1-2 小时）

TS 用 `commander`，Python 用 **`click`**：

```python
# trendpower_tui/commands/__init__.py
import click

@click.group()
def cli():
    pass

@cli.group()
def config():
    pass

@config.group()
def model():
    pass

@model.command()
@click.option("--name", required=True)
@click.option("--provider", type=click.Choice(["openai", "anthropic"]))
@click.option("--base-url")
@click.option("--api-key")
def add(name: str, provider: str, base_url: str, api_key: str) -> None:
    """Add a model entry to the config."""
    # ... 调用 config_writer
```

集成到 `__main__.py`：

```python
def main():
    import sys
    if len(sys.argv) > 1:
        from trendpower_tui.commands import cli
        cli()
    else:
        # 无参数 → 启动 TUI
        from trendpower_tui.app import trendpowerApp
        trendpowerApp().run()
```

---

### 阶段 4：核心 `AgentRunner`（最关键，2-3 小时）

这一层取代 TS 的 `useAgentLoop` hook。它是**整个 TUI 的心脏**。

```python
# trendpower_tui/tui/agent_runner.py
import asyncio
from textual.message import Message
from textual.worker import Worker

from trendpower.agent import Agent

class AgentMessageEvent(Message):
    """Posted to the App when the agent produces a new transcript message."""
    def __init__(self, message) -> None:
        self.payload = message
        super().__init__()

class StreamingChanged(Message):
    def __init__(self, streaming: bool) -> None:
        self.streaming = streaming
        super().__init__()

class AgentRunner:
    """Owns the agent + bridges agent events into Textual messages."""

    def __init__(self, agent: Agent, target) -> None:
        self.agent = agent
        self.target = target   # The App or Widget that receives messages.
        self._current_worker: Worker | None = None

    async def submit(self, text: str, requested_skill: str | None = None) -> None:
        user_msg = {"role": "user", "content": [{"type": "text", "text": text}]}
        self.target.post_message(AgentMessageEvent(user_msg))
        self.agent.set_requested_skill_name(requested_skill)

        self.target.post_message(StreamingChanged(True))
        try:
            async for event in self.agent.stream(user_msg):
                if event["type"] == "message":
                    self.target.post_message(AgentMessageEvent(event["message"]))
                # progress events: 可以忽略（TS 也是忽略），或用来驱动 streaming indicator
        except Exception as e:
            self.target.post_message(AgentMessageEvent({
                "role": "assistant",
                "content": [{"type": "text", "text": f"Error: {e}"}],
            }))
        finally:
            self.target.post_message(StreamingChanged(False))

    def abort(self) -> None:
        self.agent.abort()
```

在 App 里启动它（**关键**：用 `@work` 把它跑在 worker 里，不阻塞 UI）：

```python
# trendpower_tui/app.py
class trendpowerApp(App):
    messages: reactive[list] = reactive(list, layout=True)
    streaming: reactive[bool] = reactive(False)

    def __init__(self, agent):
        super().__init__()
        self.runner = AgentRunner(agent, target=self)

    @work(exclusive=True)
    async def submit_user_text(self, text: str) -> None:
        await self.runner.submit(text)

    def on_agent_message_event(self, event: AgentMessageEvent) -> None:
        self.messages = [*self.messages, event.payload]

    def on_streaming_changed(self, event: StreamingChanged) -> None:
        self.streaming = event.streaming
```

---

### 阶段 5：MessageHistory widget（2 小时）

把 `src/cli/tui/components/message-history.tsx` 的渲染逻辑搬过来。建议用 `RichLog` 作为容器，每条 message 追加一段渲染好的 Rich `Text` 或 `Panel`。

要点：
- 复用你已经在 `trendpower-py/trendpower/agent/tool_result/summary.py` 写的 `summarize_tool_result_text()`
- Markdown 内容用 Textual 的 `Markdown` widget 或 Rich 的 `Markdown` 对象

```python
# trendpower_tui/widgets/message_history.py
from textual.widgets import RichLog
from rich.text import Text
from rich.markdown import Markdown

from trendpower.agent.tool_result import summarize_tool_result_text

class MessageHistory(RichLog):
    def append_message(self, message: dict) -> None:
        role = message["role"]
        for part in message["content"]:
            if part["type"] == "text":
                if role == "assistant":
                    self.write(Markdown(part["text"]))
                else:
                    self.write(Text(part["text"]))
            elif part["type"] == "tool_use":
                self.write(Text(f"⏺ {part['name']}({_short(part['input'])})", style="dim cyan"))
            elif part["type"] == "tool_result":
                summary = summarize_tool_result_text(part["content"])
                self.write(Text(f"  └ {summary or part['content'][:120]}", style="dim"))
            elif part["type"] == "thinking":
                self.write(Text(f"(thinking) {part['thinking'][:200]}", style="dim italic"))
```

参考点：TS 的 `MessageHistoryItem` 用了 `todoSnapshots` 来给 `todo_write` 工具调用特殊处理，Python 版同样需要——把 `todo_view.py` 端口过来就行。

---

### 阶段 6：InputBox + 斜杠命令（2 小时）

替代 `input-box.tsx` + `use-command-input.ts`：

```python
# trendpower_tui/widgets/input_box.py
from textual.widgets import Input
from textual.message import Message

class CommandSubmitted(Message):
    def __init__(self, text: str, requested_skill: str | None) -> None:
        self.text = text
        self.requested_skill = requested_skill
        super().__init__()

class InputBox(Input):
    def __init__(self, commands: list) -> None:
        super().__init__(placeholder="输入消息或 /command...")
        self.commands = commands

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value
        # 解析斜杠命令 (移植 command-registry.ts 的 resolveBuiltinCommand)
        ...
        self.post_message(CommandSubmitted(text=text, requested_skill=None))
        self.value = ""
```

历史记录（↑/↓ 翻历史）：用 Textual 的 `on_key` 监听 Up/Down + 自己维护一个 deque。这部分是 `use-input-history.ts` 的对应物。

---

### 阶段 7：StreamingIndicator + TodoPanel + Footer + Header（1-2 小时）

这些都是"显示型"widget，依赖 App 的 reactive 状态，不太复杂。模式都是：

```python
# trendpower_tui/widgets/streaming_indicator.py
from textual.widgets import Static
from textual.reactive import reactive

class StreamingIndicator(Static):
    streaming: reactive[bool] = reactive(False)
    next_todo: reactive[str | None] = reactive(None)

    def watch_streaming(self, value: bool) -> None:
        if value:
            self.update(f"⠋ Thinking... {self.next_todo or ''}")
        else:
            self.update("")

    def watch_next_todo(self, value: str | None) -> None:
        if self.streaming:
            self.update(f"⠋ Thinking... {value or ''}")
```

App 里用 `self.query_one(StreamingIndicator).streaming = True` 推数据。或者更解耦，用 message 总线。

---

### 阶段 8：ApprovalPrompt + AskUserQuestionPrompt（2-3 小时，最复杂的两个 widget）

这两个是**模态对话框**，会阻塞 agent 工具执行。Textual 的解法：

1. 用 `ModalScreen` 弹出，在弹窗里收用户选择
2. 通过 `asyncio.Future` 把结果传回 `ApprovalManager` / `AskUserQuestionManager`（你已经在 `trendpower-py` 写好了）

```python
# trendpower_tui/widgets/approval_prompt.py
from textual.screen import ModalScreen
from textual.containers import Vertical
from textual.widgets import Button, Label

class ApprovalScreen(ModalScreen[str]):  # 返回 "deny" / "allow_once" / "allow_always_project"
    def __init__(self, tool_use: dict) -> None:
        super().__init__()
        self.tool_use = tool_use

    def compose(self):
        yield Vertical(
            Label(f"Tool {self.tool_use['name']} wants to run:"),
            Label(str(self.tool_use["input"])),
            Button("Allow once", id="allow_once"),
            Button("Allow always (this project)", id="allow_always_project"),
            Button("Deny", id="deny"),
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id)
```

挂到 App 上：

```python
# 订阅 global_approval_manager
def on_mount(self):
    self._unsub_approval = global_approval_manager.subscribe(self._handle_approval_request)

def _handle_approval_request(self, request):
    if request is None:
        return
    async def show():
        decision = await self.push_screen(ApprovalScreen(request.tool_use))
        global_approval_manager.respond(decision)
    self.call_later(show)
```

参考点：你在 `trendpower-py/trendpower/coding/permissions/approval_manager.py` 和 `.../tools/ask_user_question_manager.py` 写的 manager 完全可以复用——只是订阅 callback 改成发 Textual screen 而已。

---

### 阶段 9：Bootstrap（first-run wizard + model wizard）（2 小时）

把 `bootstrap/*.tsx` 的两个引导流程做成独立的 Textual `Screen` 子类。流程：

1. 应用启动时跑 `integrity.py`（检查 `~/.trendpower/` 目录、环境变量等）
2. 如果 `loadConfig()` 拿不到任何 model → push `FirstRunWizardScreen`，让用户走完后再回主界面

可以共用阶段 3 的 `commands/config/model/add.py` 的底层逻辑——只是 UI 不同。

---

### 阶段 10：主题 + 抛光（按需）

最后才做主题。Textual 用 `.tcss` 文件，类似简化版 CSS：

```css
/* trendpower_tui/tui/theme.tcss */
$primary: #5d7cf5;
$accent:  #ffae42;

Header { background: $primary; color: white; }
Footer { background: $surface-darken-1; }
.tool-use { color: $accent; text-style: dim; }
MessageHistory { padding: 1 2; }
```

到这里基本完成。`textual serve trendpower_tui.app:trendpowerApp` 可以白送一个网页版。

---

## 4. 你需要注意的几个坑

### 4.1 异步事件回 UI 必须用 `post_message`

Textual 的 UI 必须在 main thread 更新。你的 `agent.stream()` 是 async generator，**不能直接** `self.messages.append(...)`——必须用 `self.post_message(...)`，然后在 `on_xxx_message` handler 里改 reactive。这是阶段 4 那个 `AgentRunner` 设计的核心原因。

### 4.2 流式 token 速率别打爆 UI

agent 一秒可能产生几十个 message snapshot，TS 版用了 `setTimeout 50ms` 节流（见 `use-agent-loop.ts` 的 `enqueueMessage`）。Python 版同样要做：每 50ms 把队列里的 messages 一起 flush，否则 Textual 重绘跟不上。

### 4.3 Markdown 别每次都重新渲染整段历史

Textual 的 `RichLog` 是 append-only 的，所以**只写增量**，不重排已经显示的内容。这跟 TS 版用 `useStdout().write` 写 scrollback 是同一个思路。

### 4.4 复用 `trendpower-py` 已经写好的 manager

不要重新实现 `ApprovalManager` / `AskUserQuestionManager`——这两个 manager 已经在核心库写好，只是订阅回调改成 Textual 推 screen。这就是为什么阶段 8 那么短。

### 4.5 退出键

Ctrl+C 在 Textual 里默认是 quit，但**正在 stream 的 agent 不会被打断**。要在 `App.action_quit()` 里加：

```python
def action_quit(self) -> None:
    if self.streaming:
        self.runner.abort()
    self.exit()
```

或者 Esc 一次中断、再按一次退出（TS 版的行为）。

### 4.6 不要做的事

- ❌ 不要把 TS hooks 一比一翻成 Python（没必要，Textual 模型不同）
- ❌ 不要在 widget 的 `compose()` 里跑异步 IO（用 `on_mount` 启动 `@work`）
- ❌ 不要给 `MessageHistory` 用 reactive 整个 list（用 append 模式）

---

## 5. 工作量估计

| 阶段 | 估时 | 累计 |
|---|---|---|
| 1. Hello World | 0.5h | 0.5h |
| 2. Config/Settings | 2h | 2.5h |
| 3. CLI 子命令 | 2h | 4.5h |
| 4. AgentRunner | 3h | 7.5h |
| 5. MessageHistory | 2h | 9.5h |
| 6. InputBox + 斜杠命令 | 2h | 11.5h |
| 7. Indicator/Todo/Footer | 2h | 13.5h |
| 8. Approval/Ask prompts | 3h | 16.5h |
| 9. Bootstrap wizards | 2h | 18.5h |
| 10. 主题 + 抛光 | 2h | 20.5h |

约 **2.5 个工作日**专注开发，**完整功能**对齐 TS 版。

如果跳过 bootstrap 和 wizard（让用户手动写 config 文件），可以压缩到 **1.5 天**。

---

## 6. 验收清单

迁移结束后，确认下面这些 TS 版有的功能 Python 版都跑通：

- [ ] `trendpower` 无参数启动 TUI
- [ ] `trendpower config model add ...` 增删改 model 配置
- [ ] 跟 agent 对话能看到 streaming 文本
- [ ] 工具调用显示为 `⏺ tool_name(params)`
- [ ] 工具结果显示为带 summary 的折叠状态
- [ ] `todo_write` 工具触发 TodoPanel 更新
- [ ] 危险工具（bash/write_file/...）触发 approval 弹窗
- [ ] `ask_user_question` 工具触发选择弹窗，正确返回结果
- [ ] 斜杠命令 `/clear` `/help` `/exit` 工作
- [ ] ↑/↓ 翻输入历史
- [ ] Ctrl+C 优雅退出，正在 stream 的 agent 被 abort
- [ ] Skill 列表通过斜杠命令暴露
- [ ] `textual serve trendpower_tui.app:trendpowerApp` 能在浏览器打开同一个 TUI（白送的 web 版）

---

## 7. 进一步阅读

- Textual 官方教程：<https://textual.textualize.io/tutorial/>
- Textual widget 列表：<https://textual.textualize.io/widget_gallery/>
- Click 文档（CLI 子命令）：<https://click.palletsprojects.com/>
- 你的核心库：[`trendpower-py/`](../trendpower-py)
- 原始 TS 前端：[`src/cli/`](../src/cli)
