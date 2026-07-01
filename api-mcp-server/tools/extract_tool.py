# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import json
from typing import Any, Optional
from jsonpath_ng import parse as parse_jsonpath
from mcp.server.fastmcp import FastMCP
from api_session import ApiSessionManager
from utils.response_format import init_tool_response, format_tool_response
from utils.logger import log_tool_call

# Global session manager reference (set by server)
api_session_manager: Optional[ApiSessionManager] = None


def _get_last_response_or_raise():
    """Helper to get last response or raise if not available.

    Raises:
        ValueError: When session manager is not initialized or no prior HTTP request exists.
    """
    if not api_session_manager:
        raise ValueError("Session manager not initialized")
    if not api_session_manager.last_response:
        raise ValueError("No previous response available. Please send an HTTP request first.")
    return api_session_manager.last_response


def register_extract_tools(mcp: FastMCP, session_manager: ApiSessionManager):
    """Register all extraction tools with the MCP server"""
    global api_session_manager
    api_session_manager = session_manager

    @mcp.tool()
    @log_tool_call
    async def extract_variable(
        variable_name: str,
        jsonpath: str,
    ):
        """
        Extract a value from the last JSON response using JSONPath and store it as a variable.

        Args:
            variable_name: Name of the variable to store the extracted value
            jsonpath: JSONPath expression to extract the value
        """
        # Business error: no prior request → raise so MCP sets isError: true
        response = _get_last_response_or_raise()

        try:
            json_data = response.json()
        except json.JSONDecodeError:
            raise ValueError("Response is not JSON, cannot extract variable")

        try:
            jsonpath_expr = parse_jsonpath(jsonpath)
            matches = jsonpath_expr.find(json_data)
        except Exception as e:
            raise ValueError(f"Invalid JSONPath expression: {jsonpath} - {e}")

        if not matches:
            raise ValueError(f"No match found for JSONPath: {jsonpath}")

        extracted_value = matches[0].value
        api_session_manager.set_variable(variable_name, extracted_value)

        resp = init_tool_response()
        resp["status"] = "success"
        resp["data"] = {
            "variable_name": variable_name,
            "jsonpath": jsonpath,
            "extracted_value": extracted_value,
            "message": f"Variable '{variable_name}' extracted successfully",
        }
        return format_tool_response(resp)

    @mcp.tool()
    @log_tool_call
    async def set_variable(
        variable_name: str,
        value: Any,
    ):
        """
        Manually set a variable value for use in subsequent requests.

        Args:
            variable_name: Name of the variable to set
            value: The value to store
        """
        # Business error: session not initialized → raise
        if not api_session_manager:
            raise ValueError("Session manager not initialized")

        api_session_manager.set_variable(variable_name, value)

        resp = init_tool_response()
        resp["status"] = "success"
        resp["data"] = {
            "variable_name": variable_name,
            "value": value,
            "message": f"Variable '{variable_name}' set successfully",
        }
        return format_tool_response(resp)

    @mcp.tool()
    @log_tool_call
    async def get_variables():
        """
        Get all currently stored variables and their values.
        """
        # Business error: session not initialized → raise
        if not api_session_manager:
            raise ValueError("Session manager not initialized")

        variables = api_session_manager.get_variables()

        resp = init_tool_response()
        resp["status"] = "success"
        resp["data"] = {
            "variables": variables,
            "count": len(variables),
        }
        return format_tool_response(resp)

    @mcp.tool()
    @log_tool_call
    async def clear_variables():
        """
        Clear all stored variables.
        """
        # Business error: session not initialized → raise
        if not api_session_manager:
            raise ValueError("Session manager not initialized")

        api_session_manager.clear_variables()

        resp = init_tool_response()
        resp["status"] = "success"
        resp["data"] = {
            "message": "All variables cleared successfully",
        }
        return format_tool_response(resp)
