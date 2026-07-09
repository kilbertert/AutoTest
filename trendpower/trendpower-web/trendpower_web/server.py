"""aiohttp HTTP server: static index + /events SSE stream."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from aiohttp import web

from .broadcaster import EventBroadcaster

_STATIC_DIR = Path(__file__).parent / "static"


async def _index(_request: web.Request) -> web.FileResponse:
    return web.FileResponse(_STATIC_DIR / "index.html")


async def _asset(request: web.Request) -> web.FileResponse:
    name = request.match_info["name"]
    target = (_STATIC_DIR / name).resolve()
    if _STATIC_DIR.resolve() not in target.parents and target != _STATIC_DIR.resolve():
        raise web.HTTPNotFound()
    if not target.exists() or not target.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(target)


def _make_events_handler(broadcaster: EventBroadcaster):
    async def _events(request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )
        await response.prepare(request)
        # Initial comment line keeps proxies / curl from buffering until first event.
        await response.write(b": connected\n\n")

        async with broadcaster.subscribe() as queue:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    try:
                        await response.write(b": keep-alive\n\n")
                    except ConnectionResetError:
                        return response
                    continue
                payload = json.dumps(event, ensure_ascii=False, default=str)
                try:
                    await response.write(f"data: {payload}\n\n".encode("utf-8"))
                except ConnectionResetError:
                    return response

    return _events


def build_app(broadcaster: EventBroadcaster) -> web.Application:
    app = web.Application()
    app.router.add_get("/", _index)
    app.router.add_get("/events", _make_events_handler(broadcaster))
    app.router.add_get("/assets/{name}", _asset)
    return app


async def start_server(
    broadcaster: EventBroadcaster, host: str, port: int
) -> web.AppRunner:
    runner = web.AppRunner(build_app(broadcaster))
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    return runner
