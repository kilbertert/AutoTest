---
name: web-test-runner
description: |
  Generic web admin / dashboard UI test runner. Use this skill when the user
  says "测试 https://example-admin.com 的所有功能" / "把我写的 100 条测试用例在 xxx 后台跑一遍" /
  "用我的测试用例回归 xxx 系统" / "探索这个网站然后按测试用例挨个执行" / "full regression on this
  admin panel with my xlsx cases" / "接着上次的进度继续跑" / "resume the test run from
  sheet_row 1234".

  Long-running: built-in checkpoint/resume so a fresh Claude Code session
  can pick up where a previous one left off. Multi-machine: multiple
  Claude Code sessions can share the same case DB via SQLite's atomic
  UPDATE; case-level deduplication prevents double-execution.

  Workflow: ① Input → ② Explore (write manifest) → ③ Plan (match steps to
  selectors) → ④ Execute (one case at a time, checkpoint after each).
  See the "Long-running, multi-session, multi-machine execution" section
  for the persistence layout and resume algorithm.

  Generic — works against ANY web admin (charging-pile CMS, CRM, ERP, OA, etc.),
  not bound to any specific business system.

  Required MCP servers:
    chrome-devtools  — drives the browser
    excelio         — reads .xlsx case files (Stage ② only if xlsx input; otherwise
                      read cases from a SQLite queue built during planning)

  Optional input:
    Test cases (.xlsx with 16-col template) OR a pre-built SQLite queue built by the
    user via qumall-db/cli.py.
---

# web-test-runner — Generic UI Test Runner

A skill for **systematic, real, end-to-end UI testing** of any web admin / dashboard.
The agent (Claude Code) becomes the runner: it observes, decides, executes, and
records honest results.

## Why this exists (and why it is structured this way)

Earlier ad-hoc attempts to run 3000+ UI cases by chaining LLM prompts against
chrome-devtools-mcp produced **0 passed** in two days of debugging, for three
recurring reasons:

1. **Premature execution.** The agent jumped straight to "run case 1" without
   first mapping the target site, so it could not find the right menu or
   selector — and instead of saying "I don't know how to navigate here", it
   mass-skipped every case and lied about "16 passed" in the final report.
2. **No stable work artifact.** Every case was inferred from scratch, so the
   same menu was re-discovered 3000 times, costing tool calls and producing
   inconsistent results.
3. **Forced honesty.** Earlier runs wrote pass/fail/skip without grounding in
   a UI snapshot, so the reported results did not match what the browser
   actually showed.

This skill fixes all three by mandating a **manifest** (machine-readable site
map) that the agent consults before every action, and a **strict
explore → plan → execute → report** pipeline with checkpoints.

---

## Inputs (always ask the user up front)

| Variable | Required? | What it means | Default if missing |
|---|---|---|---|
| `target_url` | yes | The web app's URL | — |
| `login_username` | yes | Username for login | — |
| `login_password` | yes | Password for login | — |
| `cases_xlsx` | optional | Path to a `.xlsx` of test cases (16-col template) | if missing, run in "exploration only" mode |
| `cases_db` | optional | Path to a pre-built SQLite queue (`qumall.db` schema) | defaults to `<cwd>/.web-test-runner/cases.db`; auto-built from xlsx if xlsx is given |
| `manifest_path` | optional | Where to store/read the site map | `<cwd>/.web-test-runner/manifest.json` |
| `results_path` | optional | Where to write the final results table | `<cwd>/.web-test-runner/results.json` |
| `report_md_path` | optional | Markdown report for humans | `<cwd>/.web-test-runner/REPORT.md` |
| `extra_login_selectors` | optional | non-standard login form (captcha, MFA, etc.) | — |

If the user gave only the URL and creds (no xlsx), say:
"未提供测试用例。我会先探索站点 + 标记可交互点，写成 manifest。是否要我顺手生成 ~30 条覆盖各菜单的探索性测试用例？"

---

## The 4-Stage Pipeline

