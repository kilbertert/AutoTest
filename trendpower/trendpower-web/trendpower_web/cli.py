"""`trendpower-web` entry point.

Launches the same Textual TUI as `trendpower`, with an extra HTTP server
that streams the real LLM request body / response / agent events to a
browser over SSE.

Mechanism: before the TUI starts, we monkey-patch the two model provider
classes and `AgentRunner.submit` so that every LLM call and every agent
event also gets published to the broadcaster.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from .broadcaster import EventBroadcaster


def _patch_providers(broadcaster: EventBroadcaster) -> None:
    """Replace the provider classes the TUI imports with capturing subclasses.

    `trendpower_tui.app._try_create_runner` does a lazy
    `from trendpower.community.{openai,anthropic} import ...ModelProvider`
    on each agent rebuild, so monkey-patching the module attribute is
    sufficient — every subsequent rebuild picks up our subclass.
    """
    import trendpower.community.anthropic as anthropic_module
    import trendpower.community.openai as openai_module

    from .instrumented_providers import AnthropicWithCapture, OpenAIWithCapture

    class _OpenAI(OpenAIWithCapture):
        def __init__(self, *, base_url: Any = None, api_key: Any = None) -> None:
            super().__init__(broadcaster, base_url=base_url, api_key=api_key)

    class _Anthropic(AnthropicWithCapture):
        def __init__(self, *, base_url: Any = None, api_key: Any = None) -> None:
            super().__init__(broadcaster, base_url=base_url, api_key=api_key)

    openai_module.OpenAIModelProvider = _OpenAI
    anthropic_module.AnthropicModelProvider = _Anthropic


def _patch_agent_runner(broadcaster: EventBroadcaster) -> None:
    """Wrap AgentRunner.submit so every agent event is also broadcast.

    Done as a class-level patch (rather than a subclass) so we don't have
    to duplicate the buffered-flush logic inside AgentRunner.submit.
    """
    from trendpower_tui.tui import agent_runner as agent_runner_module

    runner_cls = agent_runner_module.AgentRunner
    original_submit = runner_cls.submit

    async def patched_submit(
        self: Any, text: str, requested_skill: str | None = None
    ) -> None:
        broadcaster.publish({"type": "user_input", "text": text})

        # Wrap agent.stream just for this call so each yielded event is
        # broadcast to the browser before being handed back to the runner.
        agent = self.agent
        original_stream = agent.stream

        async def wrapped(user_message: Any) -> Any:
            async for event in original_stream(user_message):
                broadcaster.publish({"type": "agent_event", "event": event})
                yield event

        agent.stream = wrapped  # type: ignore[method-assign]
        try:
            await original_submit(self, text, requested_skill)
        finally:
            try:
                del agent.stream
            except AttributeError:
                # In case some other path replaced .stream too.
                agent.stream = original_stream  # type: ignore[method-assign]

    runner_cls.submit = patched_submit  # type: ignore[method-assign]


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="trendpower-web",
        description=(
            "Launch the trendpower TUI with a parallel web view of every LLM call. "
            "Same terminal experience as `trendpower`; open the printed URL in a "
            "browser to see the real request payload, streaming response, and "
            "tool calls."
        ),
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    broadcaster = EventBroadcaster()

    try:
        _patch_providers(broadcaster)
        _patch_agent_runner(broadcaster)
    except Exception as error:
        sys.exit(f"trendpower-web: failed to install instrumentation hooks: {error}")

    # Importing the app last so the patched provider attributes are in place.
    from .app import TrendpowerWebApp

    app = TrendpowerWebApp(broadcaster, args.host, args.port)
    app.run()


if __name__ == "__main__":
    main()
