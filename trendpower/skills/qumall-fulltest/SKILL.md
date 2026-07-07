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

  Coverage matrix (Stage 3): every run designs cases along 5 dimensions —
  **业务流程 / 数据驱动 / 权限矩阵 / 异常路径 / 审计合规** — not just smoke.
  Stage 1.5 also reads real cases from the example `测试用例.xlsx` for the
  same module and feeds them as few-shot samples to keep style consistent
  with human-authored cases.

  ---

  ## ⚠ Mode B: replay existing cases (use this when QA already wrote cases)

  When the user says "跑测试用例.xlsx" / "执行我们写好的用例" / "回归一下测试
  用例" / "把这些用例跑一遍" — **switch to Mode B**. Do NOT design new cases
  (Mode A is for that). Mode B skips Stage 1.5 (few-shot), Stage 3 (design),
  and replays the cases the user already approved.

  Mode B pipeline:
  1. (pre-step, done by the user) Build a mirror xlsx with
     `uv run --project excelio-mcp-server python mirror_blueprint.py` —
     see "Mirror command" below.
  2. Stage 1: read_header the mirror to confirm 16-col layout.
  3. Stage 1' (new): read_sheet the mirror with max_rows that covers all
     cases; group by 模块. Treat empty 模块 cells as cascading (Excel
     merged-cell behaviour) — the agent should walk the rows in order and
     inherit the most recent non-empty 模块.
  4. Stage 2: chrome-devtools UI exploration — **only** for the modules
     present in the case queue (skip modules with 0 cases).
  5. Stage 4: for each case, parse col 11 (测试步骤) into ordered ops
     (split on `;` or `1. 2. 3.`), execute, and write col 14 (执行结果) +
     col 15 (备注) back to the **mirror** xlsx. Skip captcha-blocked cases
     (mark 跳过).
  6. Stage 5: summary + per-case pass/fail breakdown.

  ---

  ## Mirror command (Mode B prerequisite)

  ```
  uv run --project excelio-mcp-server python mirror_blueprint.py \
    --src "D:/workspace/project/auto-test/AutoGenesis/测试用例.xlsx" \
    --dst "D:/workspace/project/auto-test/AutoGenesis/blueprints/qumall-replay.xlsx" \
    --modules 登录 充电桩首页 商家入驻/合作商家 \
    --max-per-module 5
  ```

  This copies the source xlsx verbatim (preserving styles, shared strings,
  theme) and trims the rows to the requested modules. The mirror keeps the
  original 16-col layout, so Stage 4's `excelio__update_cells` col 14/15
  writes land on the same 16-col header QA expects.

  IMPORTANT: never write to 测试用例.xlsx directly. The mirror is the only
  writable surface.
---

# qumall business context (for Stage 3 design prompt)

qumall is a **S2B2C 充电桩运营后台** (Supplier-to-Business-to-Consumer).
Adapt the test vocabulary to this domain — do **not** write generic "登录成功"
cases; write cases that exercise the business semantics.

## User roles (权限矩阵 — Stage 3.2 must cover ≥2 roles per module)
- **总平台运营** (`platform`): 全模块可见 + 全权限
- **区域代理** (`region`): 仅看本区域商家 + 设备 + 订单
- **商家** (`merchant`): 仅看自己入驻的数据 + 自己设备 + 自己订单
- **财务** (`finance`): 仅看账单/分账/对账模块，只读
- **游客** (`guest`): 无登录态，只能访问公开页

## Core business flow (业务流程 — Stage 3.2 must cover E2E happy + E2E rollback)
```
商家入驻申请 → 平台审核(待审/通过/拒绝/撤销) → 签约(合同/分成比例/账期) →
设备登记(充电桩/型号/功率/位置) → 上线(扫码/插枪/启动/计费) →
订单生成(按计费规则) → 自动分账(平台/代理/商家比例) →
对账(T+1 出账单) → 提现(申请/审核/到账) → 异常处理(退款/申诉/调账)
```

