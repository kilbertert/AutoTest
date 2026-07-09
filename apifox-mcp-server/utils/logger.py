# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import logging
import json
import os
import uuid
from datetime import datetime
from functools import wraps


def get_mcp_logger(name=None):
    """
    Get a logger configured for MCP server components

    Args:
        name: Logger name, defaults to caller's module name

    Returns:
        logging.Logger: Configured logger instance
    """
    if name is None:
        # Get caller's module name
        import inspect
        frame = inspect.currentframe().f_back
        name = frame.f_globals.get('__name__', 'mcp_component')

    component_logger = logging.getLogger(name)

    # Avoid duplicate handlers if logger already configured
    if component_logger.handlers:
        return component_logger

    # Set log level
    mcp_log_level = os.environ.get('MCP_LOG_LEVEL', 'INFO').upper()
    log_level = getattr(logging, mcp_log_level, logging.INFO)
    component_logger.setLevel(log_level)

    # Check if MCP_LOG_FILE is set (pipeline environment)
    mcp_log_dir = os.environ.get('MCP_LOG_FILE')
    if mcp_log_dir:
        # Pipeline environment: only log to file, not console
        os.makedirs(mcp_log_dir, exist_ok=True)
        mcp_log_file = os.path.join(mcp_log_dir, 'mcp_server.log')

        file_handler = logging.FileHandler(mcp_log_file, encoding='utf-8')
        file_handler.setLevel(log_level)
        file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(file_formatter)
        component_logger.addHandler(file_handler)
        component_logger.propagate = False
    else:
        # Local development: log to file + console
        if name == 'mcp_server' and not getattr(logging.getLogger(), '_basicConfig_called', False):
            log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
            os.makedirs(log_dir, exist_ok=True)
            log_file = os.path.join(log_dir, f'mcp_server_{datetime.now().strftime("%Y%m%d")}.log')

            logging.basicConfig(
                level=logging.INFO,
                format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                handlers=[
                    logging.FileHandler(log_file, encoding='utf-8'),
                    logging.StreamHandler()
                ]
            )
            logging.getLogger()._basicConfig_called = True

    return component_logger


logger = get_mcp_logger('mcp_server')


def log_tool_call(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        tool_name = func.__name__
        call_id = str(uuid.uuid4())

        logger.info(f"Tool Call - Start - ID: {call_id} - Tool: {tool_name} - Parameters: {json.dumps(kwargs, ensure_ascii=False)}")
        try:
            result = await func(*args, **kwargs)

            if isinstance(result, str):
                try:
                    result = json.loads(result)
                except (json.JSONDecodeError, ValueError):
                    pass

            is_error_result = False
            if isinstance(result, dict) and result.get('status') == 'error':
                is_error_result = True
                logger.error(f"Tool Call - Error Result - ID: {call_id} - Tool: {tool_name} - Parameters: {json.dumps(kwargs, ensure_ascii=False)}")
            else:
                logger.info(f"Tool Call - Success - ID: {call_id} - Tool: {tool_name} - Parameters: {json.dumps(kwargs, ensure_ascii=False)}")

            result_str = str(result)
            result_size = len(result_str)

            if result_size > 1000 and (is_error_result or isinstance(result, (list, dict, str))):
                logger.info(f"Result: (large output, showing summary) Type: {type(result)}, Size: {result_size} chars")
            else:
                try:
                    logger.info(f"Result: {json.dumps(result, ensure_ascii=False)}")
                except TypeError:
                    logger.error(f"Result: [Unable to serialize: {type(result)}]")

            return result

        except Exception as e:
            import traceback
            traceback.print_exc()
            logger.error(f"Tool Call - Error - ID: {call_id} - Tool: {tool_name} - Parameters: {json.dumps(kwargs, ensure_ascii=False)} - Error: {str(e)}")
            raise

    return wrapper