```
   ┌──────────────────────────────────────────────────────────────┐
   │  Stage ① Input                                               │
   │   - Parse URL / creds / xlsx (if any) / DB (if any)         │
   │   - Verify chrome-devtools MCP is reachable                  │
   │   - Init case DB (if xlsx given)                             │
   └────────────────┬─────────────────────────────────────────────┘
                    ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  Stage ② EXPLORE — build the manifest                        │
   │   For each top-level menu:                                   │
   │     - open the menu, hover/click every sub-item             │
   │     - record: route hash, page title, form fields,           │
   │       tables, buttons, modals, status indicators             │
   │     - capture the page snapshot (text only, no full HTML)    │
   │   Persist the manifest as a JSON file at manifest_path.      │
   │                                                              │
   │   Hard rule: never read source files / run xlsx tools here   │
   │   unless the user said "skip the xlsx, just explore".       │
   │                                                              │
   │   Output: a deterministic site map the next stages trust.   │
   └────────────────┬─────────────────────────────────────────────┘
                    ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  Stage ③ PLAN — match cases → selectors                      │
   │   For every test case (row in xlsx / row in DB):             │
   │     - Parse col 11 (steps) into ordered ops                  │
   │     - For each op, find the matching element in manifest     │
   │       (by route / menu path / button text / form field       │
   │       label). If ambiguous → mark case as "needs_disambig".  │
   │     - Write a per-case execution_plan (route, ordered        │
   │       actions, expected-result keys) into the DB.            │
   │                                                              │
   │   Skip-planning rules:                                       │
   │     - Pure "view list renders" cases → auto-pass if manifest │
   │       shows the list exists with rows > 0 in the snapshot    │
   │     - Pure "missing menu / 404" cases → auto-fail if        │
   │       manifest shows the route resolves but page is blank    │
   │     - Anything that needs login + button click + form fill  │
   │       → full plan required                                 │
   └────────────────┬─────────────────────────────────────────────┘
                    ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  Stage ④ EXECUTE — run each case and write the truth         │
   │   For each case, in source order:                            │
   │     a. Navigate to the planned route (via menu click, not    │
   │        hash — many SPAs only respond to menu clicks)         │
   │     b. Verify pre-state (e.g. logged in, store selected)     │
   │     c. Perform planned actions (click / fill / submit)      │
   │     d. Compare actual result to case.expected                │
   │     e. Capture screenshot on failure                         │
   │     f. Write back: DB + (if xlsx) col 14/15 + REPORT.md     │
   │                                                              │
   │   Strict honesty:                                            │
   │     - "通过" only if actual matches expected                 │
   │     - "失败" if actual diverges from expected                │
  │     - "跳过" only for: no permission / menu missing /        │
  │       captcha needed / case needs data not present           │
   │   Never lie about counts. Never write a pass without a      │
   │   matching page snapshot to cite.                           │
   └──────────────────────────────────────────────────────────────┘
```

---

## The Manifest — the central artifact

The manifest is **machine-readable JSON** that captures everything the runner
needs to execute without re-discovering the site on every case. It is written
during Stage ② and consulted during Stages ③ + ④.

### Manifest schema (high level)

```jsonc
{
  "target_url": "https://admin.example.com/",
  "login": {
    "route": "/login",
    "username_field": { "selector": "input[name=username]", "uid_observed": "12_3" },
    "password_field": { "selector": "input[name=password]", "uid_observed": "12_4" },
    "captcha_field": null,
    "submit_button":   { "selector": "button.login-btn",     "uid_observed": "12_5" },
    "post_login_url_pattern": "#/wel/"
  },
  "preconditions": [
    {
      "id": "select_store",
      "description": "页面顶部有'请选择店铺'下拉框，必须先选具体店铺（不选的话，所有 tab 内容为空）",
      "trigger_after_login": true,
      "selector": "input[placeholder='请选择店铺']",
      "options": ["全部", "site-A", "site-B"],
      "default_to_pick": "site-A",
      "uid_observed": "14_49"
    }
  ],
  "menus": [
    {
      "path": ["内容", "公告/协议", "协议列表"],
      "route": "#/operate/contentmanager/Notice/greementList",
      "page_title": "协议列表",
      "controls": {
        "search_input":  { "selector": "input[placeholder='请输入内容']", "uid_observed": "16_13" },
        "search_button": { "selector": "button:has-text('查询')",        "uid_observed": "16_14" },
        "add_button":    { "selector": "button:has-text('新 增')",       "uid_observed": "16_10" },
        "batch_delete":  { "selector": "button:has-text('批量删除')",   "uid_observed": "16_11" }
      },
      "table": {
        "headers": ["协议名称", "协议ID", "是否启用", "添加时间"],
        "row_count_at_explore_time": 0,
        "empty_state_text": "暂无数据"
      }
    }
  ],
  "global_rules": [
    "店铺选择器必须先选具体店铺，所有 tab 内容才加载",
    "菜单点击只创建空 tab，必须等 SPA 路由完成",
    "hash URL 跳转不可靠 — 用菜单点击而非 navigate_page 到 hash"
  ],
  "explored_at": "2026-07-09T18:35:00Z",
  "explore_duration_seconds": 600,
  "notes": [
    "店铺'全部'状态下，所有具体模块 tab 内容为空",
    "Element UI tab-pane 用 lazy mount，菜单点击后立即 snapshot 可能看不到内容，需要 wait_for"
  ]
}
```

