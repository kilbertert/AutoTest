"""The Trendpower lead coding agent — same prompt + same toolset as the TS version."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Awaitable, Callable, List, Optional

from ...agent import Agent
from ...agent.compaction import CompactionEvent, create_compaction_middleware
from ...agent.skills.skills_middleware import create_skills_middleware
from ...agent.todos.todos import create_todo_system
from ...agent.tracing import TraceSink, create_tracing_middleware
from ..file_change_tracker import create_file_change_tracker
from ...foundation import Model, NonSystemMessage, Tool, ToolUseContent
from ..permissions import (
    CODING_TOOLS_REQUIRING_APPROVAL,
    ApprovalDecision,
    ApprovalPersistence,
    create_coding_approval_middleware,
)
from ..tools.apply_patch import apply_patch_tool
from ..tools.ask_user_question import (
    AskUserQuestionParameters,
    AskUserQuestionResult,
    create_ask_user_question_tool,
)
from ..tools.bash import bash_tool
from ..tools.file_info import file_info_tool
from ..tools.glob_search import glob_search_tool
from ..tools.grep_search import grep_search_tool
from ..tools.list_files import list_files_tool
from ..tools.mkdir import mkdir_tool
from ..tools.move_path import move_path_tool
from ..tools.read_file import read_file_tool
from ..tools.str_replace import str_replace_tool
from ..tools.task import create_task_tool
from ..tools.write_file import write_file_tool


async def create_coding_agent(
    *,
    model: Model,
    cwd: Optional[str] = None,
    skills_dirs: Optional[List[str]] = None,
    ask_user: Optional[Callable[[ToolUseContent], Awaitable[ApprovalDecision]]] = None,
    ask_user_question: Optional[
        Callable[[AskUserQuestionParameters], Awaitable[AskUserQuestionResult]]
    ] = None,
    approval_persistence: Optional[ApprovalPersistence] = None,
    extra_tools: Optional[List[Tool]] = None,
    enable_compaction: bool = True,
    compaction_trigger_tokens: int = 100_000,
    on_compaction: Optional[Callable[[CompactionEvent], None]] = None,
    enable_subagents: bool = True,
    tracing_sink: Optional[TraceSink] = None,
) -> Agent:
    if cwd is None:
        cwd = os.getcwd()
    if skills_dirs is None:
        skills_dirs = [str(Path(cwd) / ".agents" / "skills")]

    messages: List[NonSystemMessage] = []
    agents_file = Path(cwd) / "AGENTS.md"
    agents_section = ""
    if agents_file.exists():
        agents_content = agents_file.read_text(encoding="utf-8")
        # Project framing belongs in the system prompt: it is run-stable, so it
        # stays inside the cached prefix and never gets spent by compaction
        # (which only ever rewrites the conversation messages, not the prompt).
        agents_section = (
            "\n<project_instructions>\n"
            "The `AGENTS.md` file has been automatically loaded. Here is the content:\n\n"
            + agents_content
            + "\n</project_instructions>\n"
        )

    todo_tool, todo_middleware = create_todo_system()
    ask_user_question_tool = (
        create_ask_user_question_tool(ask_user_question) if ask_user_question else None
    )

    # When tracing is on, fold compaction events into the trace alongside any
    # caller-supplied on_compaction handler.
    tracing_middleware = (
        create_tracing_middleware(tracing_sink, model_name=model.name)
        if tracing_sink is not None
        else None
    )
    compaction_callback = on_compaction
    if tracing_middleware is not None:

        def compaction_callback(event: CompactionEvent) -> None:
            if on_compaction is not None:
                on_compaction(event)
            tracing_middleware.emit_compaction(event)

    middlewares = [
        create_skills_middleware(skills_dirs),
        todo_middleware,
        create_file_change_tracker(),
    ]
    if enable_compaction:
        # Prepend so the transcript is compacted before other beforeModel hooks
        # read it. Uses the agent's own model to summarize the dropped span.
        middlewares.insert(
            0,
            create_compaction_middleware(
                trigger_tokens=compaction_trigger_tokens,
                model=model,
                on_compaction=compaction_callback,
            ),
        )
    if ask_user is not None:
        middlewares.append(
            create_coding_approval_middleware(
                cwd=cwd,
                requires_approval=CODING_TOOLS_REQUIRING_APPROVAL,
                ask_user=ask_user,
                approval_persistence=approval_persistence,
            )
        )
    if tracing_middleware is not None:
        # Read-only observer; sits last so its model/tool timing brackets the
        # work the other middlewares schedule.
        middlewares.append(tracing_middleware)

    subagents_section = ""
    if enable_subagents:
        subagents_section = (
            "\n<subagents>\n"
            "You can delegate a focused sub-task to an isolated sub-agent via the `task` tool. "
            "The sub-agent runs with its own context and returns only a final report, so use it "
            "for broad, read-heavy work (e.g. searching the repo across many files, investigating "
            "how a feature works) to keep your own context clean.\n"
            "- Prefer subagent_type 'explore' (read-only) for investigation and search.\n"
            "- Use 'general' only when the sub-task must edit files or run commands.\n"
            "- Give the sub-agent a fully self-contained prompt; it cannot see this conversation.\n"
            "- Do NOT delegate trivial single-file operations — just do those directly.\n"
            "</subagents>\n"
        )

    prompt = (
        f'<agent name="Trendpower" role="leading_agent" description="A coding agent">\n'
        f"Use the given tools and skills to perform parallel/sequential operations and solve the user's problem in the given working directory.\n"
        f"</agent>\n\n"
        f'<working_directory dir="{cwd}/" />\n\n'
        f"<tool_usage>\n"
        f"- Inspect directories before assuming file paths.\n"
        f"- Prefer list_files or glob_search to discover files.\n"
        f"- Prefer grep_search to locate relevant content.\n"
        f"- Read a file before editing it.\n"
        f"- Prefer apply_patch for targeted edits.\n"
        f"- If apply_patch fails, re-read the file and choose a safer edit strategy.\n"
        f"- Do not repeat the same failing tool call with unchanged invalid input.\n"
        f"- Use tool result summaries and error codes to decide the next step.\n"
        f"</tool_usage>\n\n"
        f"<notes>\n"
        f"- Never try to start a local static server. Let the user do it.\n"
        f"- If the user's input is a simple task or a greeting, you should just respond with a simple answer and then stop.\n"
        f"- For a multi-step coding task (roughly 3+ distinct steps, or several files), start by laying out a plan with `todo_write`, then work through it and keep statuses current. Skip the todo list for simple, single-step changes — use judgment, don't force it.\n"
        f"</notes>\n"
        f"{subagents_section}"
        f"{agents_section}"
    )

    tools = [
        bash_tool,
        file_info_tool,
        list_files_tool,
        glob_search_tool,
        grep_search_tool,
        mkdir_tool,
        move_path_tool,
        read_file_tool,
        write_file_tool,
        str_replace_tool,
        apply_patch_tool,
        todo_tool,
    ]
    if ask_user_question_tool is not None:
        tools.append(ask_user_question_tool)
    if extra_tools:
        tools.extend(extra_tools)

    if enable_subagents:
        # base_tools is a snapshot taken before `task` is appended, so a
        # sub-agent never receives the task tool itself (recursion guard).
        tools.append(
            create_task_tool(
                model=model,
                cwd=cwd,
                base_tools=list(tools),
                ask_user=ask_user,
                approval_persistence=approval_persistence,
                compaction_trigger_tokens=compaction_trigger_tokens,
                tracing_sink=tracing_sink,
            )
        )

    return Agent(
        model=model,
        prompt=prompt,
        messages=messages,
        tools=tools,
        middlewares=middlewares,
    )
