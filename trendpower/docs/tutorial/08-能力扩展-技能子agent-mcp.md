# 第 8 课 · 能力扩展（技能 / 子 agent / MCP）

前面的循环、中间件、工具、上下文工程，已经搭起一个能干活的 agent。这一课讲三套**让它更强**的高级机制。它们都建立在前面的地基上。

---

## 一、技能（Skills）：先给目录，要用哪章再翻

### ① 问题

你想给 agent 灌一些"针对特定任务的最佳实践手册"——比如"做调研该怎么一步步来""写代码计划该遵循什么流程"。但如果把每本手册的**全文**都塞进系统提示，手册一多就把上下文撑爆，而且大部分内容这次任务根本用不上。

### ② 设计：渐进披露（progressive disclosure）

- 系统提示里**只放一份目录**——每个技能一行："技能名 + 一句话简介 + 它的文件在哪"。
- 模型扫一眼目录，判断哪本和当前任务相关，**才用 `read_file` 去把那本的正文读进来**。

打个比方：你不会把整个图书馆背下来，而是看**书架标签**，需要哪本才走过去抽出来翻。用不到的书一直待在架上，不占脑子。

### ③ 看代码

技能是个中间件（第 5 课提过），两个钩子：

```python
# agent/skills/skills_middleware.py（简化）
async def before_agent_run(params):            # 开场：扫描有哪些技能
    skills = []
    for skills_dir in skills_dirs:
        for folder in skills_dir 下的子目录:
            if (folder / "SKILL.md").exists():
                skills.append(读出它的frontmatter)   # 只读"头部信息"，不读正文
    return {"skills": skills}

async def before_model(params):                # 每次发给模型前：把目录拼进系统提示
    skills_xml = "\n".join(
        f'<skill name="{s["name"]}" path="{s["path"]}">\n{s["description"]}\n</skill>'
        for s in skills)
    addition = "<skill_system>...<skills>\n" + skills_xml + "\n</skills></skill_system>"
    return {"prompt": model_context["prompt"] + addition}
```

- 每个技能就是一个文件夹，里面一个 `SKILL.md`，开头有一段 **frontmatter**（YAML 头，写名字和简介）。开场只读这段 frontmatter（`skill_reader.py`），**不读正文**——这就是"只上目录"。
- `before_model` 把目录拼进系统提示。注意它返回 `{"prompt": 原提示 + 目录}`，因为基础提示不变、追加确定，所以每轮拼出来一样，**仍然可缓存**（呼应第 7 课）。
- 现成的技能在仓库根目录的 `skills/`（如 `coding-plan`、`deep-research-plan`、`frontend-design`）。

> 技能目录从哪找？`trendpower-tui/.../tui/skill_paths.py:discover_skills_dirs` 依次看：`TRENDPOWER_SKILLS_DIR`（设了就只用它）、`<cwd>/skills` 及其祖先、以及顺着已安装包位置往上找 `skills/`。可编辑安装（`uv tool install --editable`）时最后一条会指回源码，自动命中仓库根的 `skills/`，零配置。

---

## 二、子 Agent：派实习生去别的桌子上干脏活

### ① 问题（接第 7 课）

第 7 课的压缩是**事后**补救——噪音已经堆在主桌上了，再压缩。有没有更彻底的办法？有：**根本不让噪音上主桌**。

"在整个项目里查清楚某功能怎么实现"这种活，会翻几十个文件、产生一大堆中间噪音。

### ② 设计：隔离一个子 agent

派出一个**独立的子 agent**，给它自己的一套工作空间（独立对话），让它把这脏活干完，**只把一句结论汇报回主线**。中间翻了多少文件，主线一概看不到。

打个比方：写报告要查一堆背景资料，聪明做法是**派实习生去图书馆**翻完，只给你**一页摘要**——你的桌子从头到尾都干净。

这其实是"事前隔离"，和第 7 课的"事后压缩"互补。

### ③ 看代码

它表现为一个工具 `task`：

```python
# coding/tools/task.py:create_task_tool（简化）
def create_task_tool(*, model, cwd, base_tools, ask_user=None, ...):
    read_only_tools = [t for t in base_tools if t.name in READ_ONLY_TOOL_NAMES]
    general_tools   = [t for t in base_tools if t.name not in _NEVER_DELEGATE]

    async def _invoke(params: TaskParameters, signal=None):
        inner = _build_inner(params.subagent_type)   # 造一个独立的内层 Agent
        result = await run_subagent(inner, params.prompt, signal=signal)  # 跑完，拿结论
        return ok_tool_result(result.text, {"steps": result.steps, ...})  # 只回传结论
    return define_tool(name="task", ..., invoke=_invoke)
```