## Module-to-case mapping (Stage 3.2 must hit each module's typical cases)
| Module | 必有 case 类型 |
|---|---|
| 登录 | 验证码 3 次失败锁定、记住登录失效、踢人下线、SSO |
| 首页 | 多角色首页数据范围、按区域筛选、待办事项跳转准确性 |
| 商家入驻 | 资质上传/审核状态机/拒绝理由回填/重新提交 |
| 设备管理 | 设备新增/上线/故障/离线、扫码绑定、解绑 |
| 计费规则 | 时段计费/峰谷电价/封顶值/功率阶梯 |
| 订单/账单 | 跨月分账/T+1 出账/对账差异/退款流程 |
| 财务/分账 | 比例调整追溯、提现手续费、税务字段 |
| 系统管理 | 操作日志、权限变更追溯、敏感字段脱敏 |

## Glossary (use these terms literally in test titles)
**计费规则**: 时段/峰平谷/封顶/服务费/阶梯电价
**订单**: 充电订单/预约订单/退款单/调账单
**分账**: 平台抽成/代理抽成/商家实收/T+N 到账
**设备**: 充电桩/充电柜/编号/SN/IMEI/固件版本
**资质**: 营业执照/银行账户/法人身份证/场地证明
**状态机**: 待审 → 审核中 → 通过/拒绝 → 已撤销/已签约
**对账**: 平台账单/商家账单/差异单/补单


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

## Stage 1' — Mode B: load existing case queue from qumall.db (replay)

Skip Stage 1.5 (few-shot) and Stage 3 (design). Load the cases into a
**SQLite database** (`blueprints/qumall.db`) once, then drive the per-case
loop via precise `qumall-db` queries — never re-read the whole xlsx /
queue JSON.

### Why a database, not the JSON dump

Earlier runs (qumall-replay-queue, pilot v1/v2) wasted 30-40% of tool
calls on `excelio__read_sheet` / `read_file <queue.json>` /
`excelio__list_sheets` to "double-check" the queue. SQLite gives exact
per-case queries that the agent cannot "re-read the whole table" with
on accident. The xlsx still gets the final col 14/15 writeback via
`excelio__update_cells`; SQLite is the in-flight execution store.

### Run once at Stage 1' start

```bash
# 1. (Re-)build qumall.db from the mirror xlsx or from a pre-dumped queue.
#    The first run uses --reset to drop any prior partial results; later
#    resumes omit --reset to preserve status/note from interrupted runs.
uv run python qumall-db/import_xlsx.py \
    --db blueprints/qumall.db \
    --queue blueprints/qumall-full-queue.json

# 2. Sanity check: how many cases are loaded, distribution, anything
#    already done from a prior partial run.
uv run python qumall-db/cli.py stats --db blueprints/qumall.db
```

Output (single-line JSON, easy to parse):
```json
{
  "ok": true,
  "total": 3590,
  "by_status": {"(pending)": 1200, "通过": 1800, "失败": 540, "跳过": 50},
  "by_module": [
    {"module": "会员", "total": 261, "passed": 0, "failed": 0, "skipped": 0, "pending": 261},
    ...
  ],
  "top_failures": [
    {"note": "Element not found: 提交按钮", "n": 23},
    ...
  ]
}
```

### Initialize the UI + report_progress seed

```
total = stats["total"]; done = total - stats["by_status"].get("(pending)", 0)
failed = stats["by_status"].get("失败", 0)
report_progress(done=done, total=total, failed=failed)
for mod in stats["by_module"]:
    if mod["pending"] > 0:
        report_module_status(module=mod["module"], state="pending")
```

### Strict tool rules (Mode B)

- ✅ Allowed in Stage 1'/4: `bash` (running `qumall-db/cli.py ...`),
  `chrome-devtools__*` (browser control), `excelio__update_cells` (mirror
  col 14/15 writeback), `report_progress` / `report_module_status` (UI).
- ❌ Banned in Stage 1'/4: `excelio__read_sheet` / `excelio__read_header`
  / `excelio__list_sheets` / `read_file` on the queue JSON. The mirror
  was already read at the start of Stage 1' by `import_xlsx.py`; the DB
  is the only thing you need during execution.

The mirror is the **only** writable Excel surface. Never write to
测试用例.xlsx (read-only).

---

## Stage 1.5 — Sample-driven reference (few-shot from real cases)

The example `测试用例.xlsx` contains ~3591 real cases covering 30 modules.
These are written by QA in the exact 16-column structure the blueprint needs,
and use domain-correct terminology (计费规则/分账/状态机 etc.). **Without
learning from these samples the agent invents bland cases like "页面正常加载"
— exactly the failure mode reported in W2 user feedback.**

### 1.5.1 Pick the same-module sample window

