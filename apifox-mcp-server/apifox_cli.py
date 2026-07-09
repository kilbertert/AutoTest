# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Thin async wrapper around the `apifox` CLI (v2.x).

Design points (aligned with trendpower AGENTS.md conventions):
- Uses ``asyncio.create_subprocess_exec`` (never ``subprocess.run``).
- The Access Token from the ``APIFOX_ACCESS_TOKEN`` env var is injected as a
  ``--access-token`` argument to the child process. NOTE: apifox CLI v2.x does
  NOT read this env var itself (only ``--access-token`` or `apifox auth login`
  work), so we must pass it as an arg. The token never appears in MCP logs —
  ``run()`` masks it in its log line.
- Captures stdout/stderr as UTF-8 (Apifox CLI emits JSON with non-ASCII chars;
  Windows defaults to gbk otherwise).
- Enforces a timeout per invocation.
- The CLI returns a uniform JSON envelope ``{success, resource, operation,
  data|error, agentHints}`` — callers should check ``parsed["success"]``.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from utils.logger import logger


# Commands that don't need auth. Injecting --access-token into `--version`
# or `auth login` would be wrong / rejected.
_NO_AUTH_COMMANDS = {"--version", "--help", "-h", "auth", "cli-schema"}


@dataclass
class CliResult:
    exit_code: int
    stdout: str
    stderr: str
    parsed: Optional[Any] = field(default=None, repr=False)

    @property
    def ok(self) -> bool:
        # The CLI may exit 0 even on logical failure (it returns JSON with
        # success=false). Trust the JSON envelope when we have it.
        if self.parsed is not None and isinstance(self.parsed, dict):
            return bool(self.parsed.get("success", False))
        return self.exit_code == 0

    @property
    def cli_success(self) -> bool:
        """True only when the CLI envelope says success=true."""
        if isinstance(self.parsed, dict):
            return bool(self.parsed.get("success", False))
        return False

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "exit_code": self.exit_code,
            "cli_success": self.cli_success,
        }
        if self.parsed is not None:
            d["output"] = self.parsed
        else:
            d["output"] = self.stdout.strip()
        if self.stderr.strip():
            d["stderr"] = self.stderr.strip()
        return d

    def error_message(self) -> Optional[str]:
        """Extract a human-readable error from the CLI envelope, if any."""
        if isinstance(self.parsed, dict):
            err = self.parsed.get("error")
            if isinstance(err, dict):
                return err.get("message") or str(err)
            if isinstance(err, str):
                return err
        if self.stderr.strip():
            return self.stderr.strip()[:400]
        return None


class ApifoxCliError(Exception):
    """Raised when the apifox CLI cannot be executed at all."""


class ApifoxCliRunner:
    """Async wrapper around the `apifox` CLI binary."""

    DEFAULT_TIMEOUT = 60.0
    RUN_TIMEOUT = 300.0  # `apifox run` / `test-scenario run` may execute long scenarios

    def __init__(self, binary: Optional[str] = None) -> None:
        # Resolve the apifox binary to a full path. On Windows,
        # create_subprocess_exec doesn't consult PATHEXT, so `apifox` alone
        # fails — `shutil.which` finds `apifox.cmd` / `apifox.exe` for us.
        candidate = binary or os.environ.get("APIFOX_CLI_BINARY") or "apifox"
        resolved = shutil.which(candidate) or shutil.which(candidate + ".cmd")
        self.binary = resolved or candidate  # fall back to the name; error later if truly missing
        self._env = os.environ.copy()

    @property
    def access_token(self) -> Optional[str]:
        return self._env.get("APIFOX_ACCESS_TOKEN")

    @property
    def default_project_id(self) -> Optional[str]:
        return self._env.get("APIFOX_PROJECT_ID")

    @property
    def default_environment_id(self) -> Optional[str]:
        return self._env.get("APIFOX_DEFAULT_ENVIRONMENT_ID")

    def has_token(self) -> bool:
        return bool(self.access_token)

    async def run(
        self,
        args: List[str],
        timeout: Optional[float] = None,
        cwd: Optional[str] = None,
        inject_token: bool = True,
    ) -> CliResult:
        """Run `apifox <args...>` and return a structured result.

        ``--access-token`` is auto-prepended for commands that need auth
        (everything except --version / --help / auth / cli-schema).
        """
        final_args = list(args)
        if inject_token and self.has_token():
            first = final_args[0] if final_args else ""
            if first not in _NO_AUTH_COMMANDS:
                final_args = ["--access-token", self.access_token] + final_args

        # Mask token in log output.
        masked = [("***" if a == self.access_token else a) for a in final_args]
        logger.info(f"apifox CLI run: {self.binary} {' '.join(masked)}")

        if timeout is None:
            # Judge by the ORIGINAL args (before token injection shifts them).
            raw_first = args[0] if args else ""
            raw_second = args[1] if len(args) > 1 else ""
            if raw_first == "run" or (raw_first == "test-scenario" and raw_second == "run"):
                timeout = self.RUN_TIMEOUT
            else:
                timeout = self.DEFAULT_TIMEOUT

        try:
            proc = await asyncio.create_subprocess_exec(
                self.binary,
                *final_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._env,
                cwd=cwd,
            )
        except FileNotFoundError as exc:
            raise ApifoxCliError(
                f"apifox CLI not found on PATH. Install with `npm i -g apifox-cli`. "
                f"Binary tried: {self.binary}"
            ) from exc

        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise ApifoxCliError(
                f"apifox CLI timed out after {timeout}s: {self.binary} {' '.join(masked)}"
            )

        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")

        parsed = None
        stripped = stdout.strip()
        if stripped:
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                parsed = None

        result = CliResult(
            exit_code=proc.returncode if proc.returncode is not None else -1,
            stdout=stdout,
            stderr=stderr,
            parsed=parsed,
        )
        if not result.ok:
            logger.warning(
                f"apifox CLI non-success: {self.binary} {' '.join(masked)} :: "
                f"exit={result.exit_code} err={result.error_message()}"
            )
        return result
