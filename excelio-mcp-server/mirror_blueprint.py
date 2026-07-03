#!/usr/bin/env python3
"""Mirror 测试用例.xlsx into blueprints/qumall-replay.xlsx via pure zip+xml.

Avoids openpyxl entirely (the source has a broken stylesheet that crashes
openpyxl's Fill validator). Strategy:

1. Copy the entire source xlsx as-is to dst
2. Read xl/worksheets/sheet1.xml and xl/sharedStrings.xml
3. Filter <row> by 模块 (col D / index 3) and apply max-per-module cap
4. Renumber remaining <row r="N"> and <c r="A1"> sequentially
5. Re-pack zip with new sheet1.xml (other files untouched)
6. excelio__update_cells then writes col 14/15 on the mirror.

The original 测试用例.xlsx has 16 columns (col A..P) on sheet1.
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS = "{" + NS_MAIN + "}"
ET.register_namespace("", NS_MAIN)

COL_MODULE = 3
COL_LETTERS = "ABCDEFGHIJKLMNOP"


def parse_cell_ref(ref):
    m = re.match(r"\$?([A-Z]+)\$?(\d+)", ref)
    if not m:
        return ("", 0)
    return (m.group(1), int(m.group(2)))


def get_cell_value_from_xml(cell_elem, shared_strings):
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


def cell_value_for_column(row_elem, col_letter, shared_strings):
    for c in row_elem.findall(NS + "c"):
        ref = c.attrib.get("r", "")
        if not ref:
            continue
        cl, _ = parse_cell_ref(ref)
        if cl == col_letter:
            return get_cell_value_from_xml(c, shared_strings)
    return ""


def build_cascaded_modules(rows, col_letter, shared_strings):
    """Return a list of (row_index, module_name) with Excel-style cascading.

    Empty cells (no <v> or empty <v>) inherit the most recent non-empty value
    above. This matches how Excel renders merged-cell columns.
    """
    result = []
    last_nonempty = ""
    for row in rows[1:]:
        v = cell_value_for_column(row, col_letter, shared_strings).strip()
        if v:
            last_nonempty = v
        result.append((row, last_nonempty))
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--src", required=True)
    p.add_argument("--dst", required=True)
    p.add_argument("--modules", nargs="*", default=None)
    p.add_argument("--max-per-module", type=int, default=None)
    p.add_argument("--sheet", type=int, default=1, help="1-based sheet number")
    args = p.parse_args()

    src = Path(args.src)
    dst = Path(args.dst)
    if not src.exists():
        print(f"ERROR: source not found: {src}", file=sys.stderr)
        return 1
    if dst.exists():
        print(f"ERROR: dst already exists: {dst} - refusing to overwrite", file=sys.stderr)
        return 1

    sheet_xml_path = "xl/worksheets/sheet1.xml"
    if args.sheet != 1:
        sheet_xml_path = f"xl/worksheets/sheet{args.sheet}.xml"

    with zipfile.ZipFile(src) as zin:
        ss_bytes = zin.read("xl/sharedStrings.xml")
        sheet_bytes = zin.read(sheet_xml_path)

    ss_root = ET.fromstring(ss_bytes)
    shared_strings = []
    for si in ss_root.iter(NS + "si"):
        t = si.find(NS + "t")
        if t is not None:
            shared_strings.append(t.text or "")
        else:
            shared_strings.append("".join((tt.text or "") for tt in si.iter(NS + "t")))

    sheet_root = ET.fromstring(sheet_bytes)
    sheet_data = sheet_root.find(NS + "sheetData")
    if sheet_data is None:
        print("ERROR: no sheetData in source sheet", file=sys.stderr)
        return 1

    rows = list(sheet_data.findall(NS + "row"))
    print(f"Source: {len(rows)} rows, {len(shared_strings)} shared strings")

    new_sheet_data = ET.Element(NS + "sheetData")
    header = rows[0] if rows else None
    if header is None:
        print("ERROR: source has no rows", file=sys.stderr)
        return 1

    new_header = ET.fromstring(ET.tostring(header))
    new_header.set("r", "1")
    for c in new_header.findall(NS + "c"):
        ref = c.attrib.get("r", "")
        cl, _ = parse_cell_ref(ref)
        if cl:
            c.set("r", cl + "1")
    new_sheet_data.append(new_header)

    per_module_count = {m: 0 for m in (args.modules or [])}
    new_row_idx = 1
    kept = 0
    cascaded = build_cascaded_modules(rows, COL_LETTERS[COL_MODULE], shared_strings)
    for row, mod_val in cascaded:
        if args.modules and mod_val not in args.modules:
            continue
        if args.modules and args.max_per_module is not None and per_module_count.get(mod_val, 0) >= args.max_per_module:
            continue

        new_row_idx += 1
        new_row = ET.fromstring(ET.tostring(row))
        new_row.set("r", str(new_row_idx))
        for c in new_row.findall(NS + "c"):
            ref = c.attrib.get("r", "")
            cl, _ = parse_cell_ref(ref)
            if cl:
                c.set("r", cl + str(new_row_idx))
        new_sheet_data.append(new_row)
        if args.modules:
            per_module_count[mod_val] = per_module_count.get(mod_val, 0) + 1
        kept += 1

    print(f"Kept {kept} data rows. Module distribution: {per_module_count}")

    new_sheet_root = ET.fromstring(ET.tostring(sheet_root))
    old_sd = new_sheet_root.find(NS + "sheetData")
    if old_sd is not None:
        new_sheet_root.remove(old_sd)
    new_sheet_root.append(new_sheet_data)
    dim = new_sheet_root.find(NS + "dimension")
    if dim is not None:
        last_col = COL_LETTERS[len(COL_LETTERS) - 1]
        dim.set("ref", f"A1:{last_col}{new_row_idx}")
    new_sheet_bytes = ET.tostring(new_sheet_root, xml_declaration=True, encoding="UTF-8")

    dst.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(src) as zin:
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.namelist():
                if item == sheet_xml_path:
                    zout.writestr(item, new_sheet_bytes)
                else:
                    zout.writestr(item, zin.read(item))

    print(f"Mirror written: {dst}")
    print(f"Final: {new_row_idx} rows (1 header + {kept} data) x 16 cols")
    return 0


if __name__ == "__main__":
    sys.exit(main())
