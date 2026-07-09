"""bash tool — execute a shell command and return stdout (or stderr on failure).

The TS source hard-coded ``zsh -c``. That breaks on Windows (no `zsh` binary,
`asyncio.create_subprocess_exec("zsh", ...)` raises ``FileNotFoundError``,
which surfaces in the TUI as ``Error: [WinError 2] 系统找不到指定的文件``).

We now resolve the shell at call time:

1. ``$trendpower_BASH_SHELL`` if set — full command-line, e.g. ``bash -c`` or
   ``powershell -NoProfile -Command``. First token is the program, rest are
   prepended to the user's command.
2. Otherwise prefer ``zsh`` → ``bash`` → ``sh`` from PATH (`shutil.which`).
3. Windows fallback: ``%COMSPEC% /c`` (cmd.exe). Last-resort Unix fallback:
   ``/bin/sh -c``.
"""

from __future__ import annotations

import asyncio
import os
import shlex
import shutil
import sys
from typing import List, Optional, Tuple

from pydantic import BaseModel, Field

from ...foundation import AbortSignal, define_tool


class _BashParams(BaseModel):
    description: str = Field(
        description="Explain why you want to execute the command. Always place `description` as the first parameter."
    )
    command: str = Field(description="The bash command to execute.")


def _resolve_shell() -> Optional[Tuple[str, List[str]]]:
    """Return ``(program, args_before_command)`` for the host's best shell.

    Returning ``None`` signals "fall back to the system shell via
    ``create_subprocess_shell``" — this is what we want on Windows when the
    user has no POSIX shell installed, because ``cmd.exe`` quoting through
    ``create_subprocess_exec`` mangles embedded quotes in the command.
    """

    override = os.environ.get("trendpower_BASH_SHELL", "").strip()
    if override:
        try:
            parts = shlex.split(override, posix=(sys.platform != "win32"))
        except ValueError:
            parts = override.split()
        if parts:
            return parts[0], parts[1:]

    for candidate in ("zsh", "bash", "sh"):
        located = shutil.which(candidate)
        if located:
            return located, ["-c"]

    return None


async def _invoke(params: _BashParams, signal: Optional[AbortSignal] = None) -> str:
    resolved = _resolve_shell()
    try:
        if resolved is None:
            # No POSIX shell on PATH and no explicit override. Hand the raw
            # command to the OS shell (cmd.exe on Windows, /bin/sh on Unix)
            # which handles its own quoting.
            proc = await asyncio.create_subprocess_shell(
                params.command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        else:
            shell, shell_args = resolved
            proc = await asyncio.create_subprocess_exec(
                shell,
                *shell_args,
                params.command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
    except FileNotFoundError as error:
        return (
            f"Error: shell program not found ({error}). "
            "Set trendpower_BASH_SHELL to a valid shell command, "
            "e.g. `set trendpower_BASH_SHELL=powershell -NoProfile -Command` on Windows "
            "or `export trendpower_BASH_SHELL=bash -c` on macOS/Linux."
        )

    remove_listener = None
    if signal is not None:
        def _kill() -> None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass

        remove_listener = signal.add_listener(_kill)

    try:
        stdout_bytes, stderr_bytes = await proc.communicate()
    finally:
        if remove_listener is not None:
            remove_listener()

    if proc.returncode != 0:
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        return f"Error: Command {params.command} failed with exit code {proc.returncode}: {stderr}"
    return stdout_bytes.decode("utf-8", errors="replace")


bash_tool = define_tool(
    name="bash",
    description="Execute a bash command in a unix-like environment",
    parameters=_BashParams,
    invoke=_invoke,
)
