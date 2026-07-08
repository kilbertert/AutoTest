"""Chrome DevTools Protocol (CDP) client — bypasses chrome-devtools-mcp.

Why this exists:
  - chrome-devtools-mcp doesn't expose `upload_file` (setInputFiles), so file
    upload test cases get skipped. CDP has `DOM.setFileInputFiles` directly.
  - mcp servers are locked to a single process via stdio; for a long-running
    24/7 qumall-runner that has its own state, we want direct control.
  - CDP is just JSON-over-WebSocket. We use stdlib (json + urllib can't
    do WebSocket) so this file ships a tiny ws-client implemented on top
    of an asyncio-based ws via a single dependency we add at install time,
    OR fall back to using `websocket-client` if present, OR the even
    simpler path: launch chrome ourselves with --remote-debugging-port
    and use HTTP+WS via stdlib `socket` and `base64` for the upgrade.

This file takes the LATER path: launch Edge with --remote-debugging-port,
talk CDP over plain HTTP for /json, then over WebSocket for commands.
No third-party deps; uses stdlib `socket` and a hand-rolled WS framing.

Public surface (sync, blocking):
  - connect(debug_port) -> Client
  - Client.list_pages() -> [{pageId, url, title}]
  - Client.attach(pageId) -> (ws, targetId) — call after list_pages
  - Client.navigate(url) / reload() / close()
  - Client.take_snapshot() -> a11y tree text
  - Client.click(uid) / fill(uid, value) / press_key(key)
  - Client.evaluate_script(expression) -> result JSON
  - Client.take_screenshot(path) -> saves PNG, returns path
  - Client.upload_file(uid, file_path) -> uses DOM.setFileInputFiles
  - Client.wait_for(text, timeout_ms)
"""

from __future__ import annotations

import base64
import json
import os
import re
import socket
import struct
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any, Optional


# ─── minimal WebSocket client (RFC 6455, text frames, no masking from client) ───


class _WS:
    """Tiny sync WebSocket client. Sends text frames; reads text frames.

    Chrome's CDP requires the client to send masked frames (per RFC), and
    the server sends unmasked frames. We implement only that subset.
    """

    def __init__(self, host: str, port: int, path: str = "/"):
        self.sock = socket.create_connection((host, port), timeout=30)
        self.sock.settimeout(None)  # blocking; caller sets per-call timeout
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        ).encode("ascii")
        self.sock.sendall(req)
        # Read until \r\n\r\n
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("ws handshake closed early")
            buf += chunk
        head, _, rest = buf.partition(b"\r\n\r\n")
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise ConnectionError(f"ws handshake failed: {head[:200]!r}")
        self._buf = rest

    def _send_frame(self, payload: bytes) -> None:
        # Client frames must be masked (RFC 6455 §5.3).
        header = bytearray()
        header.append(0x81)  # FIN + text opcode
        mask_key = os.urandom(4)
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < (1 << 16):
            header.append(0x80 | 126)
            header += struct.pack("!H", length)
        else:
            header.append(0x80 | 127)
            header += struct.pack("!Q", length)
        header += mask_key
        masked = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(header) + masked)

    def _recv_exact(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("ws closed mid-frame")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _recv_frame(self) -> bytes:
        # Server frames are NOT masked.
        b = self._recv_exact(2)
        fin = b[0] & 0x80
        opcode = b[0] & 0x0F
        masked = b[1] & 0x80
        length = b[1] & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._recv_exact(8))[0]
        mask_bytes = self._recv_exact(4) if masked else b""
        payload = self._recv_exact(length)
        if mask_bytes:
            payload = bytes(c ^ mask_bytes[i % 4] for i, c in enumerate(payload))
        if opcode == 0x8:  # close
            raise ConnectionError("ws closed by server")
        if opcode == 0x9:  # ping
            self._send_frame(payload)  # pong
            return self._recv_frame()
        if not fin:
            # multi-frame: concatenate following frames
            return payload + self._recv_frame()
        return payload

    def send_text(self, msg: str) -> None:
        self._send_frame(msg.encode("utf-8"))

    def recv_text(self) -> str:
        return self._recv_frame().decode("utf-8", errors="replace")

    def close(self) -> None:
        try:
            self.sock.close()
        except Exception:
            pass