The `uid_observed` field is brittle (changes between snapshots). It exists for
**first-time execution reference only**. The agent should re-snapshot the page
on each case and use the **selector** (text/role-based) for actual clicks, not
a stale uid.

### Manifest re-use rule

- If `manifest_path` exists at start, **load it first** and only re-explore the
  menus that are missing or marked stale. Re-exploration is incremental.
- If `manifest_path` is missing, run the full exploration. Save it.
- Always commit the manifest to git (it is a small JSON file, <100KB usually).

---

## Login + Precondition Pattern (CRITICAL — get this right)

Most admin systems have **post-login preconditions** that are easy to miss and
that, if missed, cause every case to silently fail. Common ones:

1. **Store / tenant selector.** A dropdown at the top of the dashboard that
   says "All" or "请选择店铺". Clicking "All" or leaving it blank often makes
   the backend return empty data → every case sees "暂无数据" and gets
   skipped. **Always pick a specific store before running cases.**
2. **First-run wizard.** "Complete your profile" / "Bind phone" / "Set 2FA".
   Skip these if the user has a pre-baked test account.
3. **Modal overlay.** Some sites have a "Welcome to the new version!" modal
   that intercepts all clicks. Close it explicitly before starting.
4. **Cookie banner.** Same idea — dismiss it before navigating.

The exploration stage should **always document these preconditions in the
manifest** so that the executor can re-apply them on every fresh session.

**Real example from a production run** (the bug we hit):
- After login, a "请选择店铺" dropdown defaulted to "全部"
- Every menu's tab content was empty when "全部" was selected
- The earlier LLM runner kept finding empty pages and mass-skipped every case
- Fix: in manifest.preconditions, record this and have the executor click a
  specific store before each case

---

## xlsx Case Schema (when input is .xlsx)

Standard 16-col template (Excel merged cells: 模块 cascades down):

| col | name | use |
|---|---|---|
| 1 | 用例ID | identifier (may be reused across modules) |
| 2 | 项目 | (skip) |
| 3 | 端口 | (skip) |
| 4 | **模块** | menu path anchor (cascade) |
| 5 | 功能 | sub-menu |
| 6 | 子功能 | (optional) |
| 7 | 优先级 | (skip) |
| 8 | 测试方法 | (skip) |
| 9 | 用例标题 | human description |
| 10 | 前置条件 | (consume) |
| 11 | **测试步骤** | the ops to perform |
| 12 | **预期结果** | the assertion |
| 13 | 编写人 | (skip) |
| 14 | 执行结果 | WRITABLE — 通过 / 失败 / 跳过 |
| 15 | 备注 | WRITABLE — failure reason, ≤200 chars |
| 16 | (optional) screenshot path | WRITABLE — failure screenshot |

Step parsing rules:
- If step text contains ";"  → split on ";"
- If step text contains "1. ... 2. ..." → split on numbered bullets
- Each piece is one op. Ops are ordered.

Expected parsing rules:
- If expected contains ";" → split on ";"
- Each piece is one assertion. Match them in order against the post-action
  page state.

---

## Stage ② EXPLORE — how to drive chrome-devtools-mcp

For each top-level menu, in order:

