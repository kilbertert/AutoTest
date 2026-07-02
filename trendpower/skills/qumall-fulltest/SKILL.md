---
name: qumall-fulltest
description: |
  When the user says anything like "全面测试 <url>", "完整跑一遍", "全量回归",
  "全面探索网站并设计测试用例自动跑", "测试 qumall 后台全部模块",
  "探索这个网站然后自动生成测试用例跑一遍", or otherwise asks to autonomously
  explore a Web admin backend AND design test cases from scratch AND run them —
  load this skill.

  The skill orchestrates MCP servers in a strict 5-stage workflow:
  ① read the example spreadsheet's column structure as a template (excelio) →
  ② explore each module's UI (chrome-devtools) → ③ DESIGN fresh cases into a
  new blueprint .xlsx file (excelio) → ④ execute every case one-by-one
  (chrome-devtools + visual captcha OCR) → ⑤ write results back into the
  blueprint (excelio) + emit a summary.

  The example `测试用例.xlsx` is READ-ONLY — it only provides the column
  structure template. AI generates a brand-new blueprint file per run.

  Required MCP servers: `excelio` (read template + create/write blueprint) +
  `chrome-devtools` (drive Chrome). Optional: `api-mcp` for AJAX assertions.
---

# qumall-fulltest workflow

This skill runs an **autonomous end-to-end UI test**: explore a site, design
test cases from scratch, save them as a **blueprint .xlsx file**, then execute
that blueprint and write results back into the same file. One shot, start to
finish; Stage 3末尾把蓝图路径告诉用户（不阻塞，继续执行 Stage 4-5）。

The example spreadsheet (`测试用例.xlsx`) is **read-only** — it only provides
the 16-column structure template:
`用例ID / 项目 / 端口 / 模块 / 功能 / 子功能 / 优先级 / 测试方法 / 用例标题 /
前置条件 / 测试数据 / 测试步骤 / 预期结果 / 编写人 / 执行结果 / 备注`

AI never writes to the example file. The blueprint file is created fresh each
run at: `~/.trendpower/runs/<run_id>/blueprint.xlsx`

## Blueprint column structure (18 columns = 16 template + 2 extension)

The blueprint extends the template with 2 columns for replayability:

| col | name | source | writable by AI |
|---|---|---|---|
| 0 | 用例ID | AI designs | only at design time |
| 1 | 项目 | AI | only at design time |
| 2 | 端口 | AI | only at design time |
| 3 | 模块 | AI (from Stage 1 map) | only at design time |
| 4 | 功能 | AI | only at design time |
| 5 | 子功能 | AI | only at design time |
| 6 | 优先级 | AI | only at design time |
| 7 | 测试方法 | AI | only at design time |
| 8 | 用例标题 | AI | only at design time |
| 9 | 前置条件 | AI | only at design time |
| 10 | 测试数据 | AI | only at design time |
| 11 | 测试步骤 | AI | only at design time |
| 12 | 预期结果 | AI | only at design time |
| 13 | 编写人 | "auto" | only at design time |
| 14 | 执行结果 | empty at design; filled at execute | ✅ execute stage |
| 15 | 备注 | empty at design; filled at execute | ✅ execute stage |
| 16 | UI_selector | AI records the stable selector/uid for the primary target element at design time | only at design time |
| 17 | 截图路径 | empty at design; filled at execute (path to failure screenshot) | ✅ execute stage |

**Write whitelist** (enforced by `excelio__update_cells`):
- ✅ col 14 (执行结果): `"通过"` / `"失败"` / `"跳过"`
- ✅ col 15 (备注): failure reason, ≤ 200 chars
- ✅ col 17 (截图路径): absolute path to screenshot
- ❌ col 0-13, 16 — write rejected. These are design-time only.

## When NOT to use this skill

