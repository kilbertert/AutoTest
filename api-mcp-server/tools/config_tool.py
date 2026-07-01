# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import os
from typing import Any, Dict, Optional
from mcp.server.fastmcp import FastMCP
from api_session import ApiSessionManager
from utils.config_manager import ConfigManager
from utils.response_format import init_tool_response, format_tool_response
from utils.logger import log_tool_call

# Global references (set by server)
api_session_manager: Optional[ApiSessionManager] = None
config_manager: Optional[ConfigManager] = None


def register_config_tools(
    mcp: FastMCP,
    session_manager: ApiSessionManager,
    cm: ConfigManager,
):
    """Register all configuration tools with the MCP server"""
    global api_session_manager, config_manager
    api_session_manager = session_manager
    config_manager = cm

    @mcp.tool()
    @log_tool_call
    async def set_base_url(
        base_url: str,
    ):
        """
        Set the base URL for all subsequent API requests.

        Args:
            base_url: The base URL (e.g., https://api.example.com)
        """
        # Business error: session not initialized → raise so MCP sets isError: true
        if not api_session_manager:
            raise ValueError("Session manager not initialized")

        api_session_manager.set_base_url(base_url)

        # Update config if available
        if config_manager:
            current_config = config_manager.get_config()
            current_config["base_url"] = base_url
            config_manager.save_config(current_config)

        resp = init_tool_response()
        resp["status"] = "success"
        resp["data"] = {
            "base_url": base_url,
            "message": f"Base URL set to: {base_url}",
        }
        return format_tool_response(resp)

    @mcp.tool()
    @log_tool_call
    async def set_headers(
        headers: Dict[str, str],
    ):
        """
        Set global headers that will be sent with every API request.

        Args:
            headers: Dictionary of header names and values to add/replace
        """
        # Business error: session not initialized → raise
        if not api_session_manager:
            raise ValueError("Session manager not initialized")

        api_session_manager.update_headers(headers)

        # Update config if available
        if config_manager:
            current_config = config_manager.get_config()
            current_headers = current_config.get("headers", {})
            current_headers.update(headers)
            current_config["headers"] = current_headers
            config_manager.save_config(current_config)

        resp = init_tool_response()
        resp["status"] = "success"
        resp["data"] = {
            "headers": headers,
            "message": f"Updated {len(headers)} global header(s)",
        }
        return format_tool_response(resp)

    @mcp.tool()
    @log_tool_call
    async def set_auth(
        auth_type: str,
        token: Optional[str] = None,
        api_key: Optional[str] = None,
        key_name: Optional[str] = None,
        location: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ):
        """
        Set authentication for all subsequent API requests.

        Args:
            auth_type: Type of authentication: bearer, api_key, basic, or none
            token: Bearer token (for bearer type)
            api_key: API key value (for api_key type)
            key_name: API key header/param name (for api_key type, default: X-API-Key)
            location: Where to send API key: header or query (default: header)
            username: Username (for basic type)
            password: Password (for basic type)
        """
        # Business error: session not initialized → raise
        if not api_session_manager:
            raise ValueError("Session manager not initialized")

        auth_type_lower = auth_type.lower()
        auth_config: Dict[str, Any] = {"type": auth_type_lower}

        if auth_type_lower == "bearer":
            if not token:
                raise ValueError("token is required for bearer authentication")
            auth_config["token"] = token

        elif auth_type_lower == "api_key":
            if not api_key:
                raise ValueError("api_key is required for api_key authentication")
            auth_config["api_key"] = api_key
            auth_config["key_name"] = key_name or "X-API-Key"
            auth_config["location"] = location or "header"

        elif auth_type_lower == "basic":
            if not username or not password:
                raise ValueError("username and password are required for basic authentication")
            auth_config["username"] = username
            auth_config["password"] = password

        elif auth_type_lower == "none":
            auth_config["type"] = "none"

        else:
            raise ValueError(f"Unsupported auth type: {auth_type}. Supported: bearer, api_key, basic, none")

        api_session_manager.set_auth(auth_config)

        # Update config if available
        if config_manager:
            current_config = config_manager.get_config()
            current_config["auth"] = auth_config
            config_manager.save_config(current_config)

        resp = init_tool_response()
        resp["status"] = "success"
        resp["data"] = {
            "auth_type": auth_type,
            "message": f"Authentication configured: {auth_type}",
        }
        return format_tool_response(resp)

    @mcp.tool()
    @log_tool_call
    async def get_config():
        """
        Get the current API testing configuration.
        """
        # Business error: neither config_manager nor api_session_manager → raise
        if not config_manager and not api_session_manager:
            raise ValueError("Neither config manager nor session manager is initialized")

        if config_manager:
            config = config_manager.get_config()
            resp = init_tool_response()
            resp["status"] = "success"
            resp["data"] = config.copy() if config else {}
            if api_session_manager:
                resp["data"]["variables"] = api_session_manager.get_variables()
            return format_tool_response(resp)
        else:
            resp = init_tool_response()
            resp["status"] = "success"
            resp["data"] = {
                "base_url": api_session_manager.base_url,
                "headers": api_session_manager.headers,
                "auth": api_session_manager.auth,
                "timeout": api_session_manager.timeout,
                "variables": api_session_manager.get_variables(),
            }
            return format_tool_response(resp)

    @mcp.tool()
    @log_tool_call
    async def load_config(
        config_path: str,
    ):
        """
        Load configuration from a specific file.

        Args:
            config_path: Path to the configuration JSON file
        """
        # Business error: config_manager not available → raise
        if not config_manager:
            raise ValueError("Config manager not initialized")

        # Stop watching old file
        config_manager.stop_watching()

        # Update config path and reload
        config_manager.config_path = os.path.abspath(config_path)
        success = config_manager.reload_config()

        if not success:
            # Restore watching on old path on failure
            try:
                config_manager.reload_config()
            except Exception:
                pass
            raise ValueError(f"Failed to load configuration from {config_path}")

        # Apply loaded config to session
        config = config_manager.get_config()
        if api_session_manager:
            if "base_url" in config:
                api_session_manager.set_base_url(config["base_url"])
            if "headers" in config:
                api_session_manager.update_headers(config["headers"])
            if "auth" in config:
                api_session_manager.set_auth(config["auth"])
            if "timeout" in config:
                api_session_manager.set_timeout(config["timeout"])

        # Start watching for changes
        config_manager.start_watching()

        resp = init_tool_response()
        resp["status"] = "success"
        resp["data"] = {
            "config_path": config_path,
            "message": f"Configuration loaded successfully from {config_path}",
        }
        return format_tool_response(resp)

    @mcp.tool()
    @log_tool_call
    async def set_timeout(
        timeout: int,
    ):
        """
        Set the request timeout in seconds.

        Args:
            timeout: Timeout in seconds for HTTP requests
        """
        # Business error: session not initialized → raise
        if not api_session_manager:
            raise ValueError("Session manager not initialized")

        api_session_manager.set_timeout(timeout)

        # Update config if available
        if config_manager:
            current_config = config_manager.get_config()
            current_config["timeout"] = timeout
            config_manager.save_config(current_config)

        resp = init_tool_response()
        resp["status"] = "success"
        resp["data"] = {
            "timeout": timeout,
            "message": f"Request timeout set to {timeout} seconds",
        }
        return format_tool_response(resp)
