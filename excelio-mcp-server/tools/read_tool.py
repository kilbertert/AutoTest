# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Read-layer tools: let the LLM inspect a .xlsx without openpyxl's stylesheet crash.

All reads go through zipfile + xml.etree (see excel_io.py), which sidesteps
the broken `fills` node in the example 测试用例.xlsx.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from excel_io import ExcelError, get_module_map, list_sheets, read_header, read_sheet
from utils.logger import log_tool_call, logger
from utils.response_format import format_tool_response, init_tool_response


def register_read_tools(mcp: FastMCP):

    @mcp.tool()
    @log_tool_call
    async def list_sheets(path: str) -> str:
        """List all sheets in an .xlsx file. Returns [{name, index, rows, cols}].

        Use this first to discover sheet names and sizes before reading.
        Safe against broken stylesheets (reads zip+xml directly).
        """
        resp = init_tool_response()
        try:
            sheets = list_sheets(path)
            resp["status"] = "success"
            resp["data"] = {"sheets": sheets, "path": path}
        except FileNotFoundError as e:
            resp["error"] = f"file not found: {path}"
        except Exception as e:
            resp["error"] = f"failed to list sheets: {e}"
            logger.exception("excelio_list_sheets failed")
        return format_tool_response(resp)

    @mcp.tool()
    @log_tool_call
    async def read_header(path: str, sheet) -> str:
        """Return the first row of a sheet as a list of strings.

        sheet: sheet name (str) or 1-based index (int).
        Typical use: read the 16-column header of the example test-case template.
        """
        resp = init_tool_response()
        try:
            header = read_header(path, sheet)
            resp["status"] = "success"
            resp["data"] = {"header": header, "columns": len(header), "sheet": sheet}
        except FileNotFoundError:
            resp["error"] = f"file not found: {path}"
        except ExcelError as e:
            resp["error"] = str(e)
        except Exception as e:
            resp["error"] = f"failed to read header: {e}"
            logger.exception("excelio_read_header failed")
        return format_tool_response(resp)

    @mcp.tool()
    @log_tool_call
    async def read_sheet(
        path: str,
        sheet,
        start_row: Optional[int] = None,
        end_row: Optional[int] = None,
        max_rows: Optional[int] = None,
    ) -> str:
        """Read rows from a sheet. Returns [{row: <1-based>, values: [...]}, ...].

        sheet: sheet name (str) or 1-based index (int).
        Row 1 is the header. To skip it, pass start_row=2.

        Size control (pick one):
          - max_rows=N: first N rows from row 1
          - start_row=A, end_row=B: 1-based inclusive range
        Default: all rows. For large sheets, ALWAYS pass max_rows to avoid
        flooding the LLM context.
        """
        resp = init_tool_response()
        try:
            row_range: Optional[Dict[str, int]] = None
            if max_rows is not None:
                row_range = {"max_rows": int(max_rows)}
            elif start_row is not None or end_row is not None:
                row_range = {
                    "start": int(start_row or 1),
                    "end": int(end_row or 10**9),
                }
            rows = read_sheet(path, sheet, row_range=row_range)
            resp["status"] = "success"
            resp["data"] = {"rows": rows, "count": len(rows), "sheet": sheet}
        except FileNotFoundError:
            resp["error"] = f"file not found: {path}"
        except ExcelError as e:
            resp["error"] = str(e)
        except Exception as e:
            resp["error"] = f"failed to read sheet: {e}"
            logger.exception("excelio_read_sheet failed")
        return format_tool_response(resp)

    @mcp.tool()
    @log_tool_call
    async def get_module_map(path: str, sheet) -> str:
        """Read a 3-column sheet (模块/功能/子功能) as a flat module map.

        Returns [{row, module, function, subfunction}, ...] with Excel-style
        cascading: empty parent cells inherit the most recent non-empty value
        above (so merged-cell layouts flatten correctly).

        Use this on the example template's sheet 2 to get the qumall 30-module
        exploration checklist.
        """
        resp = init_tool_response()
        try:
            entries = get_module_map(path, sheet)
            modules = sorted({e["module"] for e in entries if e["module"]})
            resp["status"] = "success"
            resp["data"] = {
                "entries": entries,
                "count": len(entries),
                "modules": modules,
                "module_count": len(modules),
            }
        except FileNotFoundError:
            resp["error"] = f"file not found: {path}"
        except ExcelError as e:
            resp["error"] = str(e)
        except Exception as e:
            resp["error"] = f"failed to read module map: {e}"
            logger.exception("excelio_get_module_map failed")
        return format_tool_response(resp)
