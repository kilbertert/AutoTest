"""The ``task`` tool — delegate a focused sub-task to an isolated sub-agent.

Why this exists: broad, read-heavy work (sweeping a repo with grep/read to find
every caller of X) generates a lot of intermediate tool noise. Running it inline
bloats the parent transcript and erodes the cached prefix. Delegating it to a
sub-agent keeps all that noise in a *separate* transcript that is discarded once
the sub-agent returns — the parent only ever sees the final report.

Two flavours:
- ``explore`` (default): read-only toolset, no approval needed. The safe,
  high-value case (fan-out search / investigation).
- ``general``: the full mutating toolset, with the parent's approval flow
  forwarded so bash/writes still prompt the user.

Safety invariants:
- A sub-agent never receives the ``task`` tool → recursion depth is fixed at 1.
- A sub-agent never receives ``ask_user_question`` → it cannot block on the user.
"""

from __future__ import annotations

from typing import Awaitable, Callable, List, Literal, Optional

from pydantic import BaseModel, Field

from ...agent import Agent, create_compaction_middleware, run_subagent
from ...agent.tracing import TraceSink, create_tracing_middleware
from ...foundation import AbortError, AbortSignal, Model, Tool, ToolUseContent, define_tool
from ..permissions import (
    CODING_TOOLS_REQUIRING_APPROVAL,
    ApprovalDecision,
    ApprovalPersistence,
    create_coding_approval_middleware,
)
from .tool_result import error_tool_result, ok_tool_result

READ_ONLY_TOOL_NAMES = {"read_file", "list_files", "glob_search", "grep_search", "file_info"}

# A sub-agent must never be handed these, regardless of flavour.
_NEVER_DELEGATE = {"task", "ask_user_question"}

_SUBAGENT_MAX_STEPS = 30


class TaskParameters(BaseModel):
    description: str = Field(
        description="A short (3-5 word) label for the delegated task, shown in progress UI."
    )
    prompt: str = Field(
        description="The full, self-contained task for the sub-agent. It does not see this "
        "conversation, so include every detail it needs."
    )
    subagent_type: Literal["explore", "general"] = Field(
        default="explore",
        description=(
            "'explore' (default): read-only investigation/search — cannot modify files. "
            "'general': may edit files and run commands (still subject to approval)."
        ),
    )


def _explore_prompt(cwd: str) -> str:
    return (
        '<agent name="Explore" role="subagent" description="A read-only exploration agent">\n'
        "You are a sub-agent delegated a focused, read-only investigation. Use the search and "
        "read tools to gather what was asked, then STOP and report. You cannot modify files, run "
        "commands, or ask the user anything.\n"
        "</agent>\n\n"
        f'<working_directory dir="{cwd}/" />\n\n'
        "<output>\n"
        "End with a concise findings report: the answer to the task, citing concrete file:line "
        "references. Do not narrate your search; report conclusions.\n"
        "</output>\n"
    )


def _general_prompt(cwd: str) -> str:
    return (
        '<agent name="Worker" role="subagent" description="A coding sub-agent">\n'
        "You are a sub-agent delegated a focused, self-contained coding task. Complete it using "
        "the given tools, then STOP and report. You cannot ask the user questions; make reasonable "
        "assumptions and note them.\n"
        "</agent>\n\n"
        f'<working_directory dir="{cwd}/" />\n\n'
        "<output>\n"
        "End with a concise report of what you changed and the outcome (files touched, commands "
        "run and their result). Report conclusions, not a play-by-play.\n"
        "</output>\n"
    )


def create_task_tool(
    *,
    model: Model,
    cwd: str,
    base_tools: List[Tool],
    ask_user: Optional[Callable[[ToolUseContent], Awaitable[ApprovalDecision]]] = None,
    approval_persistence: Optional[ApprovalPersistence] = None,
    compaction_trigger_tokens: int = 100_000,
    tracing_sink: Optional[TraceSink] = None,
) -> Tool:
    """Build the ``task`` tool bound to ``model`` and the parent's ``base_tools``.

    ``base_tools`` is the parent agent's toolset; the sub-agent's toolset is
    derived from it (read-only subset for ``explore``, everything minus the
    never-delegate set for ``general``).
    """
    read_only_tools = [t for t in base_tools if t.name in READ_ONLY_TOOL_NAMES]
    general_tools = [t for t in base_tools if t.name not in _NEVER_DELEGATE]

    def _build_inner(subagent_type: str) -> Agent:
        if subagent_type == "general":
            prompt = _general_prompt(cwd)
            tools = general_tools
            needs_approval = ask_user is not None
        else:
            prompt = _explore_prompt(cwd)
            tools = read_only_tools
            needs_approval = False  # read-only tools are never in the approval set

        middlewares: List = [
            create_compaction_middleware(
                trigger_tokens=compaction_trigger_tokens, model=model
            )
        ]
        if needs_approval:
            middlewares.append(
                create_coding_approval_middleware(
                    cwd=cwd,
                    requires_approval=CODING_TOOLS_REQUIRING_APPROVAL,
                    ask_user=ask_user,  # type: ignore[arg-type]
                    approval_persistence=approval_persistence,
                )
            )
        if tracing_sink is not None:
            # Same sink instance as the parent: the sub-agent's spans land in the
            # parent's trace file/stream, linked via parent_run_id.
            middlewares.append(
                create_tracing_middleware(
                    tracing_sink, model_name=model.name, is_subagent=True
                )
            )

        return Agent(
            model=model,
            prompt=prompt,
            messages=[],
            tools=tools,
            middlewares=middlewares,
            maxSteps=_SUBAGENT_MAX_STEPS,
        )

    async def _invoke(params: TaskParameters, signal: Optional[AbortSignal] = None):
        inner = _build_inner(params.subagent_type)
        try:
            result = await run_subagent(inner, params.prompt, signal=signal)
        except AbortError:
            raise  # let the parent's abort race see the cancellation
        except Exception as exc:  # noqa: BLE001 — surface anything else as a tool error
            return error_tool_result(str(exc), "SUBAGENT_FAILED", {"type": params.subagent_type})
        return ok_tool_result(
            result.text,
            {"steps": result.steps, "subagentType": params.subagent_type},
        )

    return define_tool(
        name="task",
        description=(
            "Delegate a focused sub-task to an isolated sub-agent that runs with its own context "
            "and returns only a final report. Use this for broad, read-heavy work (e.g. searching "
            "the repo across many files) to keep your own context clean. Prefer subagent_type "
            "'explore' for investigation; use 'general' only when the sub-task must edit files. "
            "Do NOT use it for trivial single-file operations — just do those directly."
        ),
        parameters=TaskParameters,
        invoke=_invoke,
    )
