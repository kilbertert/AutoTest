# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Scenario tools: list and run pre-arranged test scenarios from Apifox.

Use run sparingly. Scenarios' assertions/extracts are configured in the Apifox
GUI beforehand — `apifox run` / `test-scenario run` only execute them, they
cannot accept inline assertions. So this is for "run the QA team's regression
scenario X", NOT for "let the LLM write a fresh test" (that path goes through
apifox_get_endpoint_detail + api-mcp's http_*/assert_* instead).
"""

from __future__ import annotations

import os
import tempfile
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from apifox_cli import ApifoxCliRunner
from utils.logger import log_tool_call, logger
from utils.response_format import format_tool_response, init_tool_response


def _resolve_project_id(cli: ApifoxCliRunner, project_id: Optional[str]) -> Optional[str]:
    return project_id or cli.default_project_id


def _missing_project_response():
    resp = init_tool_response()
    resp["status"] = "error"
    resp["error"] = (
        "project_id not provided and APIFOX_PROJECT_ID env var not set. "
        "Pass project_id explicitly or configure it in mcp_servers.json env."
    )
    return format_tool_response(resp)


def _scenario_list_from_data(data: Any) -> List[Dict[str, Any]]:
    items: Any = None
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for key in ("list", "items", "testScenarios", "data"):
            if isinstance(data.get(key), list):
                items = data[key]
                break
    if not isinstance(items, list):
        return []
    out: List[Dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        out.append({
            "id": it.get("id"),
            "name": it.get("name"),
            "priority": it.get("priority"),
            "folder_id": it.get("folderId") or it.get("folder_id"),
            "step_count": it.get("stepCount") or it.get("step_count"),
        })
    return out


def register_scenario_tools(mcp: FastMCP, cli: ApifoxCliRunner):

    @mcp.tool()
    @log_tool_call
    async def apifox_list_scenarios(project_id: Optional[str] = None):
        """List test scenarios in an Apifox project.

        A test scenario is an ordered sequence of API requests (with control
        flow, assertions, and variable extracts) that QA has arranged in the
        Apifox GUI. Use this to find a scenario's id, then run it with
        apifox_run_scenario.

        Args:
            project_id: Apifox project ID. If omitted, uses APIFOX_PROJECT_ID env var.

        Returns:
            A list of {id, name, priority, folder_id, step_count}.
        """
        pid = _resolve_project_id(cli, project_id)
        if not pid:
            return _missing_project_response()

        try:
            result = await cli.run(["test-scenario", "list", "--project", pid])
        except Exception as e:
            resp = init_tool_response()
            resp["status"] = "error"
            resp["error"] = f"Failed to run apifox test-scenario list: {e}"
            return format_tool_response(resp)

        if not result.ok:
            resp = init_tool_response()
            resp["status"] = "error"
            resp["error"] = result.error_message() or f"apifox test-scenario list failed (exit {result.exit_code})"
            return format_tool_response(resp)

        data = result.parsed.get("data") if isinstance(result.parsed, dict) else None
        scenarios = _scenario_list_from_data(data)
        logger.info(f"apifox_list_scenarios: {len(scenarios)} scenarios in project {pid}")

        resp = init_tool_response()
        resp["status"] = "success"
        resp["data"] = {"project_id": pid, "count": len(scenarios), "scenarios": scenarios}
        return format_tool_response(resp)

    @mcp.tool()
    @log_tool_call
    async def apifox_run_scenario(
        scenario_id: str,
        project_id: Optional[str] = None,
        environment_id: Optional[str] = None,
        reporters: str = "cli,json",
        iteration_count: int = 1,
        out_dir: Optional[str] = None,
    ):
        """Run a pre-arranged test scenario from the Apifox platform.

        Executes `apifox run -t <scenario_id>` against a scenario QA has already
        set up in the Apifox GUI (assertions/extracts baked in). Returns a
        pass/fail summary plus the path to the generated report.

        When to use: only when the user explicitly asks to run an Apifox
        regression/smoke scenario (e.g. "跑一下 Apifox 上的登录回归场景"). For
        exploratory "test this endpoint" requests, use apifox_get_endpoint_detail
        + api-mcp's http_*/assert_* instead.

        Args:
            scenario_id: Test scenario ID (from apifox_list_scenarios).
            project_id: Apifox project ID. If omitted, uses APIFOX_PROJECT_ID env var.
            environment_id: Apifox environment ID (-e). If omitted, uses
                            APIFOX_DEFAULT_ENVIRONMENT_ID env var.
            reporters: Comma-separated report formats (cli,html,json,junit).
                       Default "cli,json".
            iteration_count: Number of iterations (-n). Default 1.
            out_dir: Where to write reports. Defaults to a fresh temp dir.

        Returns:
            {ok, exit_code, report_dir, report_files, output} — output holds
            the CLI's JSON report summary when available.
        """
        pid = _resolve_project_id(cli, project_id)
        if not pid:
            return _missing_project_response()

        if not cli.has_token():
            resp = init_tool_response()
            resp["status"] = "error"
            resp["error"] = "APIFOX_ACCESS_TOKEN env var not set. Configure it in mcp_servers.json env."
            return format_tool_response(resp)

        env_id = environment_id or cli.default_environment_id
        report_dir = out_dir or tempfile.mkdtemp(prefix="apifox_report_")

        args = [
            "run",
            "-t", scenario_id,
            "--project", pid,
            "-n", str(iteration_count),
            "-r", reporters,
            "--out-dir", report_dir,
        ]
        if env_id:
            args.extend(["-e", env_id])

        logger.info(f"apifox_run_scenario: scenario={scenario_id} project={pid} env={env_id} reporters={reporters}")

        try:
            result = await cli.run(args, timeout=cli.RUN_TIMEOUT)
        except Exception as e:
            resp = init_tool_response()
            resp["status"] = "error"
            resp["error"] = f"Failed to run apifox run: {e}"
            return format_tool_response(resp)

        # Collect generated report files
        report_files: List[str] = []
        try:
            for name in os.listdir(report_dir):
                report_files.append(os.path.join(report_dir, name))
        except OSError:
            pass

        data: Dict[str, Any] = {
            "ok": result.ok,
            "exit_code": result.exit_code,
            "report_dir": report_dir,
            "report_files": report_files,
        }
        if result.parsed is not None:
            data["summary"] = result.parsed
        else:
            tail = result.stdout.strip().splitlines()[-20:]
            data["stdout_tail"] = tail
        if result.stderr.strip():
            data["stderr"] = result.stderr.strip()[:500]

        resp = init_tool_response()
        resp["status"] = "success" if result.ok else "error"
        resp["data"] = data
        if not result.ok:
            resp["error"] = (
                result.error_message()
                or f"apifox run exited with code {result.exit_code}. See report_dir: {report_dir}"
            )
        return format_tool_response(resp)
