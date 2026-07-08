"""Mirror xlsx write — one row at a time, no openpyxl read of stylesheet.

The mirror is the .xlsx that QA opens in Excel to see test results. We
write col 14 (执行结果) and col 15 (备注) for one row at a time, using
the same zipfile+xml approach as excelio-mcp-server. This avoids
openpyxl's broken-stylesheet crash on the source file.

API:
  write_mirror_cell(path, sheet_row, status, note)
"""

from __future__ import annotations

import shutil
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS = "{" + NS_MAIN + "}"


def write_mirror_cell(path: str, sheet_row: int, status: str, note: str) -> None:
    """Update col 14 and 15 of `sheet_row` in sheet1 of `path`."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"mirror not found: {path}")

    # Read all entries; we'll rewrite only the sheet.
    with zipfile.ZipFile(p, "r") as zin:
        entries = {name: zin.read(name) for name in zin.namelist()}

    sheet_xml = entries.get("xl/worksheets/sheet1.xml")
    if sheet_xml is None:
        raise RuntimeError("mirror missing xl/worksheets/sheet1.xml")

    # Parse, mutate, re-pack.
    ET.register_namespace("", NS_MAIN)
    root = ET.fromstring(sheet_xml)
    sheet_data = root.find(NS + "sheetData")
    if sheet_data is None:
        raise RuntimeError("mirror sheetData missing")

    # Find or create the target row.
    target_row = None
    for row in sheet_data.findall(NS + "row"):
        if row.attrib.get("r") == str(sheet_row):
            target_row = row
            break
    if target_row is None:
        target_row = ET.SubElement(sheet_data, NS + "row")
        target_row.set("r", str(sheet_row))

    def cell(col_letter: str, value: str) -> ET.Element:
        c = ET.SubElement(target_row, NS + "c")
        c.set("r", f"{col_letter}{sheet_row}")
        c.set("t", "inlineStr")
        is_el = ET.SubElement(c, NS + "is")
        t = ET.SubElement(is_el, NS + "t")
        t.text = value
        return c

    # Remove any existing cells at col O (14) and P (15) for this row.
    for c in list(target_row.findall(NS + "c")):
        ref = c.attrib.get("r", "")
        if ref.startswith(("O", "P")) and ref.endswith(str(sheet_row)):
            target_row.remove(c)

    cell("O", status)
    cell("P", (note or "")[:200])

    new_sheet = ET.tostring(root, xml_declaration=True, encoding="UTF-8")

    # Atomic-ish: write to a temp then replace.
    tmp = p.with_suffix(p.suffix + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, data in entries.items():
            if name == "xl/worksheets/sheet1.xml":
                zout.writestr(name, new_sheet)
            else:
                zout.writestr(name, data)
    shutil.move(str(tmp), str(p))
