# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import json
import operator
from typing import Any, Optional, Union
from jsonschema import validate, ValidationError
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


def register_assert_tools(mcp: FastMCP, session_manager: ApiSessionManager):
    """Register all assertion tools with the MCP server"""
    global api_session_manager
    api_session_manager = session_manager

    @mcp.tool()
    @log_tool_call
    async def assert_status(
        expected: int,
        operator_: str = "==",
    ):
        """
        Assert that the last response has the expected status code.

        Args:
            expected: The expected status code
            operator_: Comparison operator: ==, !=, <, >, <=, >=, in (default: ==)
        """
        # Business error: no prior request → raise so MCP sets isError: true
        response = _get_last_response_or_raise()

        actual = response.status_code
        ops = {
            "==": operator.eq,
            "!=": operator.ne,
            "<": operator.lt,
            ">": operator.gt,
            "<=": operator.le,
            ">=": operator.ge,
            "in": lambda a, b: a in b if isinstance(b, (list, tuple)) else False,
        }

        if operator_ not in ops:
            # Business error: invalid operator → raise
            raise ValueError(f"Invalid operator: {operator_}. Supported: {list(ops.keys())}")

        result = ops[operator_](actual, expected)

        if result:
            resp = init_tool_response()
            resp["status"] = "success"
            resp["data"] = {
                "result": True,
                "message": f"Status code assertion passed: {actual} {operator_} {expected}",
                "actual": actual,
                "expected": expected,
                "operator": operator_,
            }
            return format_tool_response(resp)
        else:
            # Assertion failure: tool executed, assertion did not pass
            resp = init_tool_response()
            resp["status"] = "error"
            resp["error"] = f"Status code assertion failed: {actual} {operator_} {expected}"
            resp["data"] = {
                "result": False,
                "actual": actual,
                "expected": expected,
                "operator": operator_,
            }
            return format_tool_response(resp)

    @mcp.tool()
    @log_tool_call
    async def assert_json_path(
        jsonpath: str,
        expected_value: Any = None,
        expected_contains: Any = None,
    ):
        """
        Assert value at a JSON path in the last response.

        Args:
            jsonpath: JSONPath expression (e.g., $.data.id, $.items[0].name)
            expected_value: Expected value at the given path (exact match)
            expected_contains: Expected value to be contained in array/string at the path
        """
        # Business error: no prior request → raise
        response = _get_last_response_or_raise()

        try:
            json_data = response.json()
        except json.JSONDecodeError:
            # Business error: not JSON → raise
            raise ValueError("Response is not JSON, cannot perform JSON path assertion")

        try:
            jsonpath_expr = parse_jsonpath(jsonpath)
            matches = jsonpath_expr.find(json_data)
        except Exception as e:
            # Business error: invalid JSONPath → raise
            raise ValueError(f"Invalid JSONPath expression: {jsonpath} - {e}")

        if not matches:
            resp = init_tool_response()
            resp["status"] = "error"
            resp["error"] = f"No match found for JSONPath: {jsonpath}"
            return format_tool_response(resp)

        actual_value = matches[0].value

        if expected_value is not None:
            if actual_value == expected_value:
                resp = init_tool_response()
                resp["status"] = "success"
                resp["data"] = {
                    "result": True,
                    "message": f"JSONPath assertion passed: {jsonpath} = {repr(expected_value)}",
                    "jsonpath": jsonpath,
                    "actual": actual_value,
                    "expected": expected_value,
                }
                return format_tool_response(resp)
            else:
                resp = init_tool_response()
                resp["status"] = "error"
                resp["error"] = f"JSONPath assertion failed: {jsonpath} = {repr(actual_value)}, expected {repr(expected_value)}"
                resp["data"] = {
                    "result": False,
                    "jsonpath": jsonpath,
                    "actual": actual_value,
                    "expected": expected_value,
                }
                return format_tool_response(resp)

        if expected_contains is not None:
            if isinstance(actual_value, (list, tuple, str)):
                if expected_contains in actual_value:
                    resp = init_tool_response()
                    resp["status"] = "success"
                    resp["data"] = {
                        "result": True,
                        "message": f"JSONPath contains assertion passed: {jsonpath} contains {repr(expected_contains)}",
                        "jsonpath": jsonpath,
                        "actual": actual_value,
                        "contains": expected_contains,
                    }
                    return format_tool_response(resp)
                else:
                    resp = init_tool_response()
                    resp["status"] = "error"
                    resp["error"] = f"JSONPath contains assertion failed: {jsonpath} does not contain {repr(expected_contains)}"
                    resp["data"] = {
                        "result": False,
                        "jsonpath": jsonpath,
                        "actual": actual_value,
                        "contains": expected_contains,
                    }
                    return format_tool_response(resp)
            else:
                resp = init_tool_response()
                resp["status"] = "error"
                resp["error"] = f"Value at {jsonpath} is not a container type (list/str) for contains assertion"
                return format_tool_response(resp)

        # If just checking existence → success
        resp = init_tool_response()
        resp["status"] = "success"
        resp["data"] = {
            "result": True,
            "message": f"JSONPath matched: {jsonpath} found {len(matches)} value(s)",
            "jsonpath": jsonpath,
            "matches_count": len(matches),
            "first_value": actual_value,
        }
        return format_tool_response(resp)

    @mcp.tool()
    @log_tool_call
    async def assert_json_schema(
        schema: dict,
    ):
        """
        Assert that the last response matches the given JSON Schema.

        Args:
            schema: JSON Schema to validate against
        """
        # Business error: no prior request → raise
        response = _get_last_response_or_raise()

        try:
            json_data = response.json()
        except json.JSONDecodeError:
            raise ValueError("Response is not JSON, cannot perform JSON schema validation")

        try:
            validate(instance=json_data, schema=schema)
            resp = init_tool_response()
            resp["status"] = "success"
            resp["data"] = {
                "result": True,
                "message": "JSON Schema validation passed",
            }
            return format_tool_response(resp)
        except ValidationError as e:
            resp = init_tool_response()
            resp["status"] = "error"
            resp["error"] = f"JSON Schema validation failed: {e.message}"
            resp["data"] = {
                "result": False,
                "error_path": list(e.path),
                "validator": e.validator,
            }
            return format_tool_response(resp)

    @mcp.tool()
    @log_tool_call
    async def assert_header(
        name: str,
        value: Optional[str] = None,
    ):
        """
        Assert a response header exists and optionally has the expected value.

        Args:
            name: Header name (case-insensitive)
            value: Expected header value (optional, if not provided just checks existence)
        """
        # Business error: no prior request → raise
        response = _get_last_response_or_raise()

        headers = {k.lower(): v for k, v in response.headers.items()}
        name_lower = name.lower()

        if name_lower not in headers:
            resp = init_tool_response()
            resp["status"] = "error"
            resp["error"] = f"Header '{name}' not found in response"
            return format_tool_response(resp)

        if value is None:
            resp = init_tool_response()
            resp["status"] = "success"
            resp["data"] = {
                "result": True,
                "message": f"Header '{name}' exists: {headers[name_lower]}",
                "header_name": name,
                "header_value": headers[name_lower],
            }
            return format_tool_response(resp)

        actual = headers[name_lower]
        if value == actual or (isinstance(value, str) and value in actual):
            resp = init_tool_response()
            resp["status"] = "success"
            resp["data"] = {
                "result": True,
                "message": f"Header assertion passed: {name} = {actual}",
                "header_name": name,
                "expected": value,
                "actual": actual,
            }
            return format_tool_response(resp)
        else:
            resp = init_tool_response()
            resp["status"] = "error"
            resp["error"] = f"Header assertion failed: {name} = {actual}, expected {value}"
            resp["data"] = {
                "result": False,
                "header_name": name,
                "expected": value,
                "actual": actual,
            }
            return format_tool_response(resp)

    @mcp.tool()
    @log_tool_call
    async def assert_response_time(
        max_ms: int,
    ):
        """
        Assert that the last response completed within the given time.

        Args:
            max_ms: Maximum allowed response time in milliseconds
        """
        # Business error: no prior request → raise
        response = _get_last_response_or_raise()

        elapsed_ms = int(response.elapsed.total_seconds() * 1000)

        if elapsed_ms <= max_ms:
            resp = init_tool_response()
            resp["status"] = "success"
            resp["data"] = {
                "result": True,
                "message": f"Response time assertion passed: {elapsed_ms}ms ≤ {max_ms}ms",
                "elapsed_ms": elapsed_ms,
                "max_ms": max_ms,
            }
            return format_tool_response(resp)
        else:
            resp = init_tool_response()
            resp["status"] = "error"
            resp["error"] = f"Response time assertion failed: {elapsed_ms}ms > {max_ms}ms"
            resp["data"] = {
                "result": False,
                "elapsed_ms": elapsed_ms,
                "max_ms": max_ms,
            }
            return format_tool_response(resp)

    @mcp.tool()
    @log_tool_call
    async def assert_body_contains(
        text: str,
        case_sensitive: bool = True,
    ):
        """
        Assert that the response body contains the given text.

        Args:
            text: Text to search for in the response body
            case_sensitive: Whether the search should be case-sensitive (default: True)
        """
        # Business error: no prior request → raise
        response = _get_last_response_or_raise()

        body_text = response.text
        search_text = text

        if not case_sensitive:
            body_text = body_text.lower()
            search_text = text.lower()

        if search_text in body_text:
            resp = init_tool_response()
            resp["status"] = "success"
            resp["data"] = {
                "result": True,
                "message": f"Response body contains '{text}'",
                "found": True,
            }
            return format_tool_response(resp)
        else:
            resp = init_tool_response()
            resp["status"] = "error"
            resp["error"] = f"Response body does not contain '{text}'"
            resp["data"] = {
                "result": False,
                "found": False,
            }
            return format_tool_response(resp)
