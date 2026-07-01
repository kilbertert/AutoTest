# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Documentation-layer tools: let the LLM see what endpoints exist on Apifox.

Wraps `apifox endpoint list` and `apifox endpoint get` (apifox CLI v2.x).
The CLI returns a uniform JSON envelope {success, resource, operation, data};
we surface a distilled view to keep the LLM context small.
"""

from __future__ import annotations

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


def _endpoint_list_from_data(data: Any) -> List[Dict[str, Any]]:
    """Defensively extract a list of endpoints from the CLI `data` payload.

    The CLI may return data as {list: [...]} or just [...] depending on
    version; handle both. Each endpoint item is distilled to the fields the
    LLM needs to pick one: id, method, path, name, status, tags.
    """
    items: Any = None
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for key in ("list", "items", "endpoints", "data"):
            if isinstance(data.get(key), list):
                items = data[key]
                break
        if items is None and isinstance(data.get("total"), int):
            # Paginated envelope without a recognized list key — give up gracefully.
            items = []
    if not isinstance(items, list):
        return []

    out: List[Dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        out.append({
            "id": it.get("id"),
            "method": (it.get("method") or it.get("httpMethod") or "").upper(),
            "path": it.get("path") or it.get("url"),
            "name": it.get("name") or it.get("summary"),
            "status": it.get("status"),
            "tags": [t.get("name", t) if isinstance(t, dict) else t for t in (it.get("tags") or [])],
            "folder_id": it.get("folderId") or it.get("folder_id"),
        })
    return out


def register_endpoint_tools(mcp: FastMCP, cli: ApifoxCliRunner):

    @mcp.tool()
    @log_tool_call
    async def apifox_list_endpoints(
        project_id: Optional[str] = None,
        method: Optional[str] = None,
        tag: Optional[str] = None,
        path_contains: Optional[str] = None,
        name_contains: Optional[str] = None,
    ):
        """List API endpoints in an Apifox project.

        Use this first to discover what endpoints exist. Returns a scannable
        list of {id, method, path, name, status, tags}. Pick one, then call
        apifox_get_endpoint_detail with its `id` to get the full request/response
        schema before testing it with api-mcp's http_* tools.

        Args:
            project_id: Apifox project ID. If omitted, uses APIFOX_PROJECT_ID env var.
            method: Filter by HTTP method (GET/POST/PUT/PATCH/DELETE/HEAD/OPTIONS).
            tag: Filter by tag name.
            path_contains: Filter by path substring.
            name_contains: Filter by endpoint name substring.

        Returns:
            A list of endpoint summaries. Large projects use server-side
            pagination (page-size 500) — if truncated, narrow with filters.
        """
        pid = _resolve_project_id(cli, project_id)
        if not pid:
            return _missing_project_response()

        args = ["endpoint", "list", "--project", pid, "--page-size", "500"]
        if method:
            args.extend(["--method", method.upper()])
        if tag:
            args.extend(["--tag", tag])
        if path_contains:
            args.extend(["--path-contains", path_contains])
        if name_contains:
            args.extend(["--name-contains", name_contains])

        try:
            result = await cli.run(args)
        except Exception as e:
            resp = init_tool_response()
            resp["status"] = "error"
            resp["error"] = f"Failed to run apifox endpoint list: {e}"
            return format_tool_response(resp)

        if not result.ok:
            resp = init_tool_response()
            resp["status"] = "error"
            resp["error"] = result.error_message() or f"apifox endpoint list failed (exit {result.exit_code})"
            return format_tool_response(resp)

        data = result.parsed.get("data") if isinstance(result.parsed, dict) else None
        endpoints = _endpoint_list_from_data(data)
        logger.info(f"apifox_list_endpoints: {len(endpoints)} endpoints in project {pid}")

        resp = init_tool_response()
        resp["status"] = "success"
        resp["data"] = {
            "project_id": pid,
            "count": len(endpoints),
            "endpoints": endpoints,
        }
        return format_tool_response(resp)

    @mcp.tool()
    @log_tool_call
    async def apifox_get_endpoint_detail(
        endpoint_id: str,
        project_id: Optional[str] = None,
    ):
        """Get the full schema of one endpoint (parameters, request body, responses).

        After apifox_list_endpoints gives you an endpoint's `id`, call this to
        read its request/response contract. Then use api-mcp's set_base_url +
        http_* + assert_* tools to actually send the request and verify.

        Args:
            endpoint_id: The endpoint's id (from apifox_list_endpoints).
            project_id: Apifox project ID. If omitted, uses APIFOX_PROJECT_ID env var.

        Returns:
            The endpoint's full definition (method, path, parameters, request
            body, responses, examples) as stored in Apifox.
        """
        pid = _resolve_project_id(cli, project_id)
        if not pid:
            return _missing_project_response()

        try:
            result = await cli.run(["endpoint", "get", endpoint_id, "--project", pid])
        except Exception as e:
            resp = init_tool_response()
            resp["status"] = "error"
            resp["error"] = f"Failed to run apifox endpoint get: {e}"
            return format_tool_response(resp)

        if not result.ok:
            resp = init_tool_response()
            resp["status"] = "error"
            resp["error"] = result.error_message() or f"apifox endpoint get failed (exit {result.exit_code})"
            return format_tool_response(resp)

        data = result.parsed.get("data") if isinstance(result.parsed, dict) else result.parsed

        resp = init_tool_response()
        resp["status"] = "success"
        resp["data"] = data if data is not None else {}
        return format_tool_response(resp)
