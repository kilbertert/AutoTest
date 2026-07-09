#!/usr/bin/env python3
"""Dump a qumall-replay mirror xlsx as a flat JSON queue for the agent.

Stage 1' of qumall-fulltest (Mode B) uses this so the agent does NOT have
to call excelio__read_sheet 18 times trying to "get complete data". The
agent runs this script once via bash, then read_file the resulting JSON
(single read), and has the full case queue in memory.

Handles Excel-style cascading empty cells in the module column (the source
uses merged-cell layout; many rows have empty col D that should inherit
the previous non-empty value).

Output JSON shape:
{
  "mirror_path": "<absolute path>",
  "header": ["用例ID", "项目", ..., "备注"],
  "total": <int>,
  "modules": { "<module>": <count>, ... },
  "cases": [
    {
      "row": <1-based sheet row>,        # for update_cells
      "id": "<用例ID>",
      "module": "<模块>",
      "function": "<功能>",
      "subfunction": "<子功能>",
      "title": "<用例标题>",
      "preconditions": "<前置条件>",
      "test_data": "<测试数据>",
      "steps": "<测试步骤>",
      "expected": "<预期结果>"
    },
    ...
  ]
}
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS = "{" + NS_MAIN + "}"
ET.register_namespace("", NS_MAIN)

COL_LETTERS = "ABCDEFGHIJKLMNOP"


def parse_cell_ref(ref: str) -> tuple[str, int]:
    m = re.match(r"\$?([A-Z]+)\$?(\d+)", ref)
    if not m:
        return ("", 0)
    return (m.group(1), int(m.group(2)))


def get_cell_value(cell_elem, shared_strings: list[str]) -> str:
    t = cell_elem.attrib.get("t", "")
    v = cell_elem.find(NS + "v")
    inline = cell_elem.find(NS + "is")
    if v is not None and v.text is not None:
        if t == "s":
            try:
                return shared_strings[int(v.text)]
            except (ValueError, IndexError):
                return v.text
        if t == "b":
            return "TRUE" if v.text == "1" else "FALSE"
        if t == "str":
            return v.text
        return v.text
    if inline is not None:
        return "".join((tt.text or "") for tt in inline.iter(NS + "t"))
    return ""


def cell_value_for_column(row_elem, col_letter: str, shared_strings: list[str]) -> str:
    for c in row_elem.findall(NS + "c"):
        ref = c.attrib.get("r", "")
        if not ref:
            continue
        cl, _ = parse_cell_ref(ref)
        if cl == col_letter:
            return get_cell_value(c, shared_strings)
    return ""


def load_mirror(mirror_path: Path) -> tuple[list[str], list[list[str]]]:
    """Return (header_row, list_of_value_rows) from the mirror's sheet1."""
    if not mirror_path.exists():
        raise FileNotFoundError(f"mirror not found: {mirror_path}")
    with zipfile.ZipFile(mirror_path) as zf:
        ss_bytes = zf.read("xl/sharedStrings.xml") if "xl/sharedStrings.xml" in zf.namelist() else None
        sheet_bytes = zf.read("xl/worksheets/sheet1.xml")

    ss_root = ET.fromstring(ss_bytes) if ss_bytes else None
    shared_strings: list[str] = []
    if ss_root is not None:
        for si in ss_root.iter(NS + "si"):
            t = si.find(NS + "t")
            if t is not None:
                shared_strings.append(t.text or "")
            else:
                shared_strings.append("".join((tt.text or "") for tt in si.iter(NS + "t")))

    sheet_root = ET.fromstring(sheet_bytes)
    sheet_data = sheet_root.find(NS + "sheetData")
    rows = list(sheet_data.findall(NS + "row")) if sheet_data is not None else []
    if not rows:
        return [], []

    # Header (row 1) — 16 cells
    header = [cell_value_for_column(rows[0], letter, shared_strings) for letter in COL_LETTERS]
    # Data rows
    data_rows: list[list[str]] = []
    for row in rows[1:]:
        vals = [cell_value_for_column(row, letter, shared_strings) for letter in COL_LETTERS]
        data_rows.append(vals)
    return header, data_rows


def main() -> int:
    p = argparse.ArgumentParser(description="Dump a qumall-replay mirror as JSON queue.")
    p.add_argument("--mirror", required=True, help="Path to the mirror xlsx.")
    p.add_argument("--out", required=True, help="Path to write the JSON queue.")
    p.add_argument(
        "--module-col",
        type=int,
        default=3,
        help="0-based column index of the module (default: 3).",
    )
    args = p.parse_args()

    mirror_path = Path(args.mirror).expanduser()
    out_path = Path(args.out).expanduser()
    header, data_rows = load_mirror(mirror_path)

    if not header:
        print("ERROR: mirror has no header row", file=sys.stderr)
        return 1

    if args.module_col >= len(header):
        print(
            f"ERROR: module_col {args.module_col} out of range (header has {len(header)} cols)",
            file=sys.stderr,
        )
        return 1

    cases: list[dict] = []
    last_module = ""
    module_counts: dict[str, int] = {}
    for sheet_row_idx, vals in enumerate(data_rows, start=2):  # row 2 onwards in 1-based
        # Pad if a row is shorter than header
        while len(vals) < len(header):
            vals.append("")
        mod = vals[args.module_col].strip()
        if mod:
            last_module = mod
        else:
            vals[args.module_col] = last_module
            mod = last_module
        module_counts[mod] = module_counts.get(mod, 0) + 1
        cases.append(
            {
                "row": sheet_row_idx,
                "id": vals[0],
                "module": mod,
                "function": vals[4],
                "subfunction": vals[5],
                "title": vals[8],
                "preconditions": vals[9],
                "test_data": vals[10],
                "steps": vals[11],
                "expected": vals[12],
            }
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "mirror_path": str(mirror_path.resolve()),
        "header": header,
        "total": len(cases),
        "modules": module_counts,
        "cases": cases,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Dumped {len(cases)} case(s) from {mirror_path} -> {out_path}")
    print(f"Module distribution: {module_counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
