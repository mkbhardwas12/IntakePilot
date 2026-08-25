"""Build real .xlsx files with the standard library, so tests exercise genuine OOXML."""
from __future__ import annotations

import io
import zipfile
from typing import Any, Iterable, Sequence

_CT = """<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="xml" ContentType="application/xml"/>
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
</Types>"""

_ROOT_RELS = """<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

_STYLES = """<?xml version="1.0"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="1"><numFmt numFmtId="164" formatCode="yyyy\\-mm\\-dd"/></numFmts>
<cellXfs count="3">
<xf numFmtId="0"/><xf numFmtId="14"/><xf numFmtId="164"/>
</cellXfs></styleSheet>"""


def _col(i: int) -> str:
    s = ""
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _esc(t: str) -> str:
    return (t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _cell_xml(ref: str, value: Any) -> str:
    """Value forms: str -> inline text; int/float -> number; ('date', serial); ('error', '#REF!');
    ('text', '123') to force a numeric-looking string; ('bool', True)."""
    if value is None or value == "":
        return ""
    if isinstance(value, tuple):
        kind, payload = value
        if kind == "date":
            return f'<c r="{ref}" s="1"><v>{payload}</v></c>'
        if kind == "error":
            return f'<c r="{ref}" t="e"><v>{_esc(str(payload))}</v></c>'
        if kind == "bool":
            return f'<c r="{ref}" t="b"><v>{1 if payload else 0}</v></c>'
        if kind == "text":
            return f'<c r="{ref}" t="inlineStr"><is><t>{_esc(str(payload))}</t></is></c>'
    if isinstance(value, bool):
        return f'<c r="{ref}" t="b"><v>{1 if value else 0}</v></c>'
    if isinstance(value, (int, float)):
        return f'<c r="{ref}"><v>{value}</v></c>'
    return f'<c r="{ref}" t="inlineStr"><is><t>{_esc(str(value))}</t></is></c>'


def _sheet_xml(rows: Sequence[Sequence[Any]]) -> str:
    body = []
    for r, row in enumerate(rows, start=1):
        cells = "".join(_cell_xml(f"{_col(c)}{r}", v) for c, v in enumerate(row, start=1))
        body.append(f'<row r="{r}">{cells}</row>')
    return ('<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/'
            'spreadsheetml/2006/main"><sheetData>' + "".join(body) + "</sheetData></worksheet>")


def build_xlsx(sheets: dict[str, Sequence[Sequence[Any]]], hidden: Iterable[str] = ()) -> bytes:
    """sheets: {name: rows}. Returns .xlsx bytes."""
    hidden = set(hidden)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CT)
        z.writestr("_rels/.rels", _ROOT_RELS)
        z.writestr("xl/styles.xml", _STYLES)
        entries, rels = [], []
        for i, name in enumerate(sheets, start=1):
            state = ' state="hidden"' if name in hidden else ""
            entries.append(f'<sheet name="{_esc(name)}" sheetId="{i}" r:id="rId{i}"{state}/>')
            rels.append(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/'
                        f'officeDocument/2006/relationships/worksheet" '
                        f'Target="worksheets/sheet{i}.xml"/>')
            z.writestr(f"xl/worksheets/sheet{i}.xml", _sheet_xml(sheets[name]))
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/'
                   'spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/'
                   'officeDocument/2006/relationships"><sheets>' + "".join(entries)
                   + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/relationships">' + "".join(rels) + "</Relationships>")
    return buf.getvalue()