- The user asks to test a **single feature** in conversation → just drive Chrome directly, no blueprint needed
- The user asks to test a **backend API** → use `apifox-api-testing` or `api-mcp` skills
- The URL is **not** a Web UI (it's an API only or a desktop app) → wrong skill

---

## Stage 0 — Inputs

Ask the user (or infer from prompt) for:

| Variable | Default | How to ask if missing |
|---|---|---|
| `target_url` | (from prompt) | "测试哪个网站？" |
| `template_xlsx_path` | `测试用例.xlsx` (search cwd + 1 level up) | (almost always auto-found) |
| `run_id` | auto: `<yyyy-mm-dd>-<short-hash>` | used for blueprint path + checkpoint |
| `sample_size` | `0` (design+run all modules) | "先跑 50 条抽样验证成本？还是全量？" |
| `credentials_provider` | ask user | "怎么登录？手工登录后导出 storage_state 给我 / 直接给用户名密码 / 已登录态从 <path> 读" |

If the user says "全面测试 https://admin.qumall.qushiyun.com/" verbatim, infer:
- target_url = that URL
- template_xlsx_path = auto-find `测试用例.xlsx`
- run_id = auto-generate
- sample_size = 0 (full)
- credentials_provider = **ask** — never assume

---

## Stage 1 — Read template structure + module map (excelio)

Goal: get the 16-column header template + (if the template has a sheet 2) the module/function hierarchy.

### 1.1 Get the header template

```
excelio__read_header(path="<template_xlsx_path>", sheet=1)
→ returns: ["用例ID", "项目", "端口", "模块", ..., "执行结果", "备注"]
```

Store this as `template_header` (16 items). The blueprint will use `template_header + ["UI_selector", "截图路径"]` = 18 columns.

### 1.2 Get the module map (if sheet 2 exists)

```
excelio__list_sheets(path="<template_xlsx_path>")
→ returns: [{name: "后台测试用例...", rows: ..., cols: 16},
            {name: "按后台开的菜单整理出的功能...", rows: 366, cols: 3}]
```

If a second sheet exists:
```
excelio__get_module_map(path="<template_xlsx_path>", sheet=2)
→ returns: [{module: "登录", function: "登录", subfunction: "登录主流程"}, ...]
```

Group into a hierarchy as `module_map`. This is your **exploration checklist** — every (module, function) pair must be visited in Stage 2.

If sheet 2 does not exist, derive the module list from Stage 2 navigation instead (visit the home page, enumerate top-level menu items, recurse one level).

### 1.3 Create the blueprint file

```
excelio__create_blueprint(
  path="~/.trendpower/runs/<run_id>/blueprint.xlsx",
  template_header=<16-item list from 1.1>,
  extra_header=["UI_selector", "截图路径"]
)
→ returns: {path: "<absolute blueprint path>", columns: 18}
```

The blueprint starts empty (header row only). Stages 2-3 will fill it.

**Emit a status event** so the sidebar knows the blueprint path early:
```
emit status phase="blueprint_created" detail="<blueprint path>"
```

### 1.4 Reporting tools (built into the runner — NOT MCP)

The runner registers two plain function tools the sidebar listens to. Call them
throughout the workflow to drive the progress bar + module chips:

- `report_progress(done, total, failed=0, module?)` — sets/updates the case
  counter. Call once after Stage 3 with `done=0, total=<N>` to set the total,
  then after every executed case in Stage 4.
- `report_module_status(module, state)` — `state` ∈ `pending` | `running` |
  `passed` | `failed`. Call when starting / finishing each module.

These are **not** `excelio__*` or `chrome-devtools__*` tools — they have no
prefix. They exist purely to surface progress to the UI; they return `{ok:true}`
and change no files.

After Stage 1.2, seed the module chips:
```
for mod in module_map.modules:
    report_module_status(module=mod, state="pending")
```

---

## Stage 2 — UI exploration (per module)

For each `(module, function)` from Stage 1.2:

### 2.1 Open a fresh tab per module

```
chrome-devtools__new_page()
chrome-devtools__select_page(pageId=<new>)
chrome-devtools__resize_page(1440, 900)
report_module_status(module=<module>, state="running")
```

### 2.2 Navigate to the module

```
chrome-devtools__navigate_page("<target_url>/<module-route>")
chrome-devtools__wait_for(text="<module-name>", timeoutMs=10000)
```

If the route is unknown, navigate home and click the menu link by text:
```
chrome-devtools__navigate_page("<target_url>/")
chrome-devtools__take_snapshot()
# from the snapshot, find the link node whose name == module_name, read its uid
chrome-devtools__click(uid=<uid-from-snapshot>)
chrome-devtools__wait_for(text=module_name, timeoutMs=10000)
```

### 2.2.1 Target stability (SPA-switching workaround)

qumall is an SPA — clicking a menu item or firing `navigate_page` to a route
(i.e. anything that changes `window.location`) **closes the previous CDP target
in chrome-devtools-mcp** and creates a new one. Subsequent tool calls that
reference the old pageId/target fail with:

> `Target closed` / `Protocol error (Page.captureScreenshot): Target closed`

Rules to survive this:

1. **Always start chrome-devtools ops with `list_pages`** if more than ~3 tool
   calls have elapsed since the last one, or if the previous call failed with
   "Target closed". Find the page whose `url` matches the route you're working
   on and `select_page(pageId=...)` it before retrying.
   ```
   chrome-devtools__list_pages()
   # → [{pageId, url, title}, ...]
   # pick the one whose url contains the current module path; chrome-devtools__select_page(pageId=<that>)
   ```
2. **After `navigate_page` and `click` (which triggers route change)**, do
   `wait_for(text="<expected text on new page>", timeoutMs=15000)` BEFORE any
   snapshot/click/evaluate — this blocks until the SPA finishes rendering the
   new route.
3. **If a tool returns `Target closed` / `Protocol error`**, do this recovery
   loop (up to 2 retries, then surface to user):
   ```
   chrome-devtools__list_pages()
   # find the page whose url matches the expected module path; select_page it
   chrome-devtools__select_page(pageId=<recovered>)
   chrome-devtools__wait_for(text=<expected>, timeoutMs=15000)
   # retry the failed operation once
   ```
4. **The `uid` from a `take_snapshot()` is only valid until the next SPA route
   change.** If a `click(uid=...)` fails with "no node found" or returns empty,
   re-`take_snapshot()` and read the new uid.
5. **Use `evaluate_script()` for tasks that don't need visual rendering** (data
   extraction, clicking hidden menus, reading localStorage). It bypasses the
   target-chrome-devtools dependency on the rendered page and is more resilient
   to view transitions.