For each `(module, function)` pair you'll design in Stage 3, pull 3-6 real
existing cases as reference. Fastest: read sheet 1 with a large `max_rows`,
filter to the current module, take the first N. Do this **inside** Stage 1.5
(concurrent with Stage 2 exploration), not in Stage 3, so the samples stay
in context for the design step.

```
excelio__read_sheet(path="测试用例.xlsx", sheet=1, max_rows=200)
→ returns rows 2..201 with col 3 = 模块 name
# filter in-memory: keep rows where col 3 (模块) == <current module>
# group by col 4 (功能) to spread coverage
→ sample_for_module[mod][function] = [3-6 rows]
```

For modules missing in the sample (rare; qumall's 30 modules all exist), fall
back to the closest semantic module's samples and explicitly note the gap.

### 1.5.2 Build the "sample bank" the design prompt references

Concatenate per-module rows into a compact text block, max **~200 tokens per
module** (otherwise it overpowers the prompt budget on big modules):

```
sample_bank[mod][func] = [
  "TC001 | 登录 | 账号不存在场景 | 输入未注册账号登录 → 提示「账号不存在」,不暴露注册接口",
  "TC002 | 登录 | 验证码错误3次锁定 | 连续3次输入错误验证码 → 锁定15分钟,前端倒计时",
  "TC003 | 商家入驻 | 营业执照号重复 | 上传已存在的营业执照 → 后端返回重复,前端红字提示",
  ...
]
```

Keep **titles verbatim** from the sample — they encode the real business
wording (e.g. "营业执照号重复" is far better than "上传证件校验"). The LLM
copies this style into its own generated cases.

### 1.5.3 Anti-pattern guard

When the agent sees good samples, it rarely regresses to "页面正常加载". Add
this hard rule to the Stage 3 prompt:

> Every case title MUST start with one of these prefixes:
> `[正常] [异常] [边界] [权限] [流程] [审计] [并发] [兼容]`
> Reject any title that starts with `页面` `功能` `正常显示` `加载`.

---

## Stage 2 — UI exploration (per module)

For each `(module, function)` from Stage 1.2:

### ⚠ 2.0 TOOL RULES — read this first (every stage, no exceptions)

The agent has FIVE MCP servers loaded. **Each one has a strict role; mixing
them is a bug.** Read the table once and apply it to every tool call:

| Task | USE | NEVER USE |
|---|---|---|
| Open a URL / new browser tab | `chrome-devtools__new_page` or `chrome-devtools__navigate_page` | `pywinauto__app_launch` (that launches native Windows apps like Notepad, not a browser — wrong tool) |
| Click / fill / read DOM | `chrome-devtools__click` / `fill` / `take_snapshot` / `evaluate_script` | `pywinauto__*` (desktop controls only — does NOT touch the browser DOM) |
| See browser pages open | `chrome-devtools__list_pages` | `pywinauto__app_screenshot` (screenshots the Windows desktop, not the browser) |
| Read the mirror xlsx | `bash` + `dump_queue.py` (preferred) **or** `excelio__read_sheet` ONCE | `read_file` on a binary xlsx (returns garbage) |
| Write results to mirror | `excelio__update_cells` (col 14 + 15 only) | `apply_patch` / `write_file` on the xlsx (will corrupt it) |
| Edit source code in the repo | `apply_patch` / `str_replace` | n/a (this skill does not edit code) |
| Run a shell command | `bash` | n/a |
| Read a text/markdown file | `read_file` | n/a |

**If a tool you tried to call returns a confusing or empty result, the
fix is NEVER to swap to a different tool family — it is to read this
table again and use the right one.** Empirically: the agent has tried
`pywinauto__app_launch` to "open a browser" multiple times in test
runs. That tool launches Notepad. It will not navigate to qumall. Stop
and re-read the table.

**Domain split:**
- `chrome-devtools__*` = the **browser** (web pages, DOM, screenshots, JS evaluation)
- `pywinauto__*` = the **Windows desktop** (native windows, Win32 controls) — NOT loaded for this skill
- `excelio__*` = the **spreadsheet** (read / write xlsx)
- `bash` = the **shell** (run python scripts, file ops)
- `read_file` / `write_file` / `apply_patch` = the **source code repo** (only edit code, never xlsx)

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

## Stage 3 — Design cases into the blueprint (5-dimension coverage matrix)

For each module's UI surfaces (Stage 2) plus its sample bank (Stage 1.5),
design test cases **along 5 mandatory dimensions**. The agent must produce
a target **N ≥ 30 cases per module** (not 3-5 — that produces "冒烟" only).
If `sample_size < 30`, scale down proportionally but keep all 5 dimensions.

### 3.1 The 5 dimensions (mandatory, per module)

| Dim | Tag | Count per module | What it tests |
|---|---|---|---|
| **业务流 (Flow)** | `[流程]` `[正常]` | 6-10 | E2E happy: 商家入驻→审核→签约→设备→订单→分账→对账→提现;每环节 1-2 条 |
| **数据驱动 (Data)** | `[边界]` `[异常]` | 8-12 | 金额边界(0/0.01/99999.99/负数/小数位)/超长字符串(>255,>4000)/特殊字符(XSS/SQL 注入)/分页边界/跨年跨月 |
| **权限矩阵 (Perm)** | `[权限]` | 4-6 | ≥2 个角色的菜单可见性 + 按钮可点性 + 数据范围; 越权访问被拒 |
| **异常路径 (Except)** | `[异常]` `[并发]` | 6-8 | 网络中断/超时/服务降级/并发双开同一单据/状态机非法跃迁/已审回到待审 |
| **审计合规 (Audit)** | `[审计]` `[兼容]` | 4-6 | 操作日志产生/敏感字段脱敏(身份证/银行卡/手机号)/改密后旧 token 失效/多端互踢 |

每维度 title 必须以方括号标签开头（见下）。**禁止**冒烟式标题如 "页面正常加载"。

### 3.2 Title template (copy this style from sample bank)

```
[流程] <业务动作>:<预期结果>
[异常] <触发条件>:<系统响应>
[边界] <输入值>:<预期行为>
[权限] <角色>访问<资源>:<允许/拒绝+原因>
[审计] <操作>:<日志/脱敏检查点>
[并发] <同时操作>:<冲突处理>
```

Good (real style): `[流程] 商家资质审核通过→设备登记→充电订单→分账:全链路账目一致`
Bad (banned): `登录功能`、`页面正常显示`、`搜索功能正常`

### 3.3 Per-module design recipe

For each `(module, function)` pair:

1. Pull sample cases for `(module, function)` from `sample_bank` (Stage 1.5)
2. For each of the 5 dimensions, generate **≥ 1 case per function** (so a module with K functions → at least 5×K cases). If a dimension doesn't apply (e.g. 财务模块没"权限矩阵"因为人人能看自己账单), document the skip explicitly.
3. Cross-link via UI flow: if `[流程] 入驻审核` creates data that `[边界] 分页` displays, write the boundary case against THAT data
4. Mark `UI_selector` (col 16) per the Stage 2 enumeration

### 3.4 Build rows (excelio__append_rows, single batch per module)

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
        test_method,                       # 7  测试方法  场景法/等价类/边界值/...
        title,                             # 8  用例标题 **必须 [标签] 开头**
        preconditions,                     # 9  前置条件
        test_data,                         # 10 测试数据
        steps,                             # 11 测试步骤 "1. ...; 2. ...; 3. ..."
        expected,                          # 12 预期结果
        "auto",                            # 13 编写人
        "",                                # 14 执行结果
        "",                                # 15 备注
        primary_selector,                  # 16 UI_selector
        "",                                # 17 截图路径
    ]
    new_rows.append(row)

