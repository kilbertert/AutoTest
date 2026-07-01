# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import json
import os
import logging
import uuid
from pathlib import Path
from utils.logger import log_tool_call
from utils.gen_code import HEADER_AUTO_GEN, STEPS_DIR_DEFAULT, TARGET_STEP_FILE_DEFAULT
from utils.gen_code import gen_code_preview, ensure_step_path_exists, gen_step_file_from_feature_path, parse_steps_dir_from_step_path
from utils.response_format import format_tool_response, init_tool_response
from utils.logger import get_mcp_logger

logger = get_mcp_logger()


def register_gen_code_tools(mcp, api_code_manager):
    """Register generate code tools to MCP server."""

    @mcp.tool()
    @log_tool_call
    async def before_gen_code(feature_file: str = '', step_file: str = ''):
        """
        Clear cache and initialize code generation session before executing test case steps.

        This function should only be called before the first step of a test case execution.
        It clears any existing code generation cache and sets up a new generation session
        with a unique ID.

        Args:
            feature_file: Full absolute path to the .feature file containing BDD scenarios.
            step_file: Full absolute path to the Python step definition file (.py).

        Returns:
            JSON response containing:
            - status: "success" or "error"
            - data: Dictionary with gen_code_id, steps_dir, and step_file_target
            - error: Error message if operation failed
        """
        api_code_manager.clear_gen_code_cache()
        api_code_manager.gen_code_id = str(uuid.uuid4())
        logger.info(f"[GEN CODE START]:{api_code_manager.gen_code_id}")

        if step_file and step_file.endswith('.py'):
            api_code_manager.steps_dir = parse_steps_dir_from_step_path(step_file)
            api_code_manager.step_file_target = step_file
        elif feature_file:
            api_code_manager.steps_dir, api_code_manager.step_file_target = gen_step_file_from_feature_path(feature_file)
        else:
            api_code_manager.steps_dir = STEPS_DIR_DEFAULT
            api_code_manager.step_file_target = TARGET_STEP_FILE_DEFAULT

        resp = init_tool_response()
        resp["status"] = "success"
        resp["data"] = {
            "gen_code_id": api_code_manager.gen_code_id,
            "steps_dir": api_code_manager.steps_dir,
            "step_file_target": api_code_manager.step_file_target,
        }
        return format_tool_response(resp)

    @mcp.tool()
    @log_tool_call
    async def preview_code_changes():
        """Preview generated test code changes and confirm before applying"""
        if not api_code_manager.gen_code_id or not api_code_manager.gen_code_cache:
            # No pending changes — not an error, just return success with empty message
            resp = init_tool_response()
            resp["status"] = "success"
            resp["data"] = {"message": "No pending code changes to preview"}
            return format_tool_response(resp)

        result = gen_code_preview(api_code_manager)
        resp = init_tool_response()
        resp["status"] = "success"
        resp["data"] = {"diff_preview": result.get('diff_preview')}
        return format_tool_response(resp)

    @mcp.tool()
    @log_tool_call
    async def confirm_code_changes():
        """Confirm the previewed code changes"""
        if not hasattr(api_code_manager, 'proposed_changes') or not api_code_manager.proposed_changes:
            # Business error: nothing to confirm → raise so MCP sets isError: true
            raise ValueError("No pending code changes to confirm. Call preview_code_changes first.")

        if not ensure_step_path_exists(api_code_manager.step_file_target):
            raise ValueError(f"Failed to create directory structure for {api_code_manager.step_file_target}")

        try:
            target_path = Path(api_code_manager.step_file_target)
            existing_content = ""
            if target_path.exists():
                existing_content = target_path.read_text(encoding='utf-8')

            with open(api_code_manager.step_file_target, 'a', encoding='utf-8') as f:
                if hasattr(api_code_manager, 'header_code') and api_code_manager.header_code and not existing_content:
                    f.write(api_code_manager.header_code + "\n")
                for item in api_code_manager.proposed_changes:
                    f.write(item + "\n")

            result = f"Applied {len(api_code_manager.proposed_changes)} new steps to {api_code_manager.step_file_target}"
            api_code_manager.new_steps_count = len(api_code_manager.proposed_changes)
        except Exception as e:
            # Business error: file write failed → raise so MCP sets isError: true
            raise ValueError(f"Error applying changes to {api_code_manager.step_file_target}: {str(e)}")

        # Clear the proposed changes
        api_code_manager.clear_gen_code_cache()

        resp = init_tool_response()
        resp["status"] = "success"
        resp["data"] = {"message": result, "new_steps_count": api_code_manager.new_steps_count}
        return format_tool_response(resp)