**Note:** chrome-devtools-mcp has **no `find` tool**. To locate an element, call
`take_snapshot()` and read the `uid` of the node you want from the accessibility
tree. For CSS-selector existence checks, use
`evaluate_script("document.querySelector('<sel>')")`.

### 2.3 Take accessibility snapshots and enumerate UI surfaces

```
chrome-devtools__take_snapshot()
```

For each UI surface in the module, record:
- Form fields (input / select / textarea): label, name, validation rules, **stable selector** (CSS or role+text — prefer role+text for resilience)
- Buttons (submit / cancel / search / reset) + their selectors
- Tables: columns, pagination, row-action buttons
- Modals: trigger conditions, fields inside, dismiss buttons
- Status indicators (success / error toasts, loading spinners)

**The selector for each surface goes into col 16 (UI_selector) of the blueprint** when you design cases in Stage 3.

### 2.4 Auth + captcha during exploration

- If the page redirects to login → **pause** and tell the user: "需要登录态。请在 Chrome 里手工登录 qumall 后台一次，然后导出 storage_state 到 `~/.trendpower/qumall_state.json`。"
- If login needs a captcha → see "Captcha handling" below; on first run, ask the user to type the captcha manually once so we capture the post-login storage state, then resume automation.

### 2.5 Browser strategy reminder

- **One tab per module** (per user decision)
- **Reload login state every 50 cases** within a module (see Stage 4.6)
- Tab crash → open a new tab for remaining cases of that module; checkpoint records progress

---

## Stage 3 — Design cases into the blueprint

For each module's UI surfaces found in Stage 2, design test cases. Write them
into the blueprint via `excelio__append_rows`. Design coverage targets:

- **Happy path** per function (1-3 cases)
- **Field validation** per form field (empty / too long / wrong format / boundary)
- **Boundary** cases for pagination (page 1, last page, beyond-last)
- **Permission** cases if the module has role-gated actions
- **Concurrent / state** cases (e.g. submit twice rapidly, submit then navigate away)

### 3.1 Build rows

```python
new_rows = []
for case in designed_cases:
    row = [
        f"auto_<runId>_<seq>",            # 0  用例ID
        "国外充电桩",                       # 1  项目 (or infer from site)
        "pc后台",                          # 2  端口
        module,                            # 3  模块
        function,                          # 4  功能
        subfunction,                       # 5  子功能
        priority,                          # 6  优先级 "高"/"中"/"低"
        "场景法",                           # 7  测试方法
        title,                             # 8  用例标题
        preconditions,                     # 9  前置条件
        test_data,                         # 10 测试数据
        steps,                             # 11 测试步骤 "1. ...; 2. ...; 3. ..."
        expected,                          # 12 预期结果
        "auto",                            # 13 编写人
        "",                                # 14 执行结果 (empty at design)
        "",                                # 15 备注 (empty at design)
        primary_selector,                  # 16 UI_selector (stable CSS / role+text)
        "",                                # 17 截图路径 (empty at design)
    ]
    new_rows.append(row)

excelio__append_rows(path=blueprint_path, sheet=1, rows=new_rows)
```

### 3.2 Tell the user the blueprint path (do NOT block)

