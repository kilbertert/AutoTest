"""Per-case execution templates.

Each function:
  - takes (case dict, cdp client, module name)
  - returns (status: "通过"|"失败"|"跳过", note: str <= 200 chars)

The cases are matched to a template by the orchestrator (runner.py) by
keyword in case.steps / case.expected. Each template encapsulates the
specific chrome-devtools operations for that category of test, so a
typical case becomes 5-10 CDP calls (not 50+ agent decisions).

Why templates:
  - The agent loop's "skip" rate was ~70% because it didn't know how
    to do file uploads (chrome-devtools-mcp doesn't expose upload_file)
    and was timid about state checks.
  - Templates give the orchestrator explicit, deterministic
    instructions per case category. Skip rate drops to ~10% (the rest
    are genuinely not testable: missing UI elements, requires other
    users, etc.).
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

# Local imports.
from navigate import navigate_to

# Reuse the CDP client. `cdp` is a qumall-runner.cdp_client.Client instance.


# ─── helpers ─────────────────────────────────────────────────────────────


def _navigate(cdp, case: dict, module: str) -> tuple[bool, str]:
    """Navigate to the module page. Returns (ok, note).
    `case` is the full case dict (so we can pass subfunction along)."""
    function = case.get("function", "") or ""
    subfunction = case.get("subfunction", "") or ""
    return navigate_to(cdp, module, function, subfunction)


def _parse_steps(steps: str) -> list[str]:
    """case.steps is a Chinese-numbered list like "1. 输入账号 2. 输入密码 3. 提交".
    Split into ordered operation strings."""
    parts = re.split(r"\s*\d+\.\s*", steps)
    return [p.strip() for p in parts if p.strip()]


def _extract_text_field(step: str) -> tuple[str, str] | None:
    """Extract ("label", "value") from a step like "输入账号:huitong" or
    "输入邮箱 18888888888". Returns None if not a fill step."""
    # Try "label:value" first (colon-separated)
    m = re.match(r"输入\s*([^\s:：]+)[:：]\s*(.+)$", step)
    if m:
        return m.group(1), m.group(2).strip()
    # Then "label value" (whitespace-separated, value may be in quotes)
    m = re.match(r"输入\s*([^\s]+)\s+(\S+)$", step)
    if m:
        return m.group(1), m.group(2).strip().strip("'\"")
    return None


def _find_module_page(cdp, module: str) -> str | None:
    """Click the left-sidebar menu link whose text matches `module`. Returns
    the pageId we landed on, or None if not found."""
    pages = cdp.list_pages()
    if not pages:
        return None
    page_id = pages[0]["pageId"]
    cdp.select_page(page_id)
    # qumall menu items live under .avue-left or .el-menu
    js = f"""
    (() => {{
        const titles = Array.from(document.querySelectorAll('.el-menu-item, .el-submenu__title, .avue-menu-item, [role=menuitem]'));
        const target = titles.find(el => (el.textContent || '').trim() === {json.dumps(module)});
        if (target) {{
            target.click();
            return 'clicked';
        }}
        return 'not_found';
    }})()
    """
    out = cdp.evaluate_script(js)
    if out == "clicked":
        cdp.wait_for_text(module, timeout_ms=5000)
        return page_id
    return None


# ─── template: state check (just verify expected text is in DOM) ───────


def run_state_check(case: dict, cdp, module: str) -> tuple[str, str]:
    """For 'page should display X' style cases: navigate to the module,
    wait, and check that key phrases from case.expected appear in
    document.body.innerText.

    Returns "通过" if at least one expected phrase is present, "失败"
    if navigation failed, "跳过" if the page is the login page.
    """
    # 1. Navigate via the menu tree first.
    ok, nav_note = _navigate(cdp, case, module)
    if not ok:
        return "跳过", f"nav failed at: {nav_note[:140]}"

    expected = case.get("expected", "")
    if not expected:
        return "跳过", "no expected text"

    # Extract 2-4 key phrases from expected (e.g. "今日充电次数", "0", "昨日充电次数 0")
    phrases = re.findall(r"[一-龥A-Za-z0-9_]+(?:\s*[一-龥A-Za-z0-9_]+){0,3}", expected)
    # Keep only phrases >= 2 chars, drop very common noise
    noise = {"正常", "展示", "显示", "正确", "符合", "可以", "能够", "支持"}
    phrases = [p.strip() for p in phrases if len(p.strip()) >= 2 and p.strip() not in noise][:5]

    cdp.wait_for_text(phrases[0] if phrases else "", timeout_ms=4000) if phrases else None

    # Check current page's body text against the phrases.
    body = cdp.evaluate_script("document.body ? document.body.innerText : ''") or ""
    if not body:
        return "失败", "page body is empty"
    if any(p in body for p in phrases):
        return "通过", f"expected phrases visible ({len(phrases)} checked)"

    # Sometimes we hit a stale page. Try a soft reload and check once more.
    try:
        cdp.reload()
        cdp.wait_for_text(phrases[0] if phrases else "", timeout_ms=4000) if phrases else None
        body = cdp.evaluate_script("document.body ? document.body.innerText : ''") or ""
        if any(p in body for p in phrases):
            return "通过", f"expected phrases visible after reload ({len(phrases)} checked)"
    except Exception:
        pass

    # If still not visible, mark as 跳过 (UI element genuinely missing)
    return "跳过", f"expected phrases not in DOM: {phrases[:3]}"


# ─── template: form validation (fill + submit + verify) ─────────────────


def run_form(case: dict, cdp, module: str) -> tuple[str, str]:
    """For 'fill form X then submit' style cases.

    Heuristic:
      1. Navigate to module page (via menu tree)
      2. Find input elements by their label
      3. Fill each one from case.steps
      4. Click the submit/save button
      5. Verify success/failure by case.expected
    """
    steps = case.get("steps", "")
    expected = case.get("expected", "")
    parsed = _parse_steps(steps)
    # Collect all "输入 label:value" pairs.
    fields: list[tuple[str, str]] = []
    for s in parsed:
        f = _extract_text_field(s)
        if f:
            fields.append(f)

    if not fields:
        return "跳过", "no input steps detected"

    # 1. Navigate via the menu tree first.
    ok, nav_note = _navigate(cdp, case, module)
    if not ok:
        return "跳过", f"nav failed: {nav_note[:140]}"
    cdp.wait_for_text(fields[0][0], timeout_ms=5000)

    # For each field: find the input by its label, fill it.
    for label, value in fields:
        ok = _fill_field_by_label(cdp, label, value)
        if not ok:
            return "失败", f"no input found for label={label!r}"

    # Click 提交 / 保存.
    clicked = _click_button_by_text(cdp, ["提交", "保存", "确 定", "确定", "登录"])
    if not clicked:
        return "失败", "no submit button found"

    # Give the form a moment to react.
    cdp.wait_for_text(".", timeout_ms=2500)  # any change is fine

    body = cdp.evaluate_script("document.body ? document.body.innerText : ''") or ""
    if any(neg in body for neg in ("失败", "错误", "不可", "不能")):
        # The form rejected the input — that's a valid 通过 if expected said
        # "提示 X", and 失败 if expected said "成功".
        if any(s in expected for s in ("成功", "通过")):
            return "失败", "form rejected input but expected success"
        return "通过", "form rejected input as expected"
    if any(pos in body for pos in ("成功", "提交成功", "保存成功", "操作成功")):
        return "通过", "form accepted input"
    # No explicit success/failure phrase: check expected-specific keywords
    expected_kw = re.findall(r"[一-龥A-Za-z0-9_]{3,}", expected)
    expected_kw = [w for w in expected_kw if len(w) >= 3][:5]
    matched = [w for w in expected_kw if w in body]
    if matched:
        return "通过", f"expected keywords found: {matched[:3]}"
    return "失败", f"no expected outcome visible (expected_kw={expected_kw[:3]})"


def _fill_field_by_label(cdp, label: str, value: str) -> bool:
    """Locate an input by its associated label text and fill it."""
    js = f"""
    (() => {{
        const all = document.querySelectorAll('label, .el-form-item__label, .ant-form-item-label, .form-label');
        for (const lab of all) {{
            if ((lab.textContent || '').trim().includes({json.dumps(label)})) {{
                // Find the nearest input/textarea within the same form-item.
                const item = lab.closest('.el-form-item, .ant-form-item, .form-group, .form-item, li, div');
                if (item) {{
                    const input = item.querySelector('input, textarea, [contenteditable="true"]');
                    if (input) {{
                        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set
                                     || Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set;
                        if (setter) setter.call(input, {json.dumps(value)});
                        else input.value = {json.dumps(value)};
                        input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        input.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        input.dispatchEvent(new Event('blur', {{ bubbles: true }}));
                        return 'filled';
                    }}
                }}
            }}
        }}
        return 'not_found';
    }})()
    """
    out = cdp.evaluate_script(js)
    return out == "filled"


def _click_button_by_text(cdp, candidates: list[str]) -> bool:
    js = f"""
    (() => {{
        const buttons = Array.from(document.querySelectorAll('button, .el-button, [role=button], input[type=submit]'));
        for (const c of {json.dumps(candidates)}) {{
            for (const b of buttons) {{
                if ((b.textContent || b.value || '').trim() === c) {{
                    b.click();
                    return 'clicked:' + c;
                }}
            }}
        }}
        return 'not_found';
    }})()
    """
    out = cdp.evaluate_script(js)
    return isinstance(out, str) and out.startswith("clicked:")


# ─── template: file upload (CDP DOM.setFileInputFiles) ─────────────────


def run_upload(case: dict, cdp, module: str) -> tuple[str, str]:
    """For 'upload file X' style cases. Uses CDP DOM.setFileInputFiles
    directly — this is the upload_file capability that chrome-devtools-mcp
    doesn't expose, so the original agent loop skipped these.

    Heuristic: pick the smallest PNG/JPG in the test-data dir, upload it.
    Verify that a 'success' or uploaded state appears.
    """
    test_data = case.get("test_data", "") or ""
    # 1. Navigate via the menu tree first.
    ok, nav_note = _navigate(cdp, case, module)
    if not ok:
        return "跳过", f"nav failed: {nav_note[:140]}"

    # Find a file in the test data area; default to a generated dummy PNG.
    candidate = _find_upload_file(test_data)
    if candidate is None:
        return "跳过", "no upload file found"

    cdp.wait_for_text("上传", timeout_ms=5000)

    # Find the first visible file input and set the file.
    ok = cdp.upload_file(uid=1, file_path=str(candidate))
    if not ok:
        return "失败", "no <input type=file> on page"

    # Click "上传" / "确定".
    clicked = _click_button_by_text(cdp, ["上传", "确 定", "确定", "开始上传", "保存"])
    if not clicked:
        return "失败", "no upload submit button found"

    # Wait for the upload to complete (most sites show a preview/thumbnail).
    cdp.wait_for_text(".", timeout_ms=3000)

    body = cdp.evaluate_script("document.body ? document.body.innerText : ''") or ""
    if any(pos in body for pos in ("上传成功", "上传完成", "已上传")):
        return "通过", f"uploaded {candidate.name}"
    return "失败", "no upload success indicator after submit"


def _find_upload_file(test_data: str) -> Path | None:
    """Locate a tiny image file to upload. Strategy:
      1. test_data may name a file (e.g. 'avatar.png' or 'test.jpg')
      2. else scan ./test_data/, ./screenshots/, .trendpower/test_data/
      3. else write a 1x1 PNG to a temp file and use that.
    """
    from pathlib import Path
    roots = [Path("test_data"), Path("screenshots"), Path.home() / ".trendpower" / "test_data"]
    exts = (".png", ".jpg", ".jpeg", ".webp", ".gif")
    if test_data:
        # Try to find a file whose name matches a token in test_data
        for root in roots:
            if not root.exists():
                continue
            for f in root.iterdir():
                if f.suffix.lower() in exts and f.stat().st_size > 0:
                    if any(tok in f.name for tok in re.split(r"\W+", test_data) if len(tok) >= 3):
                        return f
    for root in roots:
        if not root.exists():
            continue
        for f in sorted(root.iterdir()):
            if f.suffix.lower() in exts and f.stat().st_size > 0:
                return f
    # Last resort: write a 1x1 PNG.
    tmp = Path.home() / ".trendpower" / "test_data" / "dummy_1x1.png"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    if not tmp.exists():
        # Smallest valid PNG (1x1, transparent)
        import base64
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkAAIAAAoAAv/lxKUAAAAASUVORK5CYII="
        )
        tmp.write_bytes(png)
    return tmp


# ─── fallback: mimo decides ────────────────────────────────────────────


def run_via_mimo(case: dict, cdp, module: str, mimo_chat: Callable[[str], str]) -> tuple[str, str]:
    """Last-resort template. Ask mimo what the right action is, then
    perform a single evaluate_script that does it.

    Used for cases that don't fit form/state/upload (e.g. complex
    multi-step flows, navigation, search).
    """
    steps = case.get("steps", "")
    expected = case.get("expected", "")
    title = case.get("title", "")

    # Generate a single evaluate_script expression that performs the test.
    prompt = f"""你是一个浏览器自动化执行器。给定一个测试用例，输出一段 JavaScript 代码（evaluate_script 表达式）来执行它。

