# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import json
import httpx
from typing import Any, Dict, Optional, Union
from jsonpath_ng import parse as parse_jsonpath
from mcp.server.fastmcp import FastMCP
from api_session import ApiSessionManager
from utils.response_format import init_tool_response, format_tool_response
from utils.logger import log_tool_call
from utils.logger import logger

# Global session manager reference (set by server)
api_session_manager: Optional[ApiSessionManager] = None


def register_http_tools(mcp: FastMCP, session_manager: ApiSessionManager):
    """Register all HTTP tools with the MCP server"""
    global api_session_manager
    api_session_manager = session_manager

    @mcp.tool()
    @log_tool_call
    async def http_get(
        url: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        extract_path: Optional[str] = None,
        extract_variable: Optional[str] = None,
    ):
        """
        Send an HTTP GET request to the specified URL.

        Args:
            url: The URL or path to send the request to (can include {{variable}} placeholders)
            headers: Additional headers to send with the request
            params: Query parameters to include in the request
            extract_path: JSONPath expression to extract a value from the response
            extract_variable: Name of variable to store the extracted value (requires extract_path)
        """
        if not api_session_manager:
            response = init_tool_response()
            response["status"] = "error"
            response["error"] = "Session manager not initialized"
            return format_tool_response(response)

        try:
            client = api_session_manager.get_client()

            # Resolve variables in URL
            resolved_url = api_session_manager.resolve_variables(url)

            # Resolve variables in params
            resolved_params = None
            if params:
                resolved_params = api_session_manager.resolve_json_variables(params)

            # Merge headers
            request_headers = {}
            if headers:
                request_headers = api_session_manager.resolve_json_variables(headers)

            # Send request
            response = client.get(resolved_url, params=resolved_params, headers=request_headers)

            # Store last response
            api_session_manager.last_response = response

            # Extract variable if requested
            extracted_value = None
            if extract_path and extract_variable:
                try:
                    json_data = response.json()
                    jsonpath_expr = parse_jsonpath(extract_path)
                    matches = jsonpath_expr.find(json_data)
                    if matches:
                        extracted_value = matches[0].value
                        api_session_manager.set_variable(extract_variable, extracted_value)
                        logger.info(f"Extracted variable {extract_variable}: {extracted_value}")
                except Exception as e:
                    logger.warning(f"Failed to extract variable: {e}")

            # Prepare result
            result = {
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "elapsed_ms": int(response.elapsed.total_seconds() * 1000),
            }

            # Try to parse response body as JSON
            try:
                result["body"] = response.json()
            except json.JSONDecodeError:
                result["body"] = response.text

            if extracted_value is not None:
                result["extracted_value"] = extracted_value
                result["extracted_variable"] = extract_variable

            resp = init_tool_response()
            resp["status"] = "success"
            resp["data"] = result
            return format_tool_response(resp)

        except Exception as e:
            resp = init_tool_response()
            resp["status"] = "error"
            resp["error"] = str(e)
            return format_tool_response(resp)

    @mcp.tool()
    @log_tool_call
    async def http_post(
        url: str,
        body: Optional[Union[Dict[str, Any], str]] = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        extract_path: Optional[str] = None,
        extract_variable: Optional[str] = None,
    ):
        """
        Send an HTTP POST request to the specified URL.

        Args:
            url: The URL or path to send the request to (can include {{variable}} placeholders)
            body: Request body (JSON object or string)
            headers: Additional headers to send with the request
            params: Query parameters to include in the request
            extract_path: JSONPath expression to extract a value from the response
            extract_variable: Name of variable to store the extracted value (requires extract_path)
        """
        if not api_session_manager:
            response = init_tool_response()
            response["status"] = "error"
            response["error"] = "Session manager not initialized"
            return format_tool_response(response)

        try:
            client = api_session_manager.get_client()

            # Resolve variables
            resolved_url = api_session_manager.resolve_variables(url)
            resolved_params = params
            if params:
                resolved_params = api_session_manager.resolve_json_variables(params)

            request_headers = {}
            if headers:
                request_headers = api_session_manager.resolve_json_variables(headers)

            # Handle body
            resolved_body = None
            if body:
                if isinstance(body, str):
                    resolved_body_str = api_session_manager.resolve_variables(body)
                    try:
                        resolved_body = json.loads(resolved_body_str)
                    except json.JSONDecodeError:
                        resolved_body = resolved_body_str
                else:
                    resolved_body = api_session_manager.resolve_json_variables(body)

            # Send request
            if isinstance(resolved_body, dict) or isinstance(resolved_body, list):
                response = client.post(resolved_url, json=resolved_body, params=resolved_params, headers=request_headers)
            else:
                response = client.post(resolved_url, content=resolved_body, params=resolved_params, headers=request_headers)

            # Store last response
            api_session_manager.last_response = response

            # Extract variable if requested
            extracted_value = None
            if extract_path and extract_variable:
                try:
                    json_data = response.json()
                    jsonpath_expr = parse_jsonpath(extract_path)
                    matches = jsonpath_expr.find(json_data)
                    if matches:
                        extracted_value = matches[0].value
                        api_session_manager.set_variable(extract_variable, extracted_value)
                        logger.info(f"Extracted variable {extract_variable}: {extracted_value}")
                except Exception as e:
                    logger.warning(f"Failed to extract variable: {e}")

            # Prepare result
            result = {
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "elapsed_ms": int(response.elapsed.total_seconds() * 1000),
            }

            try:
                result["body"] = response.json()
            except json.JSONDecodeError:
                result["body"] = response.text

            if extracted_value is not None:
                result["extracted_value"] = extracted_value
                result["extracted_variable"] = extract_variable

            resp = init_tool_response()
            resp["status"] = "success"
            resp["data"] = result
            return format_tool_response(resp)

        except Exception as e:
            resp = init_tool_response()
            resp["status"] = "error"
            resp["error"] = str(e)
            return format_tool_response(resp)

    @mcp.tool()
    @log_tool_call
    async def http_put(
        url: str,
        body: Optional[Union[Dict[str, Any], str]] = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        extract_path: Optional[str] = None,
        extract_variable: Optional[str] = None,
    ):
        """
        Send an HTTP PUT request to the specified URL.

        Args:
            url: The URL or path to send the request to (can include {{variable}} placeholders)
            body: Request body (JSON object or string)
            headers: Additional headers to send with the request
            params: Query parameters to include in the request
            extract_path: JSONPath expression to extract a value from the response
            extract_variable: Name of variable to store the extracted value (requires extract_path)
        """
        if not api_session_manager:
            response = init_tool_response()
            response["status"] = "error"
            response["error"] = "Session manager not initialized"
            return format_tool_response(response)

        try:
            client = api_session_manager.get_client()

            # Resolve variables
            resolved_url = api_session_manager.resolve_variables(url)
            resolved_params = params
            if params:
                resolved_params = api_session_manager.resolve_json_variables(params)

            request_headers = {}
            if headers:
                request_headers = api_session_manager.resolve_json_variables(headers)

            # Handle body
            resolved_body = None
            if body:
                if isinstance(body, str):
                    resolved_body_str = api_session_manager.resolve_variables(body)
                    try:
                        resolved_body = json.loads(resolved_body_str)
                    except json.JSONDecodeError:
                        resolved_body = resolved_body_str
                else:
                    resolved_body = api_session_manager.resolve_json_variables(body)

            # Send request
            if isinstance(resolved_body, dict) or isinstance(resolved_body, list):
                response = client.put(resolved_url, json=resolved_body, params=resolved_params, headers=request_headers)
            else:
                response = client.put(resolved_url, content=resolved_body, params=resolved_params, headers=request_headers)

            # Store last response
            api_session_manager.last_response = response

            # Extract variable if requested
            extracted_value = None
            if extract_path and extract_variable:
                try:
                    json_data = response.json()
                    jsonpath_expr = parse_jsonpath(extract_path)
                    matches = jsonpath_expr.find(json_data)
                    if matches:
                        extracted_value = matches[0].value
                        api_session_manager.set_variable(extract_variable, extracted_value)
                        logger.info(f"Extracted variable {extract_variable}: {extracted_value}")
                except Exception as e:
                    logger.warning(f"Failed to extract variable: {e}")

            # Prepare result
            result = {
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "elapsed_ms": int(response.elapsed.total_seconds() * 1000),
            }

            try:
                result["body"] = response.json()
            except json.JSONDecodeError:
                result["body"] = response.text

            if extracted_value is not None:
                result["extracted_value"] = extracted_value
                result["extracted_variable"] = extract_variable

            resp = init_tool_response()
            resp["status"] = "success"
            resp["data"] = result
            return format_tool_response(resp)

        except Exception as e:
            resp = init_tool_response()
            resp["status"] = "error"
            resp["error"] = str(e)
            return format_tool_response(resp)

    @mcp.tool()
    @log_tool_call
    async def http_delete(
        url: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ):
        """
        Send an HTTP DELETE request to the specified URL.

        Args:
            url: The URL or path to send the request to (can include {{variable}} placeholders)
            headers: Additional headers to send with the request
            params: Query parameters to include in the request
        """
        if not api_session_manager:
            response = init_tool_response()
            response["status"] = "error"
            response["error"] = "Session manager not initialized"
            return format_tool_response(response)

        try:
            client = api_session_manager.get_client()

            # Resolve variables
            resolved_url = api_session_manager.resolve_variables(url)
            resolved_params = params
            if params:
                resolved_params = api_session_manager.resolve_json_variables(params)

            request_headers = {}
            if headers:
                request_headers = api_session_manager.resolve_json_variables(headers)

            # Send request
            response = client.delete(resolved_url, params=resolved_params, headers=request_headers)

            # Store last response
            api_session_manager.last_response = response

            # Prepare result
            result = {
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "elapsed_ms": int(response.elapsed.total_seconds() * 1000),
            }

            try:
                result["body"] = response.json()
            except json.JSONDecodeError:
                result["body"] = response.text

            resp = init_tool_response()
            resp["status"] = "success"
            resp["data"] = result
            return format_tool_response(resp)

        except Exception as e:
            resp = init_tool_response()
            resp["status"] = "error"
            resp["error"] = str(e)
            return format_tool_response(resp)

    @mcp.tool()
    @log_tool_call
    async def http_patch(
        url: str,
        body: Optional[Union[Dict[str, Any], str]] = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        extract_path: Optional[str] = None,
        extract_variable: Optional[str] = None,
    ):
        """
        Send an HTTP PATCH request to the specified URL.

        Args:
            url: The URL or path to send the request to (can include {{variable}} placeholders)
            body: Request body (JSON object or string)
            headers: Additional headers to send with the request
            params: Query parameters to include in the request
            extract_path: JSONPath expression to extract a value from the response
            extract_variable: Name of variable to store the extracted value (requires extract_path)
        """
        if not api_session_manager:
            response = init_tool_response()
            response["status"] = "error"
            response["error"] = "Session manager not initialized"
            return format_tool_response(response)

        try:
            client = api_session_manager.get_client()

            # Resolve variables
            resolved_url = api_session_manager.resolve_variables(url)
            resolved_params = params
            if params:
                resolved_params = api_session_manager.resolve_json_variables(params)

            request_headers = {}
            if headers:
                request_headers = api_session_manager.resolve_json_variables(headers)

            # Handle body
            resolved_body = None
            if body:
                if isinstance(body, str):
                    resolved_body_str = api_session_manager.resolve_variables(body)
                    try:
                        resolved_body = json.loads(resolved_body_str)
                    except json.JSONDecodeError:
                        resolved_body = resolved_body_str
                else:
                    resolved_body = api_session_manager.resolve_json_variables(body)

            # Send request
            if isinstance(resolved_body, dict) or isinstance(resolved_body, list):
                response = client.patch(resolved_url, json=resolved_body, params=resolved_params, headers=request_headers)
            else:
                response = client.patch(resolved_url, content=resolved_body, params=resolved_params, headers=request_headers)

            # Store last response
            api_session_manager.last_response = response

            # Extract variable if requested
            extracted_value = None
            if extract_path and extract_variable:
                try:
                    json_data = response.json()
                    jsonpath_expr = parse_jsonpath(extract_path)
                    matches = jsonpath_expr.find(json_data)
                    if matches:
                        extracted_value = matches[0].value
                        api_session_manager.set_variable(extract_variable, extracted_value)
                        logger.info(f"Extracted variable {extract_variable}: {extracted_value}")
                except Exception as e:
                    logger.warning(f"Failed to extract variable: {e}")

            # Prepare result
            result = {
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "elapsed_ms": int(response.elapsed.total_seconds() * 1000),
            }

            try:
                result["body"] = response.json()
            except json.JSONDecodeError:
                result["body"] = response.text

            if extracted_value is not None:
                result["extracted_value"] = extracted_value
                result["extracted_variable"] = extract_variable

            resp = init_tool_response()
            resp["status"] = "success"
            resp["data"] = result
            return format_tool_response(resp)

        except Exception as e:
            resp = init_tool_response()
            resp["status"] = "error"
            resp["error"] = str(e)
            return format_tool_response(resp)
