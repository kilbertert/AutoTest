# 第 4 课 · ReAct 循环（心脏）

这是整个 trendpower 的**发动机**。前面所有名词，到这一课才真正"动"起来。代码几乎全在一个文件里：`agent/agent.py`。

---

## 一、① 要解决什么问题

你让 agent "把所有 print 改成 logging"。它一句话做不完——得先搜哪些文件有 print、再逐个读、再逐个改。**每一步该干嘛，取决于上一步的结果**（搜出来几个文件，才知道要改几个）。

所以需要一个**循环**：想一步、做一步、看结果、再想——直到活干完。这个模式叫 **ReAct**（Reason + Act）。

打个比方：**修电脑**。你不会闭着眼一口气修完，而是"看哪儿坏了（想）→ 拧一颗螺丝（做）→ 看好了没（结果）→ 再决定下一步"。

---

## 二、② 设计决策

trendpower 的循环做了四个关键决定：

1. **退出条件＝模型不再调工具。** 当模型这一轮只说话、不要求用任何工具，就说明它认为干完了，循环结束。
2. **做成流式（异步生成器）。** 一边推进循环，一边 `yield` 事件（思考中、跑了某工具、回复了），让界面实时显示（第 1 课 A3）。
3. **工具并行执行 + 可抢占取消。** 一轮里多个工具同时跑；用户随时能打断（第 1 课 A2）。
4. **撞步数上限不崩，软着陆。** 防死循环设了上限，但撞到时优雅收尾而非报错（第 9 课细讲，这里点到）。

---

## 三、③ 看代码

### 主循环 `Agent.stream`

```python
# agent/agent.py:Agent.stream（简化但保留骨架）
async def stream(self, message):
    self._abort_controller = AbortController()      # 造一个"急停按钮"
    self._append_message(message)                   # 把你的话追加进对话
    await self._before_agent_run()                  # 跑"开场"中间件（第5课）
    try:
        for step in range(1, self.options.maxSteps + 1):   # 最多 100 步
            self._abort_controller.signal.throw_if_aborted()  # 每步先看有没有被急停
            await self._before_agent_step(step)

            # —— 想 ——
            assistant_message = None
            async for ev in self._think():           # think 内部也是异步生成器
                if ev["type"] == "_think_done":      # 哨兵：拿到最终消息
                    assistant_message = ev["message"]
                    break
                else:
                    yield ev                         # 把"思考中/正在调xx"进度吐给界面

            yield {"type": "message", "message": assistant_message}   # 把助手回复吐出去

            # —— 判断要不要继续 ——
            tool_uses = self._extract_tool_uses(assistant_message)    # 挑出 tool_use 块
            if not tool_uses:                        # 没有要调的工具 → 干完了
                await self._after_agent_run()
                return                               # ★唯一的正常出口★

            # —— 做 ——
            async for ev in self._act(tool_uses):    # 并行执行这些工具
                yield ev                             # 把每个工具结果吐给界面
            await self._after_agent_step(step)

        # 撞上限了：不崩，软着陆（第9课）
        async for ev in self._emit_step_limit_summary():
            yield ev
        return
    finally:
        self._streaming = False
        self._abort_controller = None
```

逐段读：

- **`for step in range(1, maxSteps+1)`**：最多循环 100 步，防死循环。
- **`self._think()`**：让模型推理一轮。它是个异步生成器，先吐若干"进度"事件，最后用一个**哨兵** `{"type": "_think_done", ...}` 把"模型这轮说完的完整消息"传回来。
  > 为什么要哨兵？因为异步生成器只能 `yield`（吐过程），不能像普通函数那样 `return` 一个最终值给 `async for` 的调用方。于是约定：吐一个特殊事件来"夹带"最终结果。这是第 1 课 A3 末尾预告的技巧。
- **`_extract_tool_uses`**：从模型这轮的回复里，挑出所有 `tool_use` 块（第 3 课说的"模型要调工具"就是这种块）。
- **`if not tool_uses: return`**：**整个循环唯一的正常出口**。没有要调的工具 = 模型认为干完了。
- **`self._act(tool_uses)`**：并行执行这些工具，把结果喂回对话，下一轮 `_think` 时模型就能看到结果。