1. **Click the top-level menu** (using its a11y name from `take_snapshot`)
2. **Wait** for the submenu to expand (check via snapshot that the next
   level of `menuitem` nodes exists)
3. **Click each submenu item**, in order
4. **Wait for the new page** (`wait_for` on a known page header text)
5. **Take a snapshot** of the resulting tabpanel
6. **Record in the manifest**:
   - The route hash from `window.location.hash`
   - The page title
   - Every form field (`textbox`, `combobox`, `switch`)
   - Every button (`button`)
   - The table structure (headers, first row sample, empty-state text)
   - Any modals / overlays / alerts
7. **Click back / close / home** to return to a clean state before the next menu

If a menu produces an empty tabpanel:
- Re-snapshot. Maybe it's lazy-mounted; wait 5s.
- Check if the user has the right permission (look at any "403 / 无权访问" text)
- Check if a precondition (e.g. store selector) is missing
- Record all of the above in `manifest.notes[]` for that menu

### Anti-patterns during exploration

- **Do not** try to login again from a sub-page — login is a one-time step.
- **Do not** submit forms during explore unless the user explicitly asked.
- **Do not** click delete buttons. Click "view" / "details" only.
- **Do not** write to disk except the manifest itself.

---

## Stage ③ PLAN — matching cases to selectors

For each case in the source DB:

```python
def plan_case(case, manifest):
    ops = parse_steps(case.steps)        # list of op strings
    expected = parse_expected(case.expected)

    route = find_route(case.module, case.function, manifest)  # by menu path
    if not route:
        return Plan(skip_reason="menu_not_found",
                    note=f"manifest has no route for '{case.module} / {case.function}'")

    actions = []
    for op in ops:
        sel = match_op_to_selector(op, route.controls, manifest)
        if sel:
            actions.append({"op": op, "selector": sel})
        else:
            return Plan(skip_reason="selector_not_found",
                        note=f"op '{op[:40]}' has no match in route '{route.path}'")

    return Plan(route=route.route, actions=actions, expected=expected)
```

`match_op_to_selector` heuristic:
- "新增" / "添加" / "Create" / "Add" → button with text match
- "搜索" / "查询" / "Search" → search input + button pair
- "点击 X 菜单" → check that `X` exists in `manifest.menus[].path[]`
- Form field references ("输入框", "密码框") → check `controls` for `<input>`
- Anything ambiguous → mark `needs_disambig` and ask the user **once** before
  proceeding (do not block the whole run for one ambiguous case)

---

## Stage ④ EXECUTE — running each case

For each case, in source order:

```
1. Apply all manifest.preconditions (e.g. select store "site-A")
2. Navigate to the planned route (prefer menu click; fall back to hash URL only
   if you confirm it works for this site)
3. Wait for the page to settle (wait_for on a stable header text)
4. For each planned action:
     - take_snapshot to get a fresh uid
     - click/fill by selector (not by uid, which is ephemeral)
     - on success, continue; on failure, retry once; on second failure,
       mark case as 失败 with the snapshot evidence
5. After all actions: snapshot the page state
6. Compare to expected. If matched → 通过. Else → 失败. With note.
7. Write back:
     a. cases_db (UPDATE cases SET status=?, note=?, updated_at=?)
     b. xlsx col 14/15 (using excelio if xlsx was the input)
     c. Append to REPORT.md
```

**Status values (strict — these are the only legal values):**
- `通过` — actual matches expected
- `失败` — actual diverges from expected
- `跳过` — cannot execute: no permission / menu missing / captcha / data absent /

**Status string MUST be Chinese** — many CLI helpers reject English variants.

---

## When to STOP and ask the user

Only stop for:

1. **Captcha / MFA** that requires the user to type — pause, ask the user to
   enter it, resume. Do NOT OCR.
2. **Critical precondition** the user did not tell you about (e.g. their 2FA
   device is needed). Pause once at the top, then proceed.
3. **More than 5 consecutive failures** in the same module — pause, show
   user the failing cases, ask if they want to continue or skip the module.
4. **A case that creates real business data** (add / delete / update) — warn
   the user once at the start of the run, and use a "test-" prefix for any
   created data. Confirm before delete operations.

Do NOT pause for: slow pages, transient failures (retry once), one-off missing
selectors (mark the case and continue).

