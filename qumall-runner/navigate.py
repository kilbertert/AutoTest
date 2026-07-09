"""Menu-path navigator for qumall-runner.

Reads menu_paths.json, parses the click-sequence for a given (module,
function, subfunction), and executes it against the live page via CDP.

Click-sequence actions:
  - {"act": "home"}                    — click the home / logo icon
  - {"act": "top_tab", "value": "..."} — click a top tab
  - {"act": "sidebar", "value": "..."} — click a left-sidebar menu item
  - {"act": "user_dropdown", "value": "..."} — click user avatar, then item
  - {"act": "sub_link", "value": "..."} — click a sub-function link/button

Resolves {function} / {subfunction} placeholders from the case. Falls
back to the per-module override map first, then the 5-tab generic
mapping (operator/iot/charging/finance/system).

If a step is not visible on the page, returns False (caller should
mark the case as 跳过 with a note about which step failed).
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Optional

_HERE = Path(__file__).parent
_PATHS_FILE = _HERE / "menu_paths.json"

# Load once at import.
_PATHS: dict = {}
if _PATHS_FILE.exists():
    _PATHS = json.loads(_PATHS_FILE.read_text(encoding="utf-8"))


def resolve_path(module: str, function: str, subfunction: str) -> list[dict]:
    """Return the click-sequence for (module, function, subfunction)."""
    # 1) Check per_module_overrides first (most explicit).
    overrides = _PATHS.get("_per_module_overrides", {}) or {}
    seq = overrides.get(module)
    if seq:
        return [_resolve_step(step, function, subfunction) for step in seq]
    # 2) Check top-level direct entries (e.g. 基础功能 → user_dropdown).
    if module in _PATHS and isinstance(_PATHS[module], list):
        return [_resolve_step(step, function, subfunction) for step in _PATHS[module]]
    # 3) Fall back to the 5-tab generic mapping.
    tab_for = {
        "运营商": "运营", "运营商管理": "运营", "运营商收益": "运营", "商家入驻/合作商家": "运营",
        "IOT": "IOT", "充电桩型号管理": "IOT", "固件升级": "IOT", "设备管理": "IOT",
        "设备白名单": "IOT", "新能源汽车设备列表": "IOT", "充电卡": "IOT", "场地管理": "IOT",
        "充电桩": "充电桩", "充电桩首页": "充电桩", "订单": "充电桩", "车队": "充电桩",
        "充电预约策略": "充电桩", "运营计费模板": "充电桩", "占位费计费模板": "充电桩", "点位奖设置": "充电桩",
        "财务": "财务", "结算": "财务", "提现": "财务", "余额": "财务", "服务费": "财务",
        "系统": "系统", "会员": "系统", "投诉建议": "系统", "FAQ": "系统", "营销活动": "系统",
        "素材库": "系统", "公告": "系统", "协议": "系统", "文章": "系统", "视频": "系统",
        "表单": "系统", "数据看板": "系统", "个人车辆": "系统", "故障反馈": "系统",
        "场地": "系统", "数据": "系统",
    }
    tab = tab_for.get(module, "系统")
    template = _PATHS.get(tab, [])
    return [_resolve_step(step, function, subfunction) for step in template]


def _resolve_step(step: dict, function: str, subfunction: str) -> dict:
    new = dict(step)
    v = new.get("value", "")
    new["value"] = v.replace("{function}", function or "").replace("{subfunction}", subfunction or "")
    return new


# ─── primitive actions (each returns True on success, False if element not found) ───


def _click_by_text(cdp, text: str, selectors: list[str]) -> str:
    """Click the first visible element whose text matches `text` and that
    matches one of the given CSS selectors (each is a selector template
    with `{}` for the text). Returns 'clicked' / 'not_found'."""
    js_lines = []
    for sel in selectors:
        js_lines.append(
            f"(() => {{"
            f"  const items = Array.from(document.querySelectorAll({json.dumps(sel.split('|'))}));"
            f"  for (const el of items) {{"
            f"    if (el.offsetParent === null) continue;"  # not visible
            f"    const t = (el.textContent || '').trim();"
            f"    if (t === {json.dumps(text)} || t.startsWith({json.dumps(text)})) {{"
            f"      el.click();"
            f"      return 'clicked';"
            f"    }}"
            f"  }}"
            f"  return 'not_found';"  # fall through to next selector
            f"}})()"
        )
    # Try each selector; first non-not_found wins.
    full_js = (
        "(() => { const r = []; \n"
        + "\n".join(js_lines)
        + "; return 'not_found'; })()"
    )
    out = cdp.evaluate_script(full_js)
    return str(out) if out else "not_found"


def _do_home(cdp) -> bool:
    """Click the home / logo icon (top-left of admin shell)."""
    js = r"""
    (() => {
        // qumall logo is the .logo / .brand / .top-bar__brand anchor
        const candidates = [
            '.top-bar__brand', '.avue-logo', '.logo', '.header__logo',
            'a[href="/"]', 'a[href*="home"]', 'a[href*="wel"]'
        ];
        for (const sel of candidates) {
            const el = document.querySelector(sel);
            if (el) { el.click(); return 'clicked:' + sel; }
        }
        // Fallback: navigate by location
        try { window.location.href = '/'; return 'clicked:location'; } catch(e) {}
        return 'not_found';
    })()
    """
    out = str(cdp.evaluate_script(js) or "")
    return out.startswith("clicked")


def _do_top_tab(cdp, value: str) -> str:
    """Click a top tab (运营/财务/IOT/充电桩/系统)."""
    return _click_by_text(cdp, value, [
        ".top-bar__menu .el-menu-item",
        ".avue-top-bar__menu .el-menu-item",
        ".el-menu--horizontal>.el-menu-item",
        ".el-tabs__item",
    ])


def _do_sidebar(cdp, value: str) -> str:
    """Click a left-sidebar menu item. Sidebar items are typically inside
    .el-menu (vertical). Some are sub-menus (.el-submenu) — we expand the
    submenu first if needed, then click the item."""
    js = f"""
    (() => {{
        const want = {json.dumps(value)};
        // 1. find submenus whose title contains the text; expand them
        const subs = Array.from(document.querySelectorAll('.el-submenu, .el-submenu__title'));
        for (const s of subs) {{
            const title = (s.querySelector('.el-submenu__title')?.textContent || s.textContent || '').trim();
            if (title.startsWith(want) || want.startsWith(title)) {{
                const trigger = s.querySelector('.el-submenu__title') || s;
                if (trigger) trigger.click();
            }}
        }}
        // 2. now find the menu-item with matching text
        const items = Array.from(document.querySelectorAll('.el-menu-item, .el-submenu .menu-item'));
        for (const it of items) {{
            const t = (it.textContent || '').trim();
            if (t === want || t.startsWith(want) || want.startsWith(t)) {{
                if (it.offsetParent !== null) {{
                    it.click();
                    return 'clicked:' + t;
                }}
            }}
        }}
        return 'not_found';
    }})()
    """
    out = str(cdp.evaluate_script(js) or "")
    return out


def _do_user_dropdown(cdp, value: str) -> str:
    """Click the user avatar (top-right) to open the dropdown, then click
    the item whose text matches `value`."""
    # qumall admin topbar has the user info area: any element with text 'huitong'
    # inside .top-bar__right or any element with .el-dropdown / .el-popper
    js = f"""
    (() => {{
        // The user dropdown trigger is .el-dropdown-link (a <span> with
        // role=button, tabindex=0). It contains a <div class="top-bar__item">
        // with the username text plus an <i> caret. Click the span (the
        // element with the actual @click handler in Vue).
        const trigger = document.querySelector('.top-bar__right .el-dropdown .el-dropdown-link');
        if (trigger) {{
            trigger.click();
            return 'opened:' + (trigger.textContent || '').trim().slice(0, 30);
        }}
        return 'no_trigger';
    }})()
    """
    open_res = str(cdp.evaluate_script(js) or "")
    if not open_res.startswith("opened"):
        return f"no_trigger:{open_res}"
    # The dropdown menu items are appended to <body> as .el-dropdown-menu / .el-menu--dropdown.
    item_js = f"""
    (() => {{
        const want = {json.dumps(value)};
        // Dropdown menu items appear in a teleported popup. Wait briefly by polling.
        return new Promise(resolve => {{
            let tries = 0;
            const tick = () => {{
                tries++;
                const items = Array.from(document.querySelectorAll(
                    '.el-dropdown-menu .el-dropdown-menu__item, .el-dropdown-item, .el-menu--dropdown li, [class*="dropdown-menu"] li, .user-menu__item'
                ));
                for (const it of items) {{
                    const t = (it.textContent || '').trim();
                    if (t === want || t.startsWith(want)) {{
                        it.click();
                        resolve('clicked:' + t);
                        return;
                    }}
                }}
                if (tries < 8) setTimeout(tick, 150);
                else {{
                    // Debug: list all visible menu items for diagnostics.
                    const all = Array.from(document.querySelectorAll('li, [role=menuitem]'))
                        .filter(el => el.offsetParent !== null && (el.textContent || '').trim().length > 0)
                        .map(el => (el.textContent || '').trim().slice(0, 40));
                    resolve('not_found_after_' + tries + ' items=' + JSON.stringify(all).slice(0, 400));
                }}
            }};
            tick();
        }});
    }})()
    """
    out = str(cdp.evaluate_script(item_js, await_promise=True) or "")
    return out


def _do_sub_link(cdp, value: str) -> str:
    """Click a sub-link / sub-button / sub-tab within the current page.

    qumall personal info page has the sub-menu as `.el-tabs__item` divs
    (not anchors), so we try the right selectors first.
    """
    js = f"""
    (() => {{
        const want = {json.dumps(value)};
        const sels = [
            '.el-tabs__item', '.el-menu-item', '.tab-item', '.nav-item',
            '.el-button', '.el-link', 'a', 'button', '[role=link]', '[role=tab]',
        ];
        for (const sel of sels) {{
            const items = Array.from(document.querySelectorAll(sel));
            for (const it of items) {{
                if (it.offsetParent === null) continue;
                const t = (it.textContent || it.getAttribute('aria-label') || it.title || '').trim();
                if (t === want || t.startsWith(want)) {{
                    it.click();
                    return 'clicked:' + t;
                }}
            }}
        }}
        return 'not_found';
    }})()
    """
    out = str(cdp.evaluate_script(js) or "")
    return out


# ─── public entry ──────────────────────────────────────────────────────


def navigate_to(cdp, module: str, function: str, subfunction: str, *,
                wait_ms: int = 2500) -> tuple[bool, str]:
    """Execute the click-sequence for the case. Returns (success, note).

    success=False means we could not find a menu item (likely the
    qumall UI text doesn't match the json). The note includes which
    step failed so the operator can fix menu_paths.json.
    """
    seq = resolve_path(module, function, subfunction)
    if not seq:
        return False, f"no menu path for module={module!r} function={function!r}"

    for i, step in enumerate(seq, 1):
        act = step.get("act", "")
        val = step.get("value", "")
        res = ""
        if act == "home":
            ok = _do_home(cdp)
        elif act == "top_tab":
            res = _do_top_tab(cdp, val)
            ok = res.startswith("clicked")
        elif act == "sidebar":
            res = _do_sidebar(cdp, val)
            ok = res.startswith("clicked")
        elif act == "user_dropdown":
            res = _do_user_dropdown(cdp, val)
            ok = res.startswith("clicked")
        elif act == "sub_link":
            res = _do_sub_link(cdp, val)
            ok = res.startswith("clicked")
        elif act == "navigate":
            # Direct URL navigation — most reliable for routes that have
            # known paths (e.g. /#/info/index, /#/wel/index).
            cdp.evaluate_script(f"window.location.href = {json.dumps(val)}")
            target = val.split("#")[-1] if "#" in val else val
            ok = False
            for _ in range(15):
                cur = cdp.evaluate_script("location.hash") or ""
                if target.lstrip("/") in cur or val.endswith(cur.lstrip("/")):
                    ok = True
                    break
                time.sleep(0.3)
            res = "navigated" if ok else "nav_timeout"
        else:
            return False, f"unknown act={act!r} at step {i}"
        if not ok:
            return False, f"step {i}/{len(seq)} {act}={val!r} res={res!r}"
        # Wait for page to settle.
        cdp.wait_for_text(".", timeout_ms=wait_ms)
    return True, f"navigated in {len(seq)} step(s)"


if __name__ == "__main__":
    # Quick smoke: print resolved paths for a few modules.
    for m, f, s in [
        ("基础功能", "个人信息", "基本信息"),
        ("充电桩首页", "", ""),
        ("运营商管理", "运营商管理（线上）", "列表"),
        ("会员", "会员列表", ""),
        ("商家入驻/合作商家", "商家入驻/合作商家", "列表"),
        ("unknown_module", "x", "y"),
    ]:
        path = resolve_path(m, f, s)
        print(f"{m}|{f}|{s} -> {path}")
