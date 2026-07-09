# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import json
from typing import Optional
from mcp.server.fastmcp import FastMCP
from api_session import ApiSessionManager
from llm.chat import LLMClient
from llm.prompt import api_analysis_prompt, ApiTaskResponse
from utils.response_format import init_tool_response, format_tool_response
from utils.logger import log_tool_call, logger

# Global references (set by server)
api_session_manager: Optional[ApiSessionManager] = None
llm_client: Optional[LLMClient] = None


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


def register_verify_tools(
    mcp: FastMCP,
    session_manager: ApiSessionManager,
    llm: LLMClient,
):
    """Register all verification tools with the MCP server"""
    global api_session_manager, llm_client
    api_session_manager = session_manager
    llm_client = llm

    @mcp.tool()
    @log_tool_call
    async def verify_response_against_requirement(
        requirement: str,
    ):
        """
        Use AI to verify that the last API response satisfies a requirement.

        Args:
            requirement: Natural language description of what to verify
        """
        # Business error: no prior request → raise
        response = _get_last_response_or_raise()

        # Business error: LLM not configured → raise
        if not llm_client:
            raise ValueError("LLM client not configured. AI verification is not available.")

        try:
            json_data = response.json()
        except json.JSONDecodeError:
            json_data = response.text

        response_text = json.dumps(json_data, indent=2, ensure_ascii=False) if isinstance(json_data, (dict, list)) else str(json_data)

        prompt = api_analysis_prompt(f"""
Original Requirement: {requirement}

Last API Response:
{response_text}
""")

        try:
            model = llm_client.get_azure_model()
            from langchain_core.messages import HumanMessage
            structured_llm = model.with_structured_output(ApiTaskResponse)
            res = structured_llm.invoke([HumanMessage(content=prompt)])

            if isinstance(res, ApiTaskResponse):
                result = res.result
                reason = res.reason

                if result:
                    resp = init_tool_response()
                    resp["status"] = "success"
                    resp["data"] = {
                        "result": True,
                        "reason": reason,
                        "message": f"Verification passed: {reason}",
                    }
                    return format_tool_response(resp)
                else:
                    resp = init_tool_response()
                    resp["status"] = "error"
                    resp["error"] = f"Verification failed: {reason}"
                    resp["data"] = {
                        "result": False,
                        "reason": reason,
                    }
                    return format_tool_response(resp)
            else:
                raise ValueError(f"Unexpected response format from LLM: {type(res)}")

        except Exception as e:
            logger.error(f"LLM verification failed: {e}")
            raise ValueError(f"LLM verification failed: {str(e)}")

    @mcp.tool()
    @log_tool_call
    async def verify_json_schema_openapi(
        openapi_schema_path: str,
        operation_id: Optional[str] = None,
        path: Optional[str] = None,
        method: Optional[str] = None,
    ):
        """
        Verify that the last response matches an OpenAPI schema.

        Args:
            openapi_schema_path: Path to the OpenAPI schema file (JSON or YAML)
            operation_id: Operation ID in the OpenAPI spec
            path: API path (required if not using operation_id)
            method: HTTP method (required if not using operation_id)
        """
        # Business error: not implemented → raise
        raise ValueError("OpenAPI schema verification is not implemented yet.")