内层 agent 怎么跑到底？靠 `agent/subagent/runner.py:run_subagent`——它就是第 4 课那个循环的"复用"：驱动内层 `Agent.stream` 跑到结束，收集最后一条文字消息当结论：

```python
# agent/subagent/runner.py:run_subagent（简化）
async def run_subagent(inner, prompt, *, signal=None):
    if signal is not None:
        signal.add_listener(inner.abort)      # 主线被急停 → 子 agent 也停（第9课）
    async for event in inner.stream({"role": "user", "content": [{"type":"text","text":prompt}]}):
        if 是助手消息: last_assistant = event["message"]
    return SubagentResult(text=最后那条的文字, steps=..., prompt_tokens=...)
```

**两种子 agent**：
- `explore`（默认）：只读工具集（`READ_ONLY_TOOL_NAMES`），免审批——最安全，专做查资料。
- `general`：完整工具集，但会**转发主线的审批**（改文件照样弹窗）。

**两条安全红线**（写死在代码里）：
- 子 agent 的工具集**永不含 `task`**（`_NEVER_DELEGATE`）→ 不能再派子 agent，杜绝无限套娃。
- 也不含 `ask_user_question` → 子 agent 是后台干活的，不能反过来弹窗问你。

**白送的并发**：第 4 课说过 `_act` 是并行的。所以模型一次发 3 个 `task`，就是 3 个子 agent 同时在 3 张桌子上干，各自独立——这正是"并行查三个方向"。

---

## 三、MCP：接入"外部工具"

### ① 问题

内置 12 个工具不够用，想接第三方提供的工具（比如一个能操作浏览器的工具、一个查数据库的工具）怎么办？业界有个标准协议叫 **MCP（Model Context Protocol）**，专门让 agent 接外部工具。

### ② 设计：协议在核心库，接线在前端

trendpower 把 MCP 拆成两半放（这又是第 2 课"单向依赖"的体现）：

| 放哪 | 内容 | 为什么 |
|---|---|---|
| **核心库** `community/mcp/` | 真正的 MCP 协议客户端（连接、列工具、调工具） | 与界面无关、可复用，所以沉到核心 |
| **前端** `trendpower-tui/.../mcp/` | 到哪找配置文件、绑定到界面的启动/退出、`/mcp` 命令 | 进程相关的"接线胶水"，留在前端 |

### ③ 看代码（点到为止）

- 核心：`community/mcp/manager.py`（管理多个 MCP server）、`session.py`、`tool_adapter.py`（把 MCP 工具**适配成 trendpower 的 `Tool`**——还记得第 3 课 `FunctionTool` 的 `raw_input_schema` 逃生舱吗？就是给 MCP 用的：直接透传它的原始参数 schema，不经 pydantic 往返）。
- 前端：`trendpower-tui/.../mcp/lifecycle.py`、`config_loader.py`——它们 `from trendpower.community.mcp import ...`，只是在 TUI 进程里**调度**核心那套。

**设计合理性**：协议实现是通用的（沉核心），"去哪找配置、绑界面生命周期"是进程特有的（留前端）。这样核心库保持纯净，不被前端细节污染——正是单向依赖想要的效果。

> 想看实战，仓库里有 [mcp.md](../mcp.md) 和 [mcp-playwright.md](../mcp-playwright.md) 两篇深入文档。

---

## 四、④ 小结

| 机制 | 一句话 | 关键文件 |
|---|---|---|
| **技能** | 系统提示只放目录，用时再 `read_file` 翻正文 | `agent/skills/skills_middleware.py` |
| **子 agent** | 脏活派去别的桌子干，只端结论回来；防套娃、防阻塞、可并行 | `coding/tools/task.py` + `agent/subagent/runner.py` |
| **MCP** | 接外部工具；协议沉核心、接线留前端 | `community/mcp/` ↔ `trendpower-tui/.../mcp/` |

这三套加上前面的循环和工具，trendpower 的"能干什么"就齐了。但还有一条贯穿所有零件的**暗线**没收口：出错了怎么办、取消怎么办。下一课专门收这条线。

👉 下一课：[09 · 健壮性与收尾](09-健壮性与收尾.md)
