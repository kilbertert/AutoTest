---
name: chrome-devtools-mcp
description: Drive a real Chrome browser via the official Chrome DevTools MCP server. Use when the user wants to test a **web UI**, automate browser interactions, take screenshots, run JS in a page, or do anything that needs DOM/JS access — for example "测试 qumall 后台的登录页", "打开 https://example.com 截图", "在当前页面点击登录按钮", "提取这个网页的所有链接". This skill is a thin reference for the chrome-devtools-mcp tool surface; for a multi-stage "explore → design → execute → report" workflow see the `qumall-fulltest` skill.
---

# Chrome DevTools MCP — Browser Automation

## When To Use

The user wants to **drive a real Chrome browser** through CDP (Chrome DevTools Protocol). The MCP server launches its own Chrome instance (or attaches to one via `--browserUrl`) and exposes DOM/network/JS/screenshot tools. This is the right tool for:

- Web UI automation (clicks, fills, form submission, navigation)
- Page content extraction (accessibility snapshot, HTML, JS evaluation)
- Visual checks (full-page screenshots, element screenshots for OCR/visual comparison)
- Network inspection (request/response capture, status codes, headers)

This is **NOT** the right tool for:
- Pure backend API testing → use `api-mcp` or `apifox-mcp` instead
- Native Windows desktop automation → use `pywinauto-mcp` instead
- Headless data scraping at scale → prefer `httpx` via `bash` + a Python script

## How the server is wired

- npm package: `chrome-devtools-mcp` (Google official, stdio transport)
- Launched by `npx -y chrome-devtools-mcp@latest` from `~/.trendpower/mcp_servers.json`
- Default args assume `chrome-devtools` server entry with no flags → server spawns an isolated Chrome at startup
- Chrome ≥ 144 required (check `chrome://version`)
- All tools are namespaced `chrome-devtools__<tool>` (per MCP tool-prefix convention)

**If tools fail with "Chrome not found":** install Chrome ≥ 144 stable, or pass `--executablePath "C:\Program Files\Google\Chrome\Application\chrome.exe"` in `args`.

**If Chrome starts but no pages are visible:** chrome-devtools-mcp launches its own isolated profile unless `--userDataDir` is set. To persist login state across runs, set `--userDataDir <fixed-path>` in the server `args` and use that same path every run.

## Tool reference

> **Naming convention:** all tools are exposed as `chrome-devtools__<tool>` (e.g. `chrome-devtools__navigate_page`). The `<tool>` part is what's listed below.

### Navigation & pages

| Tool | Purpose |
|---|---|
| `navigate_page(url)` | Go to a URL. Waits for `load` event by default. |
| `new_page(url?)` | Open a new tab (preserves cookies/storage of existing profile). Use one tab per module under test. |
| `list_pages()` | List all open tabs with `{pageId, url, title}`. |
| `select_page(pageId)` | Switch the active tab — all subsequent tools operate on it. |
| `close_page(pageId)` | Close a tab. |
| `wait_for(text?, selector?, timeoutMs?)` | Block until text appears in DOM, an element matches a CSS selector, or timeout. |
| *(no `reload` / `go_back`)* | Use `evaluate_script("location.reload()")` or `evaluate_script("history.back()")`. |

### DOM inspection

| Tool | Purpose |
|---|---|
| `take_snapshot()` | Returns an accessibility tree (preferred for AI — concise, structured, role-based). Default for understanding page structure. **Also the primary way to get a `uid` for `click`/`fill`/`hover`.** |
| `evaluate_script(expression)` | Run arbitrary JS in the page context, return the value (must be JSON-serializable). For data extraction and for locating elements when no `find` exists. |
| *(no `find`)* | chrome-devtools-mcp has no standalone `find` tool. To locate an element: (a) call `take_snapshot()` and read the `uid` of the node you want, or (b) use `evaluate_script("document.querySelector('...')")` to verify a selector exists, then reference it via snapshot. |
| *(no `get_html`)* | Use `evaluate_script("document.querySelector('...').outerHTML")`. |

### Interaction

