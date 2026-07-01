# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

# -*- coding: utf-8 -*-
import json
import os
import logging
import sys
import argparse
from mcp.server.fastmcp import FastMCP
from api_session import ApiSessionManager
from tools.http_tool import register_http_tools
from tools.assert_tool import register_assert_tools
from tools.extract_tool import register_extract_tools
from tools.config_tool import register_config_tools
from tools.gen_code_tool import register_gen_code_tools
from tools.verify_tools import register_verify_tools
from utils.logger import get_mcp_logger
from utils.config_manager import ConfigManager
from llm.chat import LLMClient

logger = get_mcp_logger()

settings = {
    "log_level": "DEBUG"
}

# 创建 MCP server
mcp = FastMCP("api-mcp-server", log_level="INFO")

# 配置MCP底层服务器日志过滤
def filter_mcp_lowlevel_logs():
    """过滤掉MCP底层服务器的INFO级别日志"""
    mcp_lowlevel_logger = logging.getLogger('mcp.server.lowlevel.server')
    mcp_lowlevel_logger.setLevel(logging.WARNING)

filter_mcp_lowlevel_logs()
api_session_manager = None  # 全局可访问
config_manager = None      # 全局配置管理器
llm_client = None          # LLM 客户端
gen_code_manager = None    # 代码生成管理器


class ApiCodeGenManager:
    """Manager for API code generation state"""
    def __init__(self):
        self.clear_gen_code_cache()
        self._tool_execution_lock = {}
        self._current_execution = None

    def clear_gen_code_cache(self):
        """Clear the generation cache"""
        self.gen_code_id = None
        self.gen_code_cache = []
        self.proposed_changes = None
        self.header_code = None
        self.steps_dir = None
        self.step_file_target = None
        self.new_steps_count = 0

    def start_tool_execution(self, tool_name: str) -> bool:
        """Check if tool can execute, acquire lock"""
        if self._current_execution:
            return False
        self._current_execution = tool_name
        return True

    def finish_tool_execution(self, tool_name: str):
        """Release lock after execution"""
        if self._current_execution == tool_name:
            self._current_execution = None


def on_config_change(new_config):
    """Callback when configuration changes"""
    global api_session_manager
    if api_session_manager:
        logger.info("Configuration changed, updating API session")
        if "base_url" in new_config:
            api_session_manager.set_base_url(new_config["base_url"])
        if "headers" in new_config:
            api_session_manager.update_headers(new_config["headers"])
        if "auth" in new_config:
            api_session_manager.set_auth(new_config["auth"])
        if "timeout" in new_config:
            api_session_manager.set_timeout(new_config["timeout"])


def main():
    global api_session_manager, config_manager, llm_client, gen_code_manager
    parser = argparse.ArgumentParser()
    parser.add_argument("--transport", choices=["stdio", "sse"], default="sse")
    parser.add_argument("--config", type=str, help="Path to config file")
    args = parser.parse_args()

    # Initialize config manager with file watching
    config_manager = ConfigManager(args.config, on_config_change=on_config_change)
    api_config = config_manager.get_config()

    # Initialize API session manager
    api_session_manager = ApiSessionManager(api_config)

    # Initialize code generation manager
    gen_code_manager = ApiCodeGenManager()

    # Initialize LLM client (will be None if not configured)
    try:
        llm_client = LLMClient()
        if not llm_client.azure_gpt_available() and not llm_client.local_copilot_available():
            logger.warning("No LLM provider configured, AI verification will be disabled")
            llm_client = None
    except Exception as e:
        logger.warning(f"Failed to initialize LLM client: {e}, AI verification will be disabled")
        llm_client = None

    # Start watching for config file changes
    config_manager.start_watching()
    logger.info("Config file hot-reload enabled")

    # register tools
    register_http_tools(mcp, api_session_manager)
    register_assert_tools(mcp, api_session_manager)
    register_extract_tools(mcp, api_session_manager)
    register_config_tools(mcp, api_session_manager, config_manager)
    register_gen_code_tools(mcp, gen_code_manager)
    if llm_client:
        register_verify_tools(mcp, api_session_manager, llm_client)
        logger.info("AI verification enabled")
    else:
        logger.info("AI verification disabled (no LLM configured)")

    # start MCP server
    try:
        mcp.run(transport=args.transport)
    finally:
        # Cleanup on shutdown
        if config_manager:
            config_manager.stop_watching()
        if api_session_manager:
            api_session_manager.close()


if __name__ == "__main__":
    main()