### "想" `_think`：发给模型、边收边吐

```python
# agent/agent.py:_think（简化）
async def _think(self):
    model_context = {"prompt": self.prompt, "messages": self.messages,
                     "tools": self.tools, "signal": ...}
    await self._before_model(model_context)         # 跑"发给模型前"中间件（压缩/注入，第5课）

    latest = None
    async for snapshot in self.model.stream(model_context):  # 模型边想边吐快照
        latest = snapshot
        if snapshot.get("streaming"):
            yield self._derive_progress(snapshot)    # 把快照转成"进度"事件
    self._append_message(latest)                     # 把完整回复追加进对话
    yield {"type": "_think_done", "message": latest} # 哨兵：把最终消息传回去
```

`_derive_progress`（同文件）把流式快照翻译成人话——有工具调用就说"正在跑 xxx"，否则"思考中"：

```python
def _derive_progress(self, snapshot):
    tool_uses = [c for c in snapshot.get("content", []) if c.get("type") == "tool_use"]
    if not tool_uses:
        return {"type": "progress", "subtype": "thinking"}
    last = tool_uses[-1]
    return {"type": "progress", "subtype": "tool", "name": last["name"], "input": last["input"]}
```

### "做" `_act`：并行 + 取消赛跑

这段把第 1 课 A2 的几件武器全用上了：

```python
# agent/agent.py:_act（简化）
async def _act(self, tool_uses):
    signal = self._abort_controller.signal

    async def run_one(index, tool_use):              # 跑单个工具
        tool = 找到名字匹配的工具
        result = await tool.invoke(tool_use["input"], signal)   # 真正执行
        return {...}

    tasks = [asyncio.create_task(run_one(i, tu)) for i, tu in enumerate(tool_uses)]  # 全部并发开跑
    abort_task = asyncio.create_task(signal.wait())  # 同时起一个"等急停"的任务

    pending = set(tasks)
    while pending:
        done, _ = await asyncio.wait({*pending, abort_task}, return_when=asyncio.FIRST_COMPLETED)
        if abort_task in done:
            signal.throw_if_aborted()                # 被急停了 → 抛 AbortError，整轮中止
        for d in done:                               # 哪个工具先好，就先把它的结果吐出去
            if d is abort_task: continue
            pending.discard(d)
            resolved = d.result()
            tool_message = {"role": "tool", "content": [{"type": "tool_result", ...}]}
            self._append_message(tool_message)       # 结果追加进对话
            yield {"type": "message", "message": tool_message}   # 吐给界面
```

三个设计点对应到代码：
- **并发**：`create_task` 把每个工具一起开跑，不排队。
- **取消赛跑**：`abort_task` 和工具任务一起 `wait(FIRST_COMPLETED)`——只要急停先到，立刻 `throw_if_aborted()` 抛出 `AbortError`，整轮中止。
- **谁先好先吐**：用 `while pending` + 每次处理"已完成的那批"，所以快的工具结果先显示，不必等最慢的。

> 单个工具内部万一抛异常怎么办？`run_one` 里会 try 住，把异常变成一条 `"Error: ..."` 结果喂回模型，**而不是让整个循环崩**——让模型自己看到错误、自我修正。这条"错误不崩、喂回模型"的暗线，第 9 课会收。

---

## 四、④ 小结

- 循环 = **想（`_think`）→ 判断要不要继续 → 做（`_act`）**，反复，直到模型不再调工具（`if not tool_uses: return`）。
- 全程**流式**：`stream`/`_think`/`_act` 都是异步生成器，一路 `yield` 事件给界面实时显示。
- "做"阶段**并行**执行工具，并和**急停信号赛跑**，保证打断立即生效。
- 单个工具出错**不崩**，撞上限**软着陆**（暗线，第 9 课收）。

这台发动机本身很纯粹——它**完全不懂"编程"**，只懂"想-做"。那"压缩历史、注入技能、审批"这些增强行为是怎么挂上去的？靠**中间件**。下一课见。

👉 下一课：[05 · 中间件（配件槽）](05-中间件.md)