---

## Output Files

After a run completes, the runner produces:

| File | Contents |
|---|---|
| `<manifest_path>` | The site map (kept; reused next run) |
| `<cases_db>` | Per-case status / note (the truth) |
| `<results_path>` | Aggregated JSON (counts, per-module pass rates, top failures) |
| `<report_md_path>` | Human-readable Markdown report |
| (optional) `<xlsx>` | Updated col 14 / 15 in the user's source xlsx |

The Markdown report should include:

- Global totals: total / passed / failed / skipped
- Per-module pass rate table
- Top failure reasons (grouped by `note`)
- For every case: its verdict and the snapshot evidence (one-line description
  of what the page looked like when the verdict was decided)
- A note about any preconditions that had to be re-applied

---

## Hard rules (read these or break things)

1. **Never lie about pass/fail.** A case is 通过 only if the page state after
   the actions matches the expected. If you cannot confirm, it is 失败 or
   跳过 — never 通过.
2. **Never reset the cases DB** between runs. Earlier (broken) code wiped
   results via `--reset`; do not reintroduce that. If a re-run is needed,
   only update rows whose status is NULL.
3. **Always apply preconditions before each run.** The store selector / MFA
   / cookie banner must be applied on every fresh session.
4. **Never OCR captchas.** Pause and ask the user.
5. **Use menu clicks, not hash URLs.** Many SPAs only respond to menu clicks;
   `navigate_page` to a hash URL may silently no-op.
6. **Use text/role selectors, not stale uids.** Uids from `take_snapshot` are
   ephemeral. Selectors are stable.
7. **Write status in Chinese** (`通过 / 失败 / 跳过`). English variants are
   silently rejected by the case DB layer.
8. **Capture evidence on failure.** A failure without a screenshot or note
   is not a real failure — it's a guess. Always cite the snapshot.
9. **The manifest is the source of truth** for selectors and routes. Do not
   re-discover the site on every case.
10. **Single-store constraint.** Pick ONE store at the start of the run and
    stick to it. Mixing stores across cases produces nonsense results.

---

## Known unknowns (surface these to the user immediately)

- **The user's actual store / tenant / org.** If the site has a store
  selector, you must ask which store to test against. Do not assume "全部" —
  that usually returns empty data.
- **Whether their test cases include write operations** (create / update /
  delete). If yes, warn once before the run starts and ask whether to use
  a `test-` prefix on created data.
- **Whether the site requires MFA / captcha** that the user must interact
  with. If yes, plan for one mid-run pause.
- **What to do if a menu's tabpanel is empty.** This is usually (a) wrong
  store, (b) missing permission, (c) lazy-mount not triggered. Try (a)
  first — pick a different store.

---

## Worked example: the trap we hit and how this skill avoids it

> Earlier run, day 1: agent clicked "协议列表", got an empty tabpanel,
> mass-skipped 15 cases, reported "all skipped due to missing menu".
> User asked "why?" — root cause: the user had a store selector defaulted
> to "全部" and the page only loaded content when a specific store was
> picked.

With this skill, Stage ② would have:
1. Logged in, observed the "请选择店铺" dropdown defaulted to "全部".
2. Recorded this as a `manifest.preconditions[]` entry.
3. Recorded in `manifest.global_rules[]` that "全部" mode returns empty data.
4. Picked a specific store and re-explored.
5. Re-confirmed that all menus now load correctly.
6. Saved this in the manifest so the next run doesn't trip on it.

Stage ④ would then apply the store precondition on every fresh session.

---

## Quick start (what the agent should do right after this skill loads)

```text
1. Greet the user; ask for: target_url, login_username, login_password,
   cases_xlsx (optional), store_to_test (optional).
2. Open Chrome via chrome-devtools-mcp; verify connectivity.
3. If a manifest exists at <cwd>/.web-test-runner/manifest.json, load it.
   If not, start Stage ②.
4. Stage ②: explore every menu, build the manifest. Save.
5. Stage ③: if xlsx given, import it into the cases DB; plan every case.
   If no xlsx, propose 30 exploration cases for the user.
6. Stage ④: run each case. Write back to DB + xlsx + REPORT.md.
7. Final summary in the chat, plus paths to all artifacts.
```