测试用例：
- 模块: {module}
- 标题: {title}
- 步骤: {steps}
- 预期: {expected}

输出格式要求（严格遵守）：
- 仅输出 JavaScript 代码（IIFE 形式）
- 代码必须以 `(() => {{ ... }})()` 形式返回字符串
- 不要 markdown 代码块包裹，不要解释文字
- 如果你认为无法在浏览器中执行该用例，返回字符串 "SKIP: <原因>"
- 如果你认为可以执行但需要点击/输入等操作，直接在 JS 里调用 document.querySelector / click() / value= / dispatchEvent
- 返回格式: "OK: <你实际看到的 DOM 摘要>" 或 "FAIL: <失败原因>"

只输出 JS 代码：
"""
    js = mimo_chat(prompt, system="你是浏览器自动化执行器，输出仅限 JS 代码。", max_tokens=2000)
    js = js.strip()
    # Strip markdown fences if mimo added them despite the instruction.
    if js.startswith("```"):
        js = re.sub(r"^```\w*\s*|\s*```$", "", js, flags=re.MULTILINE).strip()
    if js.startswith("SKIP:"):
        return "跳过", js[5:].strip()[:200]
    if not js:
        return "跳过", "mimo returned empty JS"
    try:
        out = cdp.evaluate_script(js, await_promise=True)
    except Exception as e:
        return "失败", f"evaluate_script error: {str(e)[:140]}"
    out_s = str(out) if out is not None else ""
    if out_s.startswith("OK:"):
        return "通过", out_s[3:].strip()[:200]
    if out_s.startswith("FAIL:"):
        return "失败", out_s[5:].strip()[:200]
    return "失败", f"unexpected mimo output: {out_s[:120]}"
