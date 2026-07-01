# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Write-layer tools: create blueprints, append design-time rows, update result cells.

Column whitelist (enforced in excel_io.update_cells):
  - col 14 (执行结果), col 15 (备注), col 17 (截图路径) — writable at execute time
  - col 0-13, 16 — design-time only, NEVER writable via update_cells
    (design-time cols are written once via append_rows, then frozen)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from excel_io import ExcelError, append_rows, create_blueprint, update_cells
from utils.logger import log_tool_call, logger
from utils.response_format import format_tool_response, init_tool_response


def register_write_tools(mcp: FastMCP):

    @mcp.tool()
    @log_tool_call
    async def create_blueprint(
        path: str,
        template_header: List[str],
        extra_header: Optional[List[str]] = None,
    ) -> str:
        """Create a new empty .xlsx blueprint with the given header row.

        The blueprint has one sheet "测试用例蓝图" with header = template_header + extra_header.
        Fails if the file already exists (pick a fresh run_id / path).

        Typical call:
          template_header = ["用例ID","项目","端口","模块","功能","子功能","优先级",
                             "测试方法","用例标题","前置条件","测试数据","测试步骤",
                             "预期结果","编写人","执行结果","备注"]   # 16 cols from example
          extra_header = ["UI_selector","截图路径"]                 # 2 extension cols
        """
        resp = init_tool_response()
        try:
            result = create_blueprint(path, template_header, extra_header)
            resp["status"] = "success"
            resp["data"] = result
        except ExcelError as e:
            resp["error"] = str(e)
        except Exception as e:
            resp["error"] = f"failed to create blueprint: {e}"
            logger.exception("excelio_create_blueprint failed")
        return format_tool_response(resp)

    @mcp.tool()
    @log_tool_call
    async def append_rows(
        path: str,
        sheet,
        rows: List[List[Any]],
    ) -> str:
        """Append rows to a sheet. Used at DESIGN time to add test cases to the blueprint.

        sheet: sheet name (str) or 1-based index (int).
        rows: list of rows; each row is a list of cell values (0-indexed cols).
              Length of each row should match the header width (18 for the blueprint).

        Returns {appended: N, start_row: <first new row number>}.

        NOTE: this is the ONLY way to write design-time columns (0-13, 16).
        After design, those columns are frozen — use excelio_update_cells for
        execute-time writes (col 14, 15, 17 only).
        """
        resp = init_tool_response()
        try:
            if not rows:
                resp["error"] = "rows is empty"
                return format_tool_response(resp)
            result = append_rows(path, sheet, rows)
            resp["status"] = "success"
            resp["data"] = result
        except FileNotFoundError:
            resp["error"] = f"file not found: {path}"
        except ExcelError as e:
            resp["error"] = str(e)
        except Exception as e:
            resp["error"] = f"failed to append rows: {e}"
            logger.exception("excelio_append_rows failed")
        return format_tool_response(resp)

    @mcp.tool()
    @log_tool_call
    async def update_cells(
        path: str,
        sheet,
        updates: List[Dict[str, Any]],
    ) -> str:
        """Update cells in a sheet. Used at EXECUTE time to write back results.

        sheet: sheet name (str) or 1-based index (int).
        updates: list of {row: <1-based>, col: <0-based>, value: <str>}.

        WRITABLE COLUMNS ONLY (enforced):
          col 14 → 执行结果  ("通过" / "失败" / "跳过")
          col 15 → 备注      (failure reason, ≤ 200 chars)
          col 17 → 截图路径  (absolute path to failure screenshot)

        Writing to any other column (0-13, 16) raises an error and the whole
        batch is refused. This protects design-time content from being
        mutated at execute time.
        """
        resp = init_tool_response()
        try:
            if not updates:
                resp["error"] = "updates is empty"
                return format_tool_response(resp)
            result = update_cells(path, sheet, updates)
            resp["status"] = "success"
            resp["data"] = result
        except FileNotFoundError:
            resp["error"] = f"file not found: {path}"
        except ExcelError as e:
            resp["error"] = str(e)
        except Exception as e:
            resp["error"] = f"failed to update cells: {e}"
            logger.exception("excelio_update_cells failed")
        return format_tool_response(resp)