The skill should be invoked by name (`web-test-runner`) and its instructions
above should be followed strictly. The runner is the agent itself — Claude
Code becomes the runner, the LLM does not automatically spawn another agent
to do the work.

---

# Long-running, multi-session, multi-machine execution

Running 3000+ UI cases does not fit in a single Claude Code session. A
single session's context window fills up after roughly 15-30 cases (each
case consumes ~5K-15K tokens: snapshot + click + fill + assertion). The
**practical** way to run thousands of cases is a **checkpoint / resume**
loop combined with optional multi-machine parallelism.

## The core idea: persist everything, resume from where you left off

Three pieces of state must survive across sessions:

1. **`manifest.json`** — the site map. Re-exploring from scratch wastes hours.
2. **`cases.db`** — the case queue with per-row `status` and `note`. This is
   the truth.
3. **`checkpoint.json`** — a tiny file recording "the next case to run" so
   a new session can resume immediately without re-scanning the DB.

```
.cases_runner/
├── manifest.json           # site map (from Stage ②)
├── cases.db                # case queue + per-case status (from Stage ③)
├── checkpoint.json         # { last_case_row, last_module, total_run, started_at }
├── REPORT.md               # cumulative human report
└── screenshots/            # failure screenshots, named <sheet_row>.png
```

`checkpoint.json` schema:

```json
{
  "started_at": "2026-07-09T10:00:00Z",
  "last_updated": "2026-07-09T10:18:00Z",
  "last_case_sheet_row": 1234,
  "last_module": "FAQ",
  "total_cases": 3590,
  "cases_done_this_session": 27,
  "cases_done_total": 261,
  "session_id": "host-A-2026-07-09T10:00:00Z"
}
```

## Stage ④ with checkpointing — concrete algorithm

```text
For each case (in source order, by sheet_row):
    1. Read the case row from cases.db
    2. If status is already '通过' / '失败' / '跳过' → skip (it's done)
    3. Apply manifest.preconditions (select store, dismiss modals, etc.)
    4. Navigate to the planned route via menu click
    5. Execute the planned actions
    6. Compare actual to expected
    7. Write status + note back to cases.db IMMEDIATELY (single-row UPDATE)
    8. Append one row to REPORT.md
    9. Update checkpoint.json: { last_case_sheet_row: <this>, last_updated: now, ... }
   10. On any chrome-devtools error / Target closed → retry the case once
       after re-selecting the page; on second failure → mark '失败' and move on.
   11. After every 10 cases → run a "soft checkpoint" that re-loads the
       manifest and re-selects the store (preventive, not corrective).

Soft limits:
  - Stop the session after 30 minutes OR 25 cases OR if the user hits
    Ctrl+C. The checkpoint.json already has the next row, so a new
    session can resume cleanly.
  - Do NOT try to do "one more case" past these limits — pushing past
    them risks losing the run to context exhaustion.
```

## Resuming in a new session

When the user starts a fresh Claude Code session and invokes this skill,
the agent MUST check for `.cases_runner/checkpoint.json` first:

```text
If checkpoint.json exists:
  - Read it. Note last_case_sheet_row + last_module + cases_done_total.
  - Confirm the manifest is loaded (load it if not).
  - Apply preconditions (re-login if needed; re-select store).
  - Continue from the next un-executed case after last_case_sheet_row.
  - Tell the user: "Resuming from sheet_row <X>, <Y> cases already done."

If checkpoint.json does NOT exist but cases.db does:
  - Same as above but use cases_db directly: find the lowest sheet_row
    with status IS NULL, that is the resume point.

If neither exists:
  - This is a fresh run. Start from Stage ② (explore).
```

## Multi-machine parallelism — the safe way

Each machine runs its own Claude Code session. They share **only two
files** on a writable share:

- `cases.db` (SQLite) — per-case status / note
- `manifest.json` (read-only after Stage ② completes)

**Coordination rule**: never two machines run the same case at once. The
way to enforce that is **case-level atomicity**, not machine-level:

- The session queries `cases.db`: `SELECT * FROM cases WHERE status IS NULL
  ORDER BY sheet_row LIMIT 1` (highest priority un-done case).