| Tool | Purpose |
|---|---|
| `click(uid, ...)` | Click an element identified by `uid` from `take_snapshot()`. |
| `fill(uid, value)` | Set a single input's value (clears first). For text/number/email inputs. |
| `fill_form(values)` | Fill multiple form fields in one call (preferred for forms with > 2 fields). |
| `type_text(uid, text)` | Type characters one-by-one into a focused field. Useful for autocomplete / special keys. |
| `hover(uid)` | Hover an element (triggers hover-only UI). |
| `press_key(key)` | Press a special key (`Enter`, `Tab`, `Escape`, `ArrowDown`, etc.). |
| `drag(fromUid, toUid)` | Drag-and-drop from one element to another. |
| `upload_file(uid, paths)` | Set files on a `<input type=file>` element. `paths` is an absolute-path list. |
| `handle_dialog(accept, promptText?)` | Accept/dismiss a JS `alert`/`confirm`/`prompt` dialog. |
| *(no `select_option`)* | Use `evaluate_script("document.querySelector('select').value = 'x'; dispatchEvent(new Event('change'))")` or `fill`. |

### Screenshots & visual

| Tool | Purpose |
|---|---|
| `take_screenshot(format?, quality?, maxWidth?, maxHeight?, fullPage?, uid?)` | Capture screenshot. PNG by default; JPEG/WebP smaller (better for AI context). Pass `uid` to screenshot one element (e.g. a captcha image). Returns base64 in `data` field plus a `filePath` if saved to disk. |

### Network

| Tool | Purpose |
|---|---|
| `list_network_requests(filter?, pageId?)` | All requests since navigation. |
| `get_network_request(requestId)` | Detail (headers, body, response). |

### Console

| Tool | Purpose |
|---|---|
| `list_console_messages(pageId?)` | All console messages since navigation (errors/warnings/logs). |
| `get_console_message(messageId)` | Detail of one console message. |

### Emulation

| Tool | Purpose |
|---|---|
| `resize_page(width, height)` | Resize the current tab. Use 1280×720 default; some admin backends need ≥ 1440 wide. |
| `emulate(device?)` | Emulate a device (iPhone, Pixel, etc.). |

### Performance / advanced (use only when needed)

| Tool | Purpose |
|---|---|
| `performance_start_trace` / `performance_stop_trace` / `performance_analyze_insight` | Performance tracing. |
| `lighthouse_audit(url)` | Run a Lighthouse audit (slow — seconds to minutes). |
| `take_heapsnapshot()` | Capture a JS heap snapshot (large output). |

## Best practices

1. **Always `take_snapshot()` before clicking** — `click(uid)` needs a uid from the most recent snapshot. UIDs are stable for the snapshot they came from.
2. **Prefer accessibility tree over HTML** — `take_snapshot()` is 5-10× smaller than `get_html()` (which doesn't exist here — use `evaluate_script` for raw HTML) and semantically structured.
3. **One tab per logical context** — login flow, search flow, checkout flow each get their own tab. Reduces noise from concurrent UI states.
4. **No `find` tool — use snapshot uids** — chrome-devtools-mcp has no standalone `find`. Locate elements by reading `take_snapshot()` output and using the node's `uid`. For CSS-only matching, `evaluate_script("document.querySelector('...')")` to verify existence, then re-snapshot to get a uid.
5. **`wait_for()` after navigation and click** — many admin backends have lazy-loaded sections; without `wait_for` you may click on a stale snapshot.
6. **Pass `fullPage: true` to `take_screenshot` only when needed** — full-page screenshots are 5-10× larger. For element checks, pass `uid` instead.
7. **Network inspect for AJAX testing** — `list_network_requests` + `get_network_request` is the right way to verify background API calls (POST /api/login → 200 with token) without parsing the rendered DOM.
8. **`fill_form` over multiple `fill`** — when a form has > 2 fields, `fill_form(values)` is one round-trip vs N.

## What this skill does NOT do

- **Multi-stage workflows** (explore → design → execute → write-back) → see `qumall-fulltest` skill
- **Verification code (captcha) OCR** → see `qumall-fulltest` skill section "验证码处理"
- **Assertion of UI state** (i.e. "verify the button is disabled after submission") → use `evaluate()` to read DOM attributes + `assert_*` tools from `api-mcp` if you need structured assertions
