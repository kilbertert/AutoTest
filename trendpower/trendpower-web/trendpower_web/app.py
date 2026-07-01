"""TrendpowerWebApp — the unchanged Textual TUI + a parallel aiohttp server.

The TUI behaves exactly like `trendpower`. The only additions are:

1. Provider classes have been monkey-patched (in cli.py before app start) to
   emit `llm_request` events for every SDK call.
2. `AgentRunner.submit` has been monkey-patched to broadcast every agent
   event in addition to posting Textual messages.
3. `on_mount` boots an aiohttp server on the same asyncio loop Textual uses.
"""

from __future__ import annotations

from pathlib import Path as _Path
from typing import Any

import trendpower_tui as _trendpower_tui_pkg
from aiohttp import web
from trendpower_tui.app import TrendpowerApp

from .broadcaster import EventBroadcaster
from .server import start_server

# TrendpowerApp declares ``CSS_PATH = "tui/theme.tcss"`` which Textual resolves
# relative to the file of the *concrete* App subclass. Without an override,
# Textual would look for ``trendpower_web/tui/theme.tcss`` — which does not
# exist. Pin the absolute path to trendpower_tui's bundled stylesheet instead.
_TUI_TCSS = str(
    (_Path(_trendpower_tui_pkg.__file__).parent / "tui" / "theme.tcss").resolve()
)


class TrendpowerWebApp(TrendpowerApp):
    """Same TUI as `trendpower`, with an aiohttp event stream running alongside."""

    CSS_PATH = _TUI_TCSS

    def __init__(self, broadcaster: EventBroadcaster, host: str, port: int) -> None:
        super().__init__()
        self._broadcaster = broadcaster
        self._host = host
        self._port = port
        self._server_runner: web.AppRunner | None = None

    def _build_tracing_sink(self) -> Any:
        """Always trace in the web view; stream spans to the browser (and to a
        JSONL file too when ``trendpower_TRACE`` is set)."""
        from trendpower.agent.tracing import MultiSink

        from .trace_sink import BroadcasterSink

        sinks = [BroadcasterSink(self._broadcaster)]
        file_sink = super()._build_tracing_sink()
        if file_sink is not None:
            sinks.append(file_sink)
        return MultiSink(sinks)

    async def on_mount(self) -> None:
        await super().on_mount()
        try:
            self._server_runner = await start_server(
                self._broadcaster, self._host, self._port
            )
            self._append_system_text(
                f"[trendpower-web] live view at http://{self._host}:{self._port}"
            )
        except OSError as error:
            self._append_system_text(
                f"[trendpower-web] failed to bind {self._host}:{self._port} — {error}"
            )

    async def on_unmount(self) -> None:
        try:
            await super().on_unmount()
        finally:
            if self._server_runner is not None:
                try:
                    await self._server_runner.cleanup()
                except Exception:
                    pass
                self._server_runner = None