- It begins work on that case.
- It does NOT lock the row. Instead, before writing the result, it does:
  `UPDATE cases SET status=?, note=? WHERE sheet_row=? AND status IS NULL`.
  If two machines pick the same case, only one of the UPDATEs will affect a
  row (the other's UPDATE will silently no-op because status is no longer
  NULL). The losing machine re-queries and picks the next case.

**Important**: SQLite supports this if the DB is on a network share, but
only if every writer uses WAL mode + a short busy_timeout. The agent
should set this on DB open:

```sql
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;
```

If two machines still collide (e.g. on SMB which is finicky with WAL), fall
back to per-machine shard files (`cases-A.db`, `cases-B.db`) and merge
results at the end. The skill should detect this and warn the user.

## What the skill MUST do on every session start

```text
1. Load manifest.json (or run Stage ② if missing).
2. Load checkpoint.json (if present) → note resume point.
3. Open Chrome via chrome-devtools-mcp.
4. Apply preconditions (login if needed, select store, dismiss modals).
5. Sanity check: take a snapshot of the dashboard. Confirm we are logged
   in and the store is correct. If not, stop and ask the user.
6. Pick the next case from cases.db.
7. Run it.
8. Write back.
9. Repeat until 30-min / 25-case / user-stop limit, then exit cleanly
   (checkpoint.json is already up-to-date).
```

## What the skill MUST do on every case

```text
1. Read case from cases.db by sheet_row.
2. If already done (status NOT NULL) → skip, move on.
3. Re-snapshot the page (don't trust stale snapshots).
4. Apply the planned actions, one click/fill per tool call.
5. Take a final snapshot and compare to expected.
6. Write back to cases.db (single UPDATE, atomic).
7. Update checkpoint.json (single atomic write).
8. Append to REPORT.md.
9. Move on. Do not "look back" at previous cases unless the user asks.
```

## Why this approach works

- **Single-session context** stays bounded (~25 cases / ~30 min).
- **Cross-session state** is 100% on disk (DB + manifest + checkpoint).
- **Multi-machine parallelism** is safe because SQLite's atomic UPDATE
  prevents double-execution.
- **Crash recovery** is automatic — restart anywhere, resume from checkpoint.
- **Honest reporting** — the DB is the truth; the report is a view.

## Why NOT to use subagents inside one session for parallelism

Subagents share the parent's chrome-devtools connection. Two subagents
calling `take_snapshot` at the same time will collide on the same Chrome
tab. Even sequential subagents consume parent context. The
checkpoint/resume + multi-machine approach is strictly better.

Use subagents only for **independent, read-only** subtasks (e.g. "fetch
this URL's HTML and summarize it") — never for sharing a browser.

## What to tell the user about expected runtime

```
Single session:  25 cases / 30 min
Single machine:  8 sessions/day × 25 cases = ~200 cases/day
3 machines:      600 cases/day
3590 cases:       ~6 days on 3 machines, ~18 days on 1 machine
```

These numbers assume ~60-90 seconds per case (the realistic upper bound
when including login retry + store-select + menu-click + form-fill + assert).
Empirical runs will likely be 30-60 seconds per case after Stage ② lands.

## A note on context-window economics

Each case consumes roughly:
- 1 take_snapshot (1-3K tokens output)
- 1-3 click/fill calls (small each)
- 1 final take_snapshot (1-3K tokens)
- Reasoning text (1-3K tokens)

Plus per-session overhead: manifest load, login, precondition application,
checkpoint read. Budget ~5-15K tokens per case.

At 200K tokens / 10K per case ≈ 20 cases per session. The "25 cases / 30
min" budget above is conservative; tighter cases may push to 30-40 per
session. The hard ceiling is the user's patience and the per-session cost.

## Migration path from the old (failed) approach

The previous multi-machine pool (now removed) tried to use a `qumall-pool`
coordinator. That approach failed because:

1. The runner was an LLM agent that wrote 0 passing cases.
2. The coordinator added complexity without solving the real problem
   (LLM-as-runner cannot navigate unknown SPAs reliably).

This skill replaces both with: **Claude Code IS the runner**, the manifest
IS the knowledge, the checkpoint IS the persistence, the cases DB IS the
shared truth. No external coordinator, no LLM spawned from a Python
subprocess.