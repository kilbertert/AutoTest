"""Context compaction middleware.

Long agent runs grow the transcript without bound; since every model call
resends the whole transcript, a long session eventually overflows the model's
context window. This middleware watches the estimated prompt size and, once it
crosses ``trigger_tokens``, **summarizes the middle of the conversation** and
replaces it in place — keeping the first message (task framing / AGENTS.md) and
a recent window verbatim.

It is a ``beforeModel`` hook so it runs right before each model call, when the
transcript is exactly what is about to be sent.

Correctness invariant — tool pairing
-------------------------------------
An assistant message carrying ``tool_use`` blocks is always followed by a
``tool`` message with the matching ``tool_result``. Providers (Anthropic
strictly, OpenAI too) reject a ``tool_result`` with no preceding ``tool_use``
and vice-versa. Compaction therefore:

- never lets the kept *head* end on an assistant ``tool_use`` whose result
  would be summarized away, and
- never lets the kept *tail* begin on an orphaned ``tool`` message.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, List, Optional, Tuple

from ...foundation import AbortSignal, NonSystemMessage

_log = logging.getLogger(__name__)

# A summarizer turns a slice of transcript into a single block of text.
Summarizer = Callable[[List[NonSystemMessage], Optional[AbortSignal]], Awaitable[str]]

# Roughly 4 characters per token — only used as a fallback estimate when the
# provider did not report real usage.
_CHARS_PER_TOKEN = 4

# Cap how much transcript we feed the summarizer so the summarization call
# itself cannot overflow the context window.
_DEFAULT_SUMMARY_INPUT_CHARS = 48_000

_SUMMARY_SYSTEM_PROMPT = (
    "You are compacting an AI coding agent's conversation so it can continue "
    "without losing important context. Produce a dense, factual summary of the "
    "transcript below. Preserve: the user's goal, files inspected or edited and "
    "their current state, commands run and their outcomes, decisions and their "
    "rationale, unresolved problems, and the immediate next steps. Omit "
    "pleasantries and redundant detail. Write it as notes the agent can rely on, "
    "not prose."
)

_SUMMARY_USER_PREFIX = "Summarize this transcript:\n\n"

_SUMMARY_WRAPPER = (
    "> [Earlier conversation was automatically summarized to fit the context "
    "window. The summary below replaces those messages.]\n\n"
)


@dataclass(frozen=True)
class CompactionEvent:
    """Reported via ``on_compaction`` after a successful compaction."""

    messages_before: int
    messages_after: int
    estimated_tokens: int
    summarized_messages: int


# --- token estimation -------------------------------------------------------


def _char_estimate(messages: List[NonSystemMessage]) -> int:
    total = 0
    for message in messages:
        for block in message.get("content", []) or []:
            btype = block.get("type")
            if btype in ("text", "thinking"):
                total += len(block.get(btype, "") or "")
            elif btype == "tool_use":
                total += len(json.dumps(block.get("input", {}), default=str))
            elif btype == "tool_result":
                total += len(str(block.get("content", "") or ""))
    return total // _CHARS_PER_TOKEN


def _last_prompt_tokens(messages: List[NonSystemMessage]) -> int:
    for message in reversed(messages):
        if message.get("role") == "assistant":
            usage = message.get("usage")
            if isinstance(usage, dict) and usage.get("promptTokens"):
                return int(usage["promptTokens"])
            break
    return 0


def estimate_tokens(messages: List[NonSystemMessage]) -> int:
    """Best-effort estimate of how large the next prompt will be.

    Uses the real ``promptTokens`` from the most recent model response when
    available, falling back to a character heuristic; takes the max so a recent
    burst of large tool results still triggers compaction.
    """
    return max(_last_prompt_tokens(messages), _char_estimate(messages))


# --- partitioning (the tool-pairing-safe split) -----------------------------


def _has_tool_use(message: NonSystemMessage) -> bool:
    return any(
        block.get("type") == "tool_use" for block in message.get("content", []) or []
    )


def plan_compaction(
    messages: List[NonSystemMessage],
    keep_head: int,
    keep_recent: int,
) -> Optional[Tuple[List[NonSystemMessage], List[NonSystemMessage], List[NonSystemMessage]]]:
    """Split ``messages`` into ``(head, middle, tail)`` respecting tool pairing.

    Returns ``None`` when there is nothing safe to compact.
    """
    n = len(messages)
    head_end = max(0, min(keep_head, n))
    # Do not let the head end on an assistant tool_use whose results live in the
    # middle — that would orphan the result. Pull the boundary back if so.
    while head_end > 0 and _has_tool_use(messages[head_end - 1]):
        head_end -= 1

    tail_start = max(head_end, n - keep_recent)
    # Do not let the tail begin on an orphaned tool message. Move forward (into
    # the middle) until the tail starts on a user/assistant message.
    while tail_start < n and messages[tail_start].get("role") == "tool":
        tail_start += 1

    middle = messages[head_end:tail_start]
    if not middle:
        return None
    return messages[:head_end], middle, messages[tail_start:]


# --- summarizers ------------------------------------------------------------


def _extract_text(message: Any) -> str:
    parts = [
        block.get("text", "")
        for block in (message.get("content") if isinstance(message, dict) else []) or []
        if block.get("type") == "text"
    ]
    return "\n".join(p for p in parts if p).strip()


def flatten_messages_to_text(
    messages: List[NonSystemMessage], *, per_block_limit: int = 2000
) -> str:
    """Render a transcript slice as plain text (avoids tool-pairing issues when
    handing it to a summarizer model as a single user message)."""

    def clip(text: str) -> str:
        return text if len(text) <= per_block_limit else text[:per_block_limit] + " …[truncated]"

    lines: List[str] = []
    for message in messages:
        role = message.get("role")
        for block in message.get("content", []) or []:
            btype = block.get("type")
            if btype == "text":
                lines.append(f"{role}: {clip(block.get('text', ''))}")
            elif btype == "thinking":
                lines.append(f"{role} (thinking): {clip(block.get('thinking', ''))}")
            elif btype == "tool_use":
                args = clip(json.dumps(block.get("input", {}), default=str))
                lines.append(f"{role} → tool {block.get('name')}({args})")
            elif btype == "tool_result":
                lines.append(f"tool ← {clip(str(block.get('content', '')))}")
    return "\n".join(lines)


def make_llm_summarizer(model: Any, *, max_input_chars: int = _DEFAULT_SUMMARY_INPUT_CHARS) -> Summarizer:
    """Summarize by asking ``model`` (a ``foundation.Model``) for a digest."""

    async def summarize(
        middle: List[NonSystemMessage], signal: Optional[AbortSignal]
    ) -> str:
        flat = flatten_messages_to_text(middle)
        if len(flat) > max_input_chars:
            # Keep the head and tail of the flattened text; the middle of the
            # middle is least likely to matter for "where are we now".
            half = max_input_chars // 2
            flat = flat[:half] + "\n…[transcript truncated]…\n" + flat[-half:]
        message = await model.invoke(
            {
                "prompt": _SUMMARY_SYSTEM_PROMPT,
                "messages": [
                    {"role": "user", "content": [{"type": "text", "text": _SUMMARY_USER_PREFIX + flat}]}
                ],
                "tools": None,
                "signal": signal,
            }
        )
        return _extract_text(message) or "(summary unavailable)"

    return summarize


def make_digest_summarizer(*, per_block_limit: int = 400) -> Summarizer:
    """No-model fallback: a truncated structural digest of the transcript."""

    async def summarize(
        middle: List[NonSystemMessage], signal: Optional[AbortSignal]
    ) -> str:
        return flatten_messages_to_text(middle, per_block_limit=per_block_limit)

    return summarize


# --- middleware factory -----------------------------------------------------


def create_compaction_middleware(
    *,
    trigger_tokens: int = 100_000,
    keep_recent_messages: int = 8,
    keep_head_messages: int = 1,
    summarizer: Optional[Summarizer] = None,
    model: Optional[Any] = None,
    on_compaction: Optional[Callable[[CompactionEvent], None]] = None,
) -> Any:
    """Return a middleware that compacts the transcript when it grows too large.

    - ``trigger_tokens``: compact once the estimated prompt size reaches this.
    - ``keep_recent_messages`` / ``keep_head_messages``: how much to preserve
      verbatim at each end (boundaries are adjusted to keep tool pairs intact).
    - ``summarizer``: how to condense the middle. Defaults to an LLM summarizer
      when ``model`` is given, else a deterministic structural digest.
    """
    if summarizer is None:
        summarizer = make_llm_summarizer(model) if model is not None else make_digest_summarizer()

    async def before_model(params: dict) -> Optional[dict]:
        agent_context = params["agentContext"]
        messages: List[NonSystemMessage] = agent_context.get("messages") or []
        estimated = estimate_tokens(messages)
        if estimated < trigger_tokens:
            return None

        plan = plan_compaction(messages, keep_head_messages, keep_recent_messages)
        if plan is None:
            return None
        head, middle, tail = plan

        signal = params.get("modelContext", {}).get("signal")
        try:
            summary_text = await summarizer(middle, signal)
        except Exception as exc:  # noqa: BLE001 — never let compaction crash a run
            _log.warning("Context compaction failed; continuing uncompacted: %s", exc)
            return None

        summary_message: NonSystemMessage = {
            "role": "user",
            "content": [{"type": "text", "text": _SUMMARY_WRAPPER + summary_text}],
        }  # type: ignore[assignment]
        new_messages = [*head, summary_message, *tail]

        before_count = len(messages)
        # Mutate the live transcript in place so the compaction persists across
        # steps (slice assignment keeps the same list object the agent holds).
        messages[:] = new_messages

        if on_compaction is not None:
            try:
                on_compaction(
                    CompactionEvent(
                        messages_before=before_count,
                        messages_after=len(new_messages),
                        estimated_tokens=estimated,
                        summarized_messages=len(middle),
                    )
                )
            except Exception:  # noqa: BLE001
                pass

        _log.info(
            "Compacted transcript: %d → %d messages (~%d tokens, %d summarized)",
            before_count,
            len(new_messages),
            estimated,
            len(middle),
        )
        return {"messages": new_messages}

    return SimpleNamespace(beforeModel=before_model)
