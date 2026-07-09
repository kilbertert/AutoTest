"""Top-level Textual App."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical

from .config import (
    TrendpowerConfig,
    ensure_trendpower_home_directory,
    ensure_trendpower_home_env,
    is_trendpower_setup_complete,
    load_config,
    save_config,
)
from .mcp import MCPLifecycle
from .sessions import (
    list_sessions,
    load_session,
    new_session_id,
    save_session,
)
from .sessions import delete_session as delete_saved_session
from .settings import SettingsApprovalPersistence
from .tui.agent_runner import (
    AgentMessageEvent,
    AgentProgressEvent,
    AgentRunner,
    StreamingChanged,
)
from .tui.command_registry import (
    SlashCommand,
    build_prompt_submission,
    format_help,
    load_available_commands,
    resolve_builtin_command,
)
from .tui.file_view import build_file_entries
from .tui.skill_paths import discover_skills_dirs
from .tui.todo_view import build_todo_view_state
from .tui.transcript import transcript_to_text
from .tui.token_usage import calculate_token_usage
from .tui.widgets.approval_bar import ApprovalBar, ApprovalDecided
from .tui.widgets.ask_user_question_bar import AnswersSubmitted, AskUserQuestionBar
from .tui.widgets.brand_header import BrandHeader
from .tui.widgets.code_panel import CodePanel, FileSaved
from .tui.widgets.first_run_wizard import FirstRunWizardScreen
from .tui.widgets.model_manager import (
    ModelManagerAction,
    ModelManagerScreen,
    apply_append,
    apply_remove,
    apply_switch,
)
from .tui.widgets.resume_screen import ResumeAction, ResumeScreen
from .tui.widgets.command_list import CommandList
from .tui.widgets.input_box import CommandInputChanged, CommandSubmitted, InputBox
from .tui.widgets.message_history import MessageHistory
from .tui.widgets.status_footer import StatusFooter
from .tui.widgets.streaming_indicator import StreamingIndicator
from .tui.widgets.todo_panel import TodoPanel


class TrendpowerApp(App):
    """Textual frontend for the trendpower coding agent."""

    CSS_PATH = "tui/theme.tcss"
    # `ctrl+c` is priority so it beats the focused Input's own copy binding:
    # it copies the active text selection if there is one, otherwise quits
    # (preserving the usual muscle memory). `ctrl+q` always quits.
    BINDINGS = [
        Binding("ctrl+c", "copy_or_quit", "Copy/Quit", priority=True),
        Binding("ctrl+q", "quit", "Quit", priority=True),
        Binding("ctrl+s", "save_code_file", "Save file", priority=True),
        Binding("escape", "abort_or_quit", "Abort/Quit"),
    ]
    TITLE = "trendpower"

    def __init__(self) -> None:
        super().__init__()
        self.runner: AgentRunner | None = None
        self.messages: list[dict] = []
        self.commands: list[SlashCommand] = []
        self.model_name: str | None = None
        self.skills_dirs: list[str] = []
        self.skills_found: int = 0
        self._unsubscribe_approval = None
        self._unsubscribe_ask_question = None
        self.mcp = MCPLifecycle()
        self._mcp_tools: list = []
        # Session persistence: an id is minted lazily on the first real prompt
        # and the transcript is re-saved after every completed run.
        self.session_id: str | None = None
        self.session_created: float | None = None

    def compose(self) -> ComposeResult:
        yield BrandHeader(id="brand")
        # Main content splits horizontally: the left column keeps the original
        # transcript + execution-step widgets; the right column (hidden until a
        # coding task touches files) shows the editable code panel.
        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield MessageHistory(id="history")
                yield TodoPanel(id="todos")
                yield StreamingIndicator(id="streaming")
                yield CommandList(id="commands")
            yield CodePanel(id="code")
        # Bottom dock siblings — `#status` is yielded first so it sits at the
        # very bottom; the input / approval / ask-question bars stack above
        # status and only one of those three is visible at a time.
        yield StatusFooter(id="status")
        yield InputBox(id="input")
        yield ApprovalBar(id="approval-bar")
        yield AskUserQuestionBar(id="ask-bar")

    async def on_mount(self) -> None:
        ensure_trendpower_home_env()
        # Always compute skills_dirs first, even before checking config, so the
        # /help list and the agent prompt see the same set of skills.
        self.skills_dirs = discover_skills_dirs(os.getcwd())
        self.commands = await load_available_commands(self.skills_dirs)
        self.skills_found = sum(1 for command in self.commands if command.type == "skill")
        try:
            self._mcp_tools = await self.mcp.startup()
        except Exception as exc:  # noqa: BLE001
            self._mcp_tools = []
            self._append_system_text(f"MCP startup failed: {exc}")
        await self._try_create_runner()
        self._subscribe_to_managers()
        if self.runner is None:
            self._append_system_text(
                "未配置模型 (No models configured)。请按 Enter 启动首次运行向导，"
                "或者在另一个终端运行 `trendpower config model add ...` 后重启 TUI。"
            )
            self.call_later(self._launch_first_run_wizard)
        else:
            self._append_system_text(self._startup_banner())
            self.query_one(InputBox).focus()
        self._refresh_derived_views()

    def _launch_first_run_wizard(self) -> None:
        def on_dismiss(entry) -> None:
            if entry is None:
                self._append_system_text(
                    "已取消首次运行向导。可随时使用 `/model` 或 `trendpower config model add ...` 再来配置。"
                )
                return
            # First-run replaces the config wholesale.
            ensure_trendpower_home_directory()
            save_config(TrendpowerConfig(models=[entry], defaultModel=entry.name))
            self._append_system_text(f"已写入新模型 `{entry.name}` 并设为默认。重建 agent…")
            self._retry_setup()

        self.push_screen(FirstRunWizardScreen(), on_dismiss)

    def open_model_manager(self) -> None:
        """Public entrypoint used by `/model` slash command."""

        if not is_trendpower_setup_complete():
            # Treat /model on a fresh install the same as first-run wizard.
            self._launch_first_run_wizard()
            return
        try:
            config = load_config()
        except Exception as error:
            self._append_system_text(f"读取配置失败: {error}")
            return
        if not config.models:
            self._launch_first_run_wizard()
            return

        def on_dismiss(action: ModelManagerAction | None) -> None:
            if action is None or action.kind == "none":
                return
            if action.kind == "switch":
                self._switch_default_model(config, action.payload or "")
            elif action.kind == "remove":
                self._remove_model(config, action.payload or "")
            elif action.kind == "add":
                self._launch_add_model_wizard()

        self.push_screen(ModelManagerScreen(config), on_dismiss)

    def _switch_default_model(self, config: TrendpowerConfig, model_name: str) -> None:
        if not model_name:
            return
        current_default = config.defaultModel or (config.models[0].name if config.models else None)
        if model_name == current_default and self.model_name == model_name:
            self._append_system_text(f"`{model_name}` 已经是默认模型。")
            return
        updated = apply_switch(config, model_name)
        save_config(updated)
        self._append_system_text(f"已切换默认模型为 `{model_name}`，正在重建 agent…")
        self._retry_setup()

    def _remove_model(self, config: TrendpowerConfig, model_name: str) -> None:
        if not model_name:
            return
        updated = apply_remove(config, model_name)
        if len(updated.models) == len(config.models):
            self._append_system_text(f"未找到模型 `{model_name}`。")
            return
        save_config(updated)
        suffix = ""
        if config.defaultModel == model_name and updated.defaultModel:
            suffix = f"，默认模型已切换为 `{updated.defaultModel}`"
        self._append_system_text(f"已删除模型 `{model_name}`{suffix}。重建 agent…")
        self._retry_setup()

    def _launch_add_model_wizard(self) -> None:
        def on_dismiss(entry) -> None:
            if entry is None:
                self._append_system_text("已取消添加。")
                # Re-open the manager so the user is back where they came from.
                self.call_later(self.open_model_manager)
                return
            ensure_trendpower_home_directory()
            try:
                current = load_config()
            except Exception:
                current = TrendpowerConfig(models=[], defaultModel=None)
            updated = apply_append(current, entry)
            save_config(updated)
            self._append_system_text(
                f"已添加模型 `{entry.name}`，并设为默认。重建 agent…"
            )
            self._retry_setup()

        self.push_screen(FirstRunWizardScreen(title="添加新模型 / Add a model"), on_dismiss)

    @work(exclusive=True)
    async def _retry_setup(self) -> None:
        # Tear down the old runner + subscriptions before swapping. The agent
        # itself is GC'd once nothing references it, but we abort in case a
        # request is still in flight.
        if self.runner is not None:
            try:
                self.runner.abort()
            except Exception:
                pass
        for handle_name in ("_unsubscribe_approval", "_unsubscribe_ask_question"):
            handle = getattr(self, handle_name, None)
            if handle is not None:
                try:
                    handle()
                except Exception:
                    pass
                setattr(self, handle_name, None)
        self.runner = None
        self.model_name = None

        # Refresh skills_dirs in case the user added skills in another shell.
        self.skills_dirs = discover_skills_dirs(os.getcwd())
        self.commands = await load_available_commands(self.skills_dirs)
        self.skills_found = sum(1 for command in self.commands if command.type == "skill")

        await self._try_create_runner()
        self._subscribe_to_managers()
        if self.runner is not None:
            self._append_system_text(self._startup_banner())
            self.query_one(InputBox).focus()
        self._refresh_derived_views()

    async def on_unmount(self) -> None:
        if self._unsubscribe_approval is not None:
            try:
                self._unsubscribe_approval()
            except Exception:
                pass
        if self._unsubscribe_ask_question is not None:
            try:
                self._unsubscribe_ask_question()
            except Exception:
                pass
        try:
            await self.mcp.shutdown()
        except Exception:
            pass

    def _startup_banner(self) -> str:
        lines = [
            f"Trendpower 已就绪。Model: `{self.model_name or '(none)'}`",
            f"Skills found: {self.skills_found}",
            f"Skill dirs scanned: {', '.join(self.skills_dirs) or '(none)'}",
        ]
        if self.mcp.startup_summary:
            lines.append(self.mcp.startup_summary)
        lines.append(
            "_提示：拖动鼠标选中文本后按 ctrl+c 复制（ctrl+q 退出）；"
            "`/resume` 恢复历史对话，`/export` 导出当前对话。_"
        )
        return "\n".join(lines)

    async def _try_create_runner(self) -> None:
        if not is_trendpower_setup_complete():
            return

        config = load_config()
        if not config.models:
            return
        default_name = config.defaultModel or config.models[0].name
        entry = next(
            (model for model in config.models if model.name == default_name),
            config.models[0],
        )
        self.model_name = entry.name

        from trendpower.coding import (
            create_coding_agent,
            global_approval_manager,
            global_ask_user_question_manager,
        )
        from trendpower.community.anthropic import AnthropicModelProvider
        from trendpower.community.openai import OpenAIModelProvider
        from trendpower.foundation import Model

        if entry.provider == "anthropic":
            provider = AnthropicModelProvider(base_url=entry.baseURL, api_key=entry.APIKey)
        else:
            provider = OpenAIModelProvider(base_url=entry.baseURL, api_key=entry.APIKey)

        model_options: dict[str, Any] = {"max_tokens": 16 * 1024}
        if entry.provider == "anthropic":
            model_options["thinking"] = {"type": "enabled"}

        model = Model(entry.name, provider, model_options)
        cwd = os.getcwd()
        approval_persistence = SettingsApprovalPersistence()

        def on_compaction(event) -> None:
            # Fires from inside the agent loop (same event loop); schedule the
            # notice so it lands after the current await chain.
            self.call_later(
                lambda: self._append_system_text(
                    f"_Context compacted: {event.messages_before} → "
                    f"{event.messages_after} messages (~{event.estimated_tokens:,} tokens)._"
                )
            )

        agent = await create_coding_agent(
            model=model,
            cwd=cwd,
            skills_dirs=self.skills_dirs,
            ask_user=global_approval_manager.ask_user,
            ask_user_question=global_ask_user_question_manager.ask_user_question,
            approval_persistence=approval_persistence,
            extra_tools=list(self._mcp_tools) or None,
            on_compaction=on_compaction,
            tracing_sink=self._build_tracing_sink(),
        )
        self.runner = AgentRunner(agent, target=self)

    def _build_tracing_sink(self):
        """Trace sink for agent runs, or ``None``.

        Opt-in via ``trendpower_TRACE=1``: writes a JSONL span trace per run under
        ``$trendpower_HOME/traces/``, viewable with ``trendpower trace view``.
        trendpower-web overrides this to also stream spans to the browser.
        """
        if os.environ.get("trendpower_TRACE", "").strip() in ("", "0", "false"):
            return None
        from trendpower.agent.tracing import JsonlSink

        from .config import get_trendpower_home_path

        return JsonlSink(get_trendpower_home_path() / "traces")

    def _subscribe_to_managers(self) -> None:
        if self.runner is None:
            return
        from trendpower.coding import global_approval_manager, global_ask_user_question_manager

        def on_approval_request(request) -> None:
            if request is None:
                return
            # Schedule on the event loop so push_screen happens after the
            # current await chain returns; this also handles the case where the
            # callback fires synchronously from inside a tool invocation.
            captured = request
            self.call_later(lambda: self._show_approval_screen(captured))

        def on_ask_user_question_request(request) -> None:
            if request is None:
                return
            captured = request
            self.call_later(lambda: self._show_ask_user_question_screen(captured))

        # subscribe() returns the unsubscribe handle in the Python port. The TS
        # version returned nothing useful so we keep the handle defensively.
        try:
            self._unsubscribe_approval = global_approval_manager.subscribe(on_approval_request)
        except Exception:
            self._unsubscribe_approval = None
        try:
            self._unsubscribe_ask_question = global_ask_user_question_manager.subscribe(
                on_ask_user_question_request
            )
        except Exception:
            self._unsubscribe_ask_question = None

    def _show_approval_screen(self, request) -> None:
        bar = self.query_one(ApprovalBar)
        # Hide the input slot while the bar is active so they don't both try to
        # occupy the same bottom row.
        self.query_one(InputBox).display = False
        self.query_one(AskUserQuestionBar).hide()
        bar.show_for(dict(request.tool_use))

    def _show_ask_user_question_screen(self, request) -> None:
        bar = self.query_one(AskUserQuestionBar)
        self.query_one(InputBox).display = False
        self.query_one(ApprovalBar).hide()
        bar.show_for(list(request.params.get("questions", [])))

    def on_approval_decided(self, event: ApprovalDecided) -> None:
        from trendpower.coding import global_approval_manager

        self.query_one(ApprovalBar).hide()
        self._restore_input_focus()
        global_approval_manager.respond(event.decision)

    def on_answers_submitted(self, event: AnswersSubmitted) -> None:
        from trendpower.coding import global_ask_user_question_manager

        self.query_one(AskUserQuestionBar).hide()
        self._restore_input_focus()
        global_ask_user_question_manager.respond_with_answers({"answers": event.answers})

    def _restore_input_focus(self) -> None:
        input_widget = self.query_one(InputBox)
        input_widget.display = True
        input_widget.focus()

    def on_command_submitted(self, event: CommandSubmitted) -> None:
        text = event.text.strip()
        if not text:
            return
        invocation = resolve_builtin_command(text)
        if invocation and invocation.name == "clear":
            self.query_one(MessageHistory).clear()
            self.messages = []
            self.session_id = None
            self.session_created = None
            if self.runner is not None:
                self.runner.agent.clear_messages()
            self._refresh_derived_views()
            return
        if invocation and invocation.name in {"exit", "quit"}:
            self.action_quit()
            return
        if invocation and invocation.name == "help":
            self._append_system_text(format_help(self.commands, invocation.args or None))
            return
        if invocation and invocation.name == "model":
            self.open_model_manager()
            return
        if invocation and invocation.name == "mcp":
            self.handle_mcp_command(invocation.args)
            return
        if invocation and invocation.name == "copy":
            self.handle_copy_command()
            return
        if invocation and invocation.name == "export":
            self.handle_export_command(invocation.args)
            return
        if invocation and invocation.name == "resume":
            self.handle_resume_command(invocation.args)
            return
        if self.runner is None:
            self._append_system_text("尚未创建 Agent。请先用 `trendpower config model add ...` 配置模型。")
            return
        # Mint a session id on the first real prompt so empty sessions are never
        # persisted; the transcript is saved when the run completes.
        if self.session_id is None:
            self.session_id = new_session_id()
            self.session_created = time.time()
        submission = build_prompt_submission(text, self.commands)
        self.submit_user_text(submission.text, submission.requested_skill_name)

    def on_command_input_changed(self, event: CommandInputChanged) -> None:
        text = event.text.strip()
        query = text[1:] if text.startswith("/") and " " not in text else ""
        self.query_one(CommandList).set_commands(self.commands, query)

    @work(exclusive=True)
    async def submit_user_text(self, text: str, requested_skill: str | None = None) -> None:
        assert self.runner is not None
        await self.runner.submit(text, requested_skill=requested_skill)

    # --- /copy and /export -------------------------------------------------

    def handle_copy_command(self) -> None:
        text = transcript_to_text(self.messages)
        if not text.strip():
            self._append_system_text("当前没有可复制的对话内容。")
            return
        self.copy_to_clipboard(text)
        self._append_system_text(
            f"已复制整段对话到剪贴板（{len(text)} 字符）。"
            "\n_若终端不支持 OSC52 剪贴板，可改用 `/export` 写入文件。_"
        )

    def handle_export_command(self, args: str) -> None:
        text = transcript_to_text(self.messages)
        if not text.strip():
            self._append_system_text("当前没有可导出的对话内容。")
            return
        target = (args or "").strip()
        if target:
            path = Path(target).expanduser()
        else:
            stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
            path = Path(os.getcwd()) / f"trendpower-transcript-{stamp}.md"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        except OSError as error:
            self._append_system_text(f"导出失败：{error}")
            return
        self._append_system_text(f"已导出对话到 `{path}`（{len(text)} 字符）。")

    # --- /resume -----------------------------------------------------------

    def handle_resume_command(self, args: str) -> None:
        sessions = list_sessions()
        target = (args or "").strip()
        if target:
            match = next(
                (meta for meta in sessions if meta.id == target or meta.id.startswith(target)),
                None,
            )
            if match is None:
                self._append_system_text(
                    f"未找到会话 `{target}`。运行 `/resume` 查看全部已保存的对话。"
                )
                return
            self._resume_session(match.id)
            return
        if not sessions:
            self._append_system_text("还没有任何已保存的对话。先聊几句，结束后会自动保存。")
            return

        def on_dismiss(action: ResumeAction | None) -> None:
            if action is None or action.kind == "none":
                return
            if action.kind == "resume" and action.payload:
                self._resume_session(action.payload)
            elif action.kind == "delete" and action.payload:
                if delete_saved_session(action.payload):
                    if self.session_id == action.payload:
                        self.session_id = None
                        self.session_created = None
                    self._append_system_text(f"已删除会话 `{action.payload}`。")
                else:
                    self._append_system_text(f"删除会话 `{action.payload}` 失败。")
                # Re-open the picker so the user can keep managing sessions.
                self.call_later(lambda: self.handle_resume_command(""))

        self.push_screen(ResumeScreen(sessions), on_dismiss)

    def _resume_session(self, session_id: str) -> None:
        if self.runner is None:
            self._append_system_text("尚未创建 Agent，无法恢复会话。请先配置模型。")
            return
        if self.query_one(StreamingIndicator).streaming:
            self._append_system_text("正在生成回复，请等当前回合结束后再恢复会话。")
            return
        try:
            meta, messages = load_session(session_id)
        except (OSError, ValueError) as error:
            self._append_system_text(f"读取会话 `{session_id}` 失败：{error}")
            return

        # Reload into both the UI transcript and the agent's working memory so
        # the model has the full prior context, then re-render from scratch.
        self.session_id = meta.id
        self.session_created = meta.created or time.time()
        self.runner.agent.load_messages(messages)
        self.messages = list(messages)
        history = self.query_one(MessageHistory)
        history.clear()
        todo_state = build_todo_view_state(self.messages)
        for index, message in enumerate(self.messages):
            history.append_message(
                message,
                message_index=index,
                todo_snapshots=todo_state.todo_snapshots,
            )
        self._append_system_text(
            f"已恢复会话 `{meta.id}` · {meta.message_count} 条消息 · {meta.title}"
        )
        self._refresh_derived_views()

    def _persist_session(self) -> None:
        if self.session_id is None or self.runner is None:
            return
        messages = list(self.runner.agent.messages)
        if not messages:
            return
        try:
            save_session(
                self.session_id,
                messages,
                model=self.model_name,
                cwd=os.getcwd(),
                created=self.session_created,
            )
        except OSError:
            # Persistence is best-effort; never let it break the UI loop.
            pass

    # --- /mcp slash command ------------------------------------------------

    def handle_mcp_command(self, args: str) -> None:
        sub = (args or "").strip().lower()
        if sub in ("", "help"):
            self._append_system_text(
                "**/mcp** — manage MCP servers\n"
                "\n"
                f"Config file: `{self.mcp.config_path}`\n"
                "\n"
                "Subcommands:\n"
                "- `/mcp list` — show every configured server and its status\n"
                "- `/mcp reload` — re-read the config file and reconnect all servers"
            )
            return
        if sub == "list":
            self._append_system_text(self._format_mcp_list())
            return
        if sub == "reload":
            self._mcp_reload_async()
            return
        self._append_system_text(
            f"Unknown /mcp subcommand: `{sub}`. Try `/mcp`, `/mcp list`, or `/mcp reload`."
        )

    def _format_mcp_list(self) -> str:
        statuses = self.mcp.status()
        if not statuses:
            return (
                f"No MCP servers configured. To add one, create "
                f"`{self.mcp.config_path}` (see `docs/mcp.md`)."
            )
        lines = ["**MCP servers**", ""]
        lines.append("| name | transport | status | tools | error |")
        lines.append("|---|---|---|---:|---|")
        for s in statuses:
            err = (s.error or "").replace("|", "\\|").replace("\n", " ")
            if len(err) > 80:
                err = err[:77] + "..."
            lines.append(
                f"| `{s.name}` | {s.transport} | {s.status} | {s.tool_count} | {err} |"
            )
        return "\n".join(lines)

    @work(exclusive=True)
    async def _mcp_reload_async(self) -> None:
        self._append_system_text("Reloading MCP servers...")
        try:
            tools = await self.mcp.reload()
        except Exception as exc:  # noqa: BLE001
            self._append_system_text(f"MCP reload failed: {exc}")
            return
        self._mcp_tools = tools
        self._append_system_text(
            f"MCP reload complete. {len(tools)} tool(s) available.\n"
            f"_Note: existing agent session keeps its prior toolset until restart._"
        )
        self._append_system_text(self._format_mcp_list())

    def on_agent_message_event(self, event: AgentMessageEvent) -> None:
        self._append_message(event.payload)

    def on_agent_progress_event(self, event: AgentProgressEvent) -> None:
        self.query_one(StreamingIndicator).progress_text = event.text

    def on_streaming_changed(self, event: StreamingChanged) -> None:
        indicator = self.query_one(StreamingIndicator)
        indicator.streaming = event.streaming
        if not event.streaming:
            indicator.progress_text = ""
            # A turn just finished — checkpoint the transcript to disk.
            self._persist_session()

    def action_copy_or_quit(self) -> None:
        # Copy the active mouse selection (works across the message history even
        # while the InputBox holds focus). With nothing selected, fall back to
        # quitting so ctrl+c keeps its familiar behavior.
        selected = self.screen.get_selected_text()
        if not selected:
            focused = self.focused
            selected = getattr(focused, "selected_text", "") if focused is not None else ""
        if selected:
            self.copy_to_clipboard(selected)
            self.screen.clear_selection()
            self.notify(f"Copied {len(selected)} chars to clipboard", timeout=2)
            return
        self.action_quit()

    def action_abort_or_quit(self) -> None:
        if self.runner is not None and self.query_one(StreamingIndicator).streaming:
            self.runner.abort()
            return
        self.action_quit()

    def action_quit(self) -> None:
        if self.runner is not None:
            self.runner.abort()
        self.exit()

    def _append_system_text(self, text: str) -> None:
        self._append_message({"role": "assistant", "content": [{"type": "text", "text": text}]})

    def _append_message(self, message: dict) -> None:
        message_index = len(self.messages)
        self.messages.append(message)
        todo_state = build_todo_view_state(self.messages)
        self.query_one(MessageHistory).append_message(
            message,
            message_index=message_index,
            todo_snapshots=todo_state.todo_snapshots,
        )
        self._refresh_derived_views()

    def _refresh_derived_views(self) -> None:
        todo_state = build_todo_view_state(self.messages)
        token_usage = calculate_token_usage(self.messages)
        self.query_one(BrandHeader).update_status(
            model_name=self.model_name,
            ready=self.runner is not None,
            skills_count=self.skills_found,
        )
        self.query_one(TodoPanel).set_todos(todo_state.latest_todos)
        self.query_one(CodePanel).set_files(build_file_entries(self.messages, os.getcwd()))
        self.query_one(StatusFooter).update_status(self.model_name, token_usage)

    def action_save_code_file(self) -> None:
        panel = self.query_one(CodePanel)
        if panel.display:
            panel.save_current()

    def on_file_saved(self, event: FileSaved) -> None:
        # The on-disk file now holds the user's edits; the core file-change
        # tracker will surface them to the agent on the next turn.
        self.notify(f"已保存 {os.path.relpath(event.path, os.getcwd())}", timeout=2)