# 一次 append, 一模块一批; tools/MCP 节省 round-trip
excelio__append_rows(path=blueprint_path, sheet=1, rows=new_rows)
```

Priority distribution (rule of thumb, scale per module criticality):
- **高** 30% (blocking / financial / cross-module)
- **中** 50% (feature correctness)
- **低** 20% (cosmetic / UI consistency)

Test method distribution: 场景法 40% / 等价类+边界值 30% / 状态转换 15% / 错误猜测 15%.

### 3.5 Self-check before Stage 3 end

Before you emit the "stage 3 done" message, walk this checklist:

- [ ] Every module has cases in **all 5 dimensions** (or explicit skip reason)
- [ ] Title column starts with `[标签]` for 100% of cases
- [ ] At least 2 different user roles covered in permission cases
- [ ] E2E flow cross-module linkage: at least 1 case in 设备管理 references data from 入驻审核
- [ ] Total N ≥ 30 per module × M modules

If any check fails → **re-design** that module's cases before emitting.

### 3.6 Tell the user the blueprint path (do NOT block)

After all modules are designed, emit:
```
emit assistant_text: "蓝图已生成: <blueprint_path>\n共 N 条用例，覆盖 M 个模块 × 5 维度。开始执行..."
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

### 3.7 Reload the blueprint into memory

```
excelio__read_sheet(path=blueprint_path, sheet=1, range={"max_rows": 5000})
→ returns: [{row: 2, values: [...]}, ...]
```

Group by `(模块, 功能)` → `cases_by_module`. This is the execution queue for Stage 4.

---

## Stage 4 — Per-case execution

Iterate all cases in the blueprint, **one at a time**, in the matching module tab.

### 4.0 Mode B variant (replay existing cases)

In Mode B the "blueprint" is the **mirror xlsx** (16-col layout, no
UI_selector or 截图路径 columns). Writable columns are 14 (执行结果) and
15 (备注) only — col 17 does not exist in the mirror.

```
Per-case loop — drive via qumall-db, not by re-reading the xlsx/JSON:

1. Pop one case from the DB (source-ordered by sheet_row):
   bash: uv run python qumall-db/cli.py next-pending --db blueprints/qumall.db
   → returns:
     {
       "ok": true,
       "case": {
         "id": "test_017",
         "sheet_row": 18,
         "module": "基础功能",
         "function": "首页数据",
         "subfunction": "KPI",
         "title": "首页KPI卡片正常显示",
         "preconditions": "已登录后台",
         "test_data": "无",
         "steps": "1. 访问首页 ... 2. 查看KPI卡片 ...",
         "expected": "4个KPI卡片显示数据为0/0/0/0"
       },
       "remaining": 3590
     }
   If `case` is null, the queue is exhausted — go to Stage 5.

2. Execute the case (chrome-devtools__list_pages → select_page →
   navigate/click/fill/snapshot per case.steps). Apply Stage 4.1
   rules (target stability 2.2.1, captcha 4.5, etc.).

3. Determine 通过/失败/跳过 by comparing actual to case.expected.

4. Write back TWO places in parallel:
   a. qumall-db (in-flight execution store):
      bash: uv run python qumall-db/cli.py set --db blueprints/qumall.db \\
          --id <case.id> --status <通过|失败|跳过> --note "<≤200 chars>"
      → returns {"ok": true, "id": "...", "status": "...", "note_len": N}
   b. mirror xlsx (final visible result for QA opening in Excel):
      excelio__update_cells(path=mirror_path, sheet=1, updates=[
        {row: <case.sheet_row>, col: 14, value: "<status>"},
        {row: <case.sheet_row>, col: 15, value: "<note>"},
      ])
      # DO NOT touch col 17 (no 截图路径 column in the 16-col mirror)
      # DO NOT write to 测试用例.xlsx (read-only)

5. Verify both writes succeeded:
   - cli.py set returns ok=true → DB updated
   - update_cells response has written=2 rejected=0 → xlsx updated.
     If rejected > 0 the write was refused (col 17 attempted, or row
     out of range); the `summary` field explains.

6. Update UI:
   report_progress(done=<done+1>, total=<total>,
                   failed=<stats.by_status["失败"]>, module=<case.module>)
   When the LAST case of a module finishes:
   report_module_status(module=<case.module>, state="passed" | "failed")

7. Loop back to step 1.

8. If the loop ends naturally (next-pending returns case=null) OR a
   case is permanently blocked, call:
   bash: uv run python qumall-db/cli.py stats --db blueprints/qumall.db
   → use this for the Stage 5 final report.
```

The mirror preserves the original 16-col header that QA uses in Excel, so
the result writes land on the columns they expect. The user can open the
mirror in Excel and see the run results inline with the original cases.

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
state. Your first action on resume should be:

```bash
# 1. Check what's still pending
uv run python qumall-db/cli.py stats --db blueprints/qumall.db

# 2. Continue from next-pending — it returns the lowest sheet_row
#    whose status is NULL, ignoring already-finished rows.
uv run python qumall-db/cli.py next-pending --db blueprints/qumall.db
```

The DB is the source of truth for "what to run next" — DO NOT re-scan
the mirror xlsx for empty col 14 to find the next row. Re-importing the
xlsx WITHOUT `--reset` is also safe: it preserves prior status/note.

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