After all modules are designed, emit:
```
emit assistant_text: "蓝图已生成: <blueprint_path>\n共 N 条用例，覆盖 M 个模块。开始执行..."
report_progress(done=0, total=<N>, failed=0)
```

Setting `total` here initializes the sidebar progress bar (0 / N) before
execution starts.

Then **immediately continue to Stage 4**. Do not wait for user confirmation —
the user can open the blueprint file in Excel alongside the run if they want
to review mid-execution. (Per user decision: 一次跑完但 Stage 3 末尾把蓝图路径告诉用户。)

⚠ **Before entering Stage 4**: re-read section 2.2.1 ("Target stability"). The
SPA-switching race that killed Stage 2 will absolutely happen during Stage 4's
per-case clicks. Apply the `list_pages` / `select_page` / `wait_for` discipline
on every chrome-devtools call inside the case loop.

### 3.3 Reload the blueprint into memory

```
excelio__read_sheet(path=blueprint_path, sheet=1, range={"max_rows": 5000})
→ returns: [{row: 2, values: [...]}, ...]
```

Group by `(模块, 功能)` → `cases_by_module`. This is the execution queue for Stage 4.

---

## Stage 4 — Per-case execution

Iterate all cases in the blueprint, **one at a time**, in the matching module tab.

### 4.1 Per case

```
1. Parse col 11 (测试步骤) into ordered operations (split on "; " or "1. 2. 3.")
2. For each operation:
   a. Identify target element — prefer col 16 (UI_selector) recorded at design;
      fall back to take_snapshot() to get a fresh uid if the recorded selector is stale
   b. chrome-devtools__click(uid=...) / chrome-devtools__fill(uid, value) /
      chrome-devtools__fill_form(values) / chrome-devtools__type_text(uid, text) / ...
   c. If a captcha appears, see "Captcha handling" below
3. After all steps, read the resulting state:
   - chrome-devtools__take_snapshot() to compare with col 12 (预期结果)
   - chrome-devtools__evaluate_script("() => document.body.innerText") for text matching
   - chrome-devtools__list_network_requests() to verify expected AJAX calls
4. Determine pass/fail:
   - PASS: actual matches expected
   - FAIL: actual diverges — capture divergence in note + take a screenshot
5. Write back to the blueprint (whitelist: col 14, 15, 17):
   excelio__update_cells(path=blueprint_path, sheet=1, updates=[
     {row: case.row, col: 14, value: "通过" or "失败" or "跳过"},
     {row: case.row, col: 15, value: "<failure reason, ≤ 200 chars>" or ""},
     {row: case.row, col: 17, value: "<screenshot path>"}    # only on failure
   ])
6. Report progress to the UI:
   report_progress(done=<done+1>, total=<total>, failed=<failed + (1 if 失败 else 0)>, module=<current module>)
```

### 4.2 Per-case progress event

`report_progress` (called in step 6 above) is the single source of truth for the
sidebar progress bar. Call it after **every** case — the runner also snapshots
the transcript + progress to `~/.trendpower/checkpoints/<run_id>.json` after
every tool_result, so a crash never costs more than one case.

When the last case of a module finishes:
```
report_module_status(module=<module>, state="passed")   # if no failures
# or
report_module_status(module=<module>, state="failed")   # if any case failed
```

### 4.3 Checkpoint & resume (automatic)

You do **not** write checkpoints yourself. The runner auto-saves
`~/.trendpower/checkpoints/<run_id>.json` after every tool result (transcript +
last `report_progress`/`report_module_status` snapshot). On a hard crash or
user stop, the user resumes with:

```
runner --resume <run_id> --prompt "继续执行 blueprint 里未完成的用例"
```

On resume, the runner reloads the transcript and re-emits the last
`progress` + per-module `module_status` events so the sidebar restores its
state. Your first action on resume should be to read the blueprint's col 14 to
find the first row where 执行结果 is still empty, and continue from there.

### 4.4 Error recovery

- **Single case fails** → log to note + screenshot, continue
- **5 consecutive failures in same module** → `ask_user_question`:
  (a) Continue  (b) Skip module  (c) Pause + surface top-3 errors
- **Tab crash** → open new tab, reload module, continue from last-checkpointed case
- **Captcha OCR fails twice** → `ask_user_question`: "OCR 识别失败 [显示两次识别结果 vs 实际]，请手工输入当前验证码"

### 4.5 Captcha handling (visual OCR)

qumall uses a dynamic graphical captcha. The flow:

```
1. chrome-devtools__take_screenshot(uid=<captcha-img-uid>, format="png")
   → returns {filePath: "~/.trendpower/runs/<runId>/captcha_<n>.png", data: "<base64>"}
2. Construct an image_url content block from the returned data (already base64):
   {"type": "image_url",
    "image_url": {"url": "data:image/png;base64,<base64>"}}
3. Send as a new user message:
   user_message = {
     "role": "user",
     "content": [
       {"type": "text", "text": "这是验证码图片。识别并只输出 4-6 位字符（数字+字母），不要其他任何内容。"},
       <image_url block above>
     ]
   }
4. Capture the agent's text response → that's the captcha text
5. chrome-devtools__fill(uid=<captcha-input>, value=<captcha-text>)
```

**Hard constraints:**
- ✅ **Must use anthropic provider** — `AnthropicModelProvider` converts `image_url` to a native Anthropic image block (anthropic/utils.py:37-43). The OpenAI provider (`community/openai/utils.py:11-52`) **silently drops image content** — it has no `image_url` branch.
- ✅ **minimax 中转已确认支持 vision** (anthropic 兼容协议) — if a vision call returns 4xx, fall back to: (a) ask user to type captcha manually, (b) cache answer, (c) continue
- ❌ Do not retry OCR more than 3 times in a row — pause and ask user

### 4.6 Storage state reload every 50 cases

Inside a long-running module, the login session may expire. To refresh:
```
chrome-devtools__evaluate_script("async () => { await fetch('/api/refresh', {credentials:'include'}); }")
# fallback:
chrome-devtools__navigate_page(current_url)  # or evaluate_script("location.reload()")()
chrome-devtools__wait_for(text=<something-on-the-page>, timeoutMs=5000)
```

If the page redirects to login mid-module: pause, tell user "登录态失效，请重新登录并重新导出 storage_state。"

---

## Stage 5 — Summary

After all cases (or after user interrupts via stop):

1. Aggregate from the blueprint's col 14:
   - total, passed, failed, skipped
   - per-module pass rate
   - top 5 failure categories (group col 15 by keyword)

2. Surface as the assistant's final text:
```
测试完成
========
蓝图文件: <blueprint_path>
总用例: 3020  通过: 2843 (94.1%)  失败: 165  跳过: 12
模块通过率:
  登录     98%  (44/45)
  首页    100%  (12/12)
  ...
Top 5 失败原因:
  1. 验证码识别超时 (47 次)
  2. 列表分页跳转异常 (28 次)
  ...
蓝图已就地更新（执行结果/备注/截图路径列）。
```

3. Write a JSON summary to `~/.trendpower/runs/<run_id>/summary.json` for later inspection.

---

## Hard constraints (read these or break things)

1. **Never write to the example `测试用例.xlsx`** — it is read-only. All writes go to the blueprint file.
2. **Never modify col 0-13, 16 of the blueprint** — `excelio__update_cells` will refuse. These are design-time only.
3. **Use anthropic provider only** — OpenAI provider silently drops image content; captcha OCR will fail silently.
4. **One tab per module** — never share tabs across modules (state contamination).
5. **Design before execute** — Stage 3 must complete for all modules before Stage 4 starts on any module.
6. **Call `report_progress` after every case** — it drives the sidebar progress bar AND triggers the runner's auto-checkpoint. Skipping it means the UI goes dark and a crash may cost more work.
7. **`--resume <run_id>` restores the transcript + progress** — the runner auto-saves after every tool result. On resume, re-read the blueprint's col 14 to find the first un-executed row and continue.
8. **Storage state at `~/.trendpower/qumall_state.json`** — if missing, STOP and ask the user to provide it.
9. **Browser headless mode is OFF by default** — visual OCR needs visible Chrome. If user wants headless, plan a fallback first (ddddocr local OCR).
10. **The sample_size escape hatch exists for a reason** — if unsure about cost, design + run 50 first.

## Known unknowns (flag these to the user immediately)

- **minimax 中转对 vision 模型的真实支持度** — confirmed by user but not yet stress-tested; first captcha is the canary.
- **chrome-devtools-mcp 对 qumall 旧版 UI 组件的兼容性** — if `find(role=…)` returns no matches, fall back to `evaluate()` + CSS selectors.
- **qumall 验证码的实际字符集与长度** — example sheet shows `"验证码：ny5x"` (4 chars), live UI may differ. OCR prompt says "4-6 位字符" as a fallback.
- **登录态有效期** — default ~30 min. Stage 4's "every 50 cases reload" is empirical, may need tightening.