# ─── CDP client ─────────────────────────────────────────────────────────


class Client:
    """Sync CDP client over a single WebSocket to a specific page target."""

    def __init__(self, debug_port: int, *, executable: Optional[str] = None,
                 user_data_dir: Optional[str] = None,
                 headless: bool = False, url: Optional[str] = None) -> None:
        self.debug_port = debug_port
        self._proc: Optional[subprocess.Popen] = None
        self._ws: Optional[_WS] = None
        self._id = 0
        self._pending: dict[int, dict] = {}
        if executable:
            self._launch(executable, user_data_dir, headless, url)
        # else assume Edge/Chrome is already running with --remote-debugging-port
        self._ws = self._attach_first_page()

    def _launch(self, executable: str, user_data_dir: Optional[str],
                headless: bool, url: Optional[str]) -> None:
        args = [
            executable,
            f"--remote-debugging-port={self.debug_port}",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        if user_data_dir:
            args.append(f"--user-data-dir={user_data_dir}")
        if headless:
            args.append("--headless=new")
        if url:
            args.append(url)
        # Detach from console: no stdin, separate stdout/stderr files.
        log_dir = Path.home() / ".trendpower" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        self._proc = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=open(log_dir / "qumall-runner-edge.out", "ab"),
            stderr=open(log_dir / "qumall-runner-edge.err", "ab"),
            close_fds=True,
        )
        # Wait for the debugger to come up.
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.debug_port}/json/version", timeout=2)
                return
            except Exception:
                time.sleep(0.5)
        raise RuntimeError(f"Edge didn't open debug port {self.debug_port} within 30s")

    def _http_json(self, path: str) -> list:
        with urllib.request.urlopen(f"http://127.0.0.1:{self.debug_port}{path}", timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))

    def _attach_first_page(self) -> _WS:
        pages = self._http_json("/json")
        if not pages:
            # No page yet — open about:blank via a new tab
            tabs = self._http_json("/json/new?about:blank")
            pages = tabs
        # Pick the first non-Chrome-internal page
        for p in pages:
            if p.get("type") in ("page", ""):
                ws_url = p["webSocketDebuggerUrl"]
                # ws://127.0.0.1:PORT/devtools/page/<id>
                m = re.match(r"ws://([^/]+)(/.*)", ws_url)
                host_port, path = m.group(1), m.group(2)
                host, port = host_port.split(":")
                return _WS(host, int(port), path)
        raise RuntimeError(f"no page target found at debug port {self.debug_port}: {pages}")

    def _send(self, method: str, params: Optional[dict] = None) -> dict:
        """Send a CDP command, wait for the matching response. Returns the
        full message dict (caller reads .get('result') / .get('error'))."""
        assert self._ws is not None
        self._id += 1
        msg_id = self._id
        req = {"id": msg_id, "method": method, "params": params or {}}
        self._ws.send_text(json.dumps(req))
        # Drain events until we get our id.
        while True:
            text = self._ws.recv_text()
            try:
                obj = json.loads(text)
            except json.JSONDecodeError:
                continue
            if obj.get("id") == msg_id:
                return obj
            # Else it's an event (e.g. Page.loadEventFired) — discard.

    def list_pages(self) -> list[dict]:
        """Return [{pageId, url, title, type}] — usable for selecting a page
        before each operation. We get this by polling /json/list."""
        pages = self._http_json("/json/list")
        return [
            {
                "pageId": p.get("id", ""),
                "url": p.get("url", ""),
                "title": p.get("title", ""),
                "type": p.get("type", "page"),
            }
            for p in pages
        ]

    def select_page(self, page_id: str) -> "Client":
        """Re-attach the WS to a different page. Returns self for chaining."""
        pages = self._http_json("/json/list")
        target = next((p for p in pages if p.get("id") == page_id), None)
        if not target:
            raise RuntimeError(f"pageId {page_id!r} not found in /json/list")
        ws_url = target["webSocketDebuggerUrl"]
        m = re.match(r"ws://([^/]+)(/.*)", ws_url)
        host_port, path = m.group(1), m.group(2)
        host, port = host_port.split(":")
        if self._ws is not None:
            self._ws.close()
        self._ws = _WS(host, int(port), path)
        return self

    def navigate(self, url: str) -> None:
        r = self._send("Page.enable")
        r = self._send("Page.navigate", {"url": url})
        # Best-effort: Page.navigate resolves when the navigation is committed;
        # for full load, caller should also Page.loadEventFired.
        if "error" in r:
            raise RuntimeError(f"Page.navigate error: {r['error']}")

    def reload(self) -> None:
        self._send("Page.reload", {"ignoreCache": False})

    def evaluate_script(self, expression: str, *, await_promise: bool = False) -> Any:
        params = {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": await_promise,
        }
        r = self._send("Runtime.evaluate", params)
        if "error" in r:
            raise RuntimeError(f"Runtime.evaluate error: {r['error']}")
        result = (r.get("result") or {}).get("result") or {}
        if "value" in result:
            return result["value"]
        if result.get("type") == "undefined":
            return None
        return None

    def take_snapshot(self) -> str:
        """Returns the page's accessibility tree as plain text — same shape
        chrome-devtools-mcp emits. Built from DOM tree to avoid pulling in
        the full Accessibility domain (which requires enableAccessibilityTree)."""
        js = r"""
        (() => {
            const lines = [];
            let uid = 0;
            function walk(node, depth) {
                if (!node || depth > 20) return;
                if (node.nodeType === 3) {
                    const t = (node.textContent || '').trim();
                    if (t) lines.push('  '.repeat(depth) + 'text: ' + t);
                    return;
                }
                if (node.nodeType !== 1) return;
                const role = node.getAttribute('role') || node.tagName.toLowerCase();
                const name = node.getAttribute('aria-label') || node.textContent?.trim().slice(0, 80) || '';
                const id = node.id ? '#' + node.id : '';
                const cls = node.className && typeof node.className === 'string' ? '.' + node.className.split(' ')[0] : '';
                const rect = node.getBoundingClientRect ? node.getBoundingClientRect() : null;
                const visible = rect && rect.width > 0 && rect.height > 0;
                const u = (visible ? 'uid=' : 'uid_h=') + (++uid);
                lines.push('  '.repeat(depth) + u + ' ' + role + (name ? ' \"' + name.replace(/\"/g, '\\"').slice(0, 60) + '\"' : '') + id + cls);
                for (const c of node.childNodes) walk(c, depth + 1);
            }
            walk(document.body || document.documentElement, 0);
            return lines.join('\n');
        })()
        """
        return self.evaluate_script(js) or ""

    def click_uid(self, uid: int) -> None:
        """Click the element with this uid (from take_snapshot)."""
        js = f"""
        (() => {{
            const all = document.querySelectorAll('*');
            let i = 0;
            for (const el of all) {{
                const r = el.getBoundingClientRect();
                if (r.width > 0 && r.height > 0) {{
                    if (++i === {uid}) {{
                        el.click();
                        return 'clicked';
                    }}
                }}
            }}
            return 'not_found';
        }})()
        """
        out = self.evaluate_script(js)
        if out != "clicked":
            raise RuntimeError(f"uid={uid} click failed: {out}")

    def fill_uid(self, uid: int, value: str) -> None:
        js = f"""
        (() => {{
            const all = document.querySelectorAll('input, textarea, [contenteditable="true"]');
            let i = 0;
            for (const el of all) {{
                const r = el.getBoundingClientRect();
                if (r.width > 0 && r.height > 0) {{
                    if (++i === {uid}) {{
                        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set
                                     || Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set;
                        if (setter) setter.call(el, {json.dumps(value)});
                        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        return 'filled';
                    }}
                }}
            }}
            return 'not_found';
        }})()
        """
        out = self.evaluate_script(js)
        if out != "filled":
            raise RuntimeError(f"uid={uid} fill failed: {out}")

    def press_key(self, key: str) -> None:
        """key examples: 'Enter', 'Tab', 'Escape', 'ArrowDown'."""
        self.evaluate_script(f"document.activeElement?.dispatchEvent(new KeyboardEvent('keydown', {{ key: {json.dumps(key)} }}))")

    def take_screenshot(self, path: str) -> str:
        r = self._send("Page.captureScreenshot", {"format": "png"})
        data = (r.get("result") or {}).get("data") or ""
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(base64.b64decode(data))
        return path

    def upload_file(self, uid: int, file_path: str) -> None:
        """CDP DOM.setFileInputFiles — fills <input type=file>.

        uid in our snapshot = the visible position (1-based) of an
        <input type=file> among all visible inputs.
        """
        # Find the nodeId for the file input at position `uid` among visible file inputs.
        r = self._send("Runtime.evaluate", {
            "expression": (
                "(() => {"
                "  const inputs = Array.from(document.querySelectorAll('input[type=file]'));"
                "  const visible = inputs.filter(i => i.offsetParent !== null || i.getBoundingClientRect().height > 0);"
                f"  const target = visible[{uid - 1}];"
                "  if (!target) return null;"
                "  return target.outerHTML.slice(0, 200);"
                "})()"
            ),
            "returnByValue": True,
        })
        # Walk DOM to find backendNodeId of the input. Easier: just dispatch
        # a synthetic change event with files via DataTransfer — but that
        # doesn't work for security reasons. So we do it the proper way:
        #   1. Runtime.evaluate returning the DOM node
        #   2. DOM.describeNode to get backendNodeId
        #   3. DOM.setFileInputFiles
        # Step 1+2 via a single getDocument walk is simpler:
        doc = self._send("DOM.getDocument", {"depth": -1, "pierce": True})
        # Find the Nth visible file input by walking.
        target_node_id = self._find_nth_file_input(doc.get("result", {}).get("root", {}), uid)
        if target_node_id is None:
            raise RuntimeError(f"file input uid={uid} not found")
        r = self._send("DOM.setFileInputFiles", {
            "files": [file_path],
            "nodeId": target_node_id,
        })
        if "error" in r:
            raise RuntimeError(f"DOM.setFileInputFiles error: {r['error']}")

    def _find_nth_file_input(self, node: dict, uid: int) -> Optional[int]:
        """Walk the DOM tree (already-fetched) and return the backendNodeId
        of the Nth visible <input type=file>."""
        count = [0]
        def walk(n):
            if not isinstance(n, dict):
                return None
            attrs = n.get("attributes") or []
            if n.get("nodeType") == 1 and "FILE" in [a.upper() for a in attrs if a.upper() in ("TYPE", "FILE")]:
                if any(a.lower() == "type" and a_val.lower() == "file" for a, a_val in zip(attrs[::2], attrs[1::2])):
                    if count[0] == uid - 1:
                        return n.get("backendNodeId")
                    count[0] += 1
            for c in n.get("children") or []:
                r = walk(c)
                if r is not None:
                    return r
            return None
        return walk(node)

    def wait_for_text(self, text: str, timeout_ms: int = 10000) -> bool:
        deadline = time.time() + (timeout_ms / 1000)
        while time.time() < deadline:
            js = f"document.body && document.body.innerText && document.body.innerText.includes({json.dumps(text)})"
            try:
                if self.evaluate_script(js):
                    return True
            except Exception:
                pass
            time.sleep(0.5)
        return False

    def close(self) -> None:
        if self._ws:
            self._ws.close()
        if self._proc:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass


# ─── public surface (sync) ──────────────────────────────────────────────

def connect(*, debug_port: int = 9222, executable: Optional[str] = None,
           user_data_dir: Optional[str] = None, headless: bool = False,
           url: Optional[str] = None) -> Client:
    return Client(debug_port, executable=executable, user_data_dir=user_data_dir,
                  headless=headless, url=url)


if __name__ == "__main__":
    # Smoke test: launch Edge, list pages, navigate, take screenshot.
    EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    PROFILE = str(Path.home() / ".trendpower" / "qumall-profile")
    c = connect(debug_port=9222, executable=EDGE, user_data_dir=PROFILE,
                url="https://admin.qumall.qushiyun.com/")
    print("pages:", c.list_pages()[:3])
    c.take_screenshot(str(Path.home() / ".trendpower" / "logs" / "smoke.png"))
    print("ok")
    c.close()
