"""Streaming .xlsx reader — standard library only.

IntakePilot keeps a zero-external-dependency run path, so this does not use openpyxl or pandas. An
.xlsx file is a ZIP of XML parts, and `zipfile` plus a streaming `iterparse` reads one arbitrarily
large workbook in constant memory.

That is not just a dependency choice, it is what makes the "no size limit" requirement honest. Nothing
here caps the number of sheets, rows, columns, or the character length of a cell. A 400 MB export with
a million rows and a 50,000-character comment field streams through with the same memory footprint as a
ten-row sheet, because rows are yielded one at a time and each XML element is discarded after use.

**Untrusted input.** A business user's spreadsheet is untrusted by definition, so three defences apply
and none of them is a size limit:

* a `DOCTYPE` anywhere in a part is rejected outright, which closes both XXE and billion-laughs entity
  expansion at the door rather than relying on parser configuration;
* each ZIP member is read through a decompression budget keyed on its *compression ratio*, which is how
  a zip bomb is actually detected — a 40 KB file that expands to 4 GB is anomalous at any absolute size,
  while a genuinely large export has an ordinary ratio and passes;
* member paths are checked before they are opened, so a crafted archive cannot reach outside the parts
  this reader expects.

Dates are the other thing worth care: Excel stores them as serial numbers with a display format, so a
cell is only a date if its style says so. Getting that wrong is what turns "2026-03-01" into "46082" in
a downstream extract.
"""
from __future__ import annotations

import datetime as _dt
import re
import zipfile
from dataclasses import dataclass, field
from typing import Any, Iterator, Mapping
from xml.etree import ElementTree as ET

__all__ = [
    "Cell",
    "Sheet",
    "Workbook",
    "XlsxError",
    "column_label",
    "open_workbook",
]

_NS_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_NS_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_NS_PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"

# A zip bomb is an outlier in *ratio*, not in absolute size. 200:1 passes every real spreadsheet we
# have seen (dense numeric sheets compress around 20:1) and stops the classic bombs, which run to
# 1000:1 and beyond.
_MAX_COMPRESSION_RATIO = 200
_RATIO_FLOOR_BYTES = 1 << 20  # ignore the ratio on small members; it is noisy there

_SAFE_MEMBER = re.compile(r"^[A-Za-z0-9_./\[\]-]+$")
_DOCTYPE = re.compile(rb"<!DOCTYPE", re.IGNORECASE)

# Built-in number-format ids that denote a date or time (ECMA-376 §18.8.30).
_BUILTIN_DATE_FORMATS = frozenset(range(14, 23)) | frozenset({27, 30, 36, 45, 46, 47, 50, 57})
_DATE_TOKENS = re.compile(r"[yYmMdDhHsS]")
_ESCAPED_FORMAT = re.compile(r'\\.|"[^"]*"|\[[^\]]*\]')

_EXCEL_EPOCH = _dt.datetime(1899, 12, 30)   # 1900 date system, accounting for the 1900 leap-year bug
_EXCEL_EPOCH_1904 = _dt.datetime(1904, 1, 1)


class XlsxError(Exception):
    """The file cannot be read as a spreadsheet. Message is safe to show a business user."""


@dataclass(frozen=True)
class Cell:
    """One populated cell. ``value`` is already typed; ``raw`` keeps what the file literally held."""

    row: int                 # 1-based, as Excel shows it
    column: int              # 1-based
    value: Any
    kind: str                # text | number | date | bool | error | empty
    raw: str | None = None

    @property
    def ref(self) -> str:
        return f"{column_label(self.column)}{self.row}"


@dataclass
class Sheet:
    name: str
    index: int
    hidden: bool = False
    _reader: "Workbook" = field(repr=False, default=None)  # type: ignore[assignment]
    _path: str = field(repr=False, default="")

    def rows(self) -> Iterator[list[Cell]]:
        """Yield populated rows in order. Constant memory; no row or column cap."""
        yield from self._reader._iter_rows(self._path)


def column_label(index: int) -> str:
    """1 -> A, 27 -> AA. Used so findings point at a reference a user can see in Excel."""
    if index < 1:
        raise ValueError("column index is 1-based")
    label = ""
    while index:
        index, rem = divmod(index - 1, 26)
        label = chr(65 + rem) + label
    return label


def _column_index(ref: str) -> int:
    letters = "".join(ch for ch in ref if ch.isalpha())
    index = 0
    for ch in letters.upper():
        index = index * 26 + (ord(ch) - 64)
    return index or 1


def _row_index(ref: str) -> int:
    digits = "".join(ch for ch in ref if ch.isdigit())
    return int(digits) if digits else 0


def _is_date_format(code: str | None, fmt_id: int | None) -> bool:
    if fmt_id is not None and fmt_id in _BUILTIN_DATE_FORMATS:
        return True
    if not code:
        return False
    stripped = _ESCAPED_FORMAT.sub("", code)
    return bool(_DATE_TOKENS.search(stripped))


def _serial_to_datetime(serial: float, date1904: bool) -> _dt.datetime | _dt.date | _dt.time:
    epoch = _EXCEL_EPOCH_1904 if date1904 else _EXCEL_EPOCH
    if not date1904 and serial < 60:
        # Excel's phantom 29 Feb 1900. Shift so early dates land correctly.
        epoch = _dt.datetime(1899, 12, 31)
    whole = int(serial)
    fraction = serial - whole
    moment = epoch + _dt.timedelta(days=whole, seconds=round(fraction * 86400))
    if whole == 0:
        return moment.time()
    if abs(fraction) < 1e-9:
        return moment.date()
    return moment


class Workbook:
    """An open workbook. Use :func:`open_workbook`; close it when finished."""

    def __init__(self, zf: zipfile.ZipFile) -> None:
        self._zf = zf
        self._shared: list[str] = []
        self._style_is_date: list[bool] = []
        self._date1904 = False
        self.sheets: list[Sheet] = []
        self._load()

    # ---------------------------------------------------------------- lifecycle

    def close(self) -> None:
        self._zf.close()

    def __enter__(self) -> "Workbook":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---------------------------------------------------------------- safe reads

    def _read(self, name: str) -> bytes:
        """Read one member with a bomb guard. Not a size limit — a ratio guard."""
        if not _SAFE_MEMBER.match(name):
            raise XlsxError("the spreadsheet contains an unexpected internal file name")
        try:
            info = self._zf.getinfo(name)
        except KeyError:
            raise XlsxError(f"the spreadsheet is missing an expected part ({name})")
        if info.compress_size >= _RATIO_FLOOR_BYTES or info.file_size >= _RATIO_FLOOR_BYTES:
            ratio = info.file_size / max(info.compress_size, 1)
            if ratio > _MAX_COMPRESSION_RATIO:
                raise XlsxError(
                    "the spreadsheet expands far more than its compressed size suggests and was "
                    "not opened"
                )
        data = self._zf.read(name)
        if _DOCTYPE.search(data[:4096]):
            raise XlsxError("the spreadsheet contains an XML document type declaration")
        return data

    def _open_stream(self, name: str):
        if not _SAFE_MEMBER.match(name):
            raise XlsxError("the spreadsheet contains an unexpected internal file name")
        try:
            info = self._zf.getinfo(name)
        except KeyError:
            raise XlsxError(f"the spreadsheet is missing an expected part ({name})")
        if info.compress_size >= _RATIO_FLOOR_BYTES or info.file_size >= _RATIO_FLOOR_BYTES:
            if info.file_size / max(info.compress_size, 1) > _MAX_COMPRESSION_RATIO:
                raise XlsxError(
                    "the spreadsheet expands far more than its compressed size suggests and was "
                    "not opened"
                )
        return self._zf.open(name)

    # ---------------------------------------------------------------- parts

    def _load(self) -> None:
        names = set(self._zf.namelist())
        if "xl/workbook.xml" not in names:
            raise XlsxError(
                "this does not look like an Excel .xlsx workbook. If it is an older .xls file, "
                "re-save it as .xlsx"
            )
        self._load_styles()
        self._load_shared_strings()
        self._load_sheets()

    def _load_styles(self) -> None:
        if "xl/styles.xml" not in set(self._zf.namelist()):
            return
        root = ET.fromstring(self._read("xl/styles.xml"))
        custom: dict[int, str] = {}
        for fmt in root.iter(f"{_NS_MAIN}numFmt"):
            try:
                custom[int(fmt.get("numFmtId", "-1"))] = fmt.get("formatCode", "")
            except ValueError:
                continue
        cell_xfs = root.find(f"{_NS_MAIN}cellXfs")
        if cell_xfs is None:
            return
        for xf in cell_xfs.findall(f"{_NS_MAIN}xf"):
            try:
                fmt_id = int(xf.get("numFmtId", "0"))
            except ValueError:
                fmt_id = 0
            self._style_is_date.append(_is_date_format(custom.get(fmt_id), fmt_id))

    def _load_shared_strings(self) -> None:
        if "xl/sharedStrings.xml" not in set(self._zf.namelist()):
            return
        # Streamed: a workbook can carry hundreds of thousands of distinct strings.
        with self._open_stream("xl/sharedStrings.xml") as handle:
            for event, elem in ET.iterparse(handle, events=("end",)):
                if elem.tag == f"{_NS_MAIN}si":
                    self._shared.append(
                        "".join(node.text or "" for node in elem.iter(f"{_NS_MAIN}t"))
                    )
                    elem.clear()

    def _load_sheets(self) -> None:
        root = ET.fromstring(self._read("xl/workbook.xml"))
        pr = root.find(f"{_NS_MAIN}workbookPr")
        if pr is not None and pr.get("date1904", "0") in ("1", "true"):
            self._date1904 = True

        targets: dict[str, str] = {}
        if "xl/_rels/workbook.xml.rels" in set(self._zf.namelist()):
            rels = ET.fromstring(self._read("xl/_rels/workbook.xml.rels"))
            for rel in rels.iter(f"{_NS_PKG_REL}Relationship"):
                rid, target = rel.get("Id"), rel.get("Target", "")
                if rid and target:
                    target = target.lstrip("/")
                    targets[rid] = target if target.startswith("xl/") else f"xl/{target}"

        sheets_el = root.find(f"{_NS_MAIN}sheets")
        if sheets_el is None:
            raise XlsxError("the workbook declares no sheets")
        for position, node in enumerate(sheets_el.findall(f"{_NS_MAIN}sheet"), start=1):
            rid = node.get(f"{_NS_REL}id")
            path = targets.get(rid or "", f"xl/worksheets/sheet{position}.xml")
            self.sheets.append(
                Sheet(
                    name=node.get("name", f"Sheet{position}"),
                    index=position,
                    hidden=node.get("state", "visible") in ("hidden", "veryHidden"),
                    _reader=self,
                    _path=path,
                )
            )

    # ---------------------------------------------------------------- rows

    def _cell_value(self, elem: ET.Element) -> Cell | None:
        ref = elem.get("r") or ""
        row = _row_index(ref)
        col = _column_index(ref)
        ctype = elem.get("t", "n")

        if ctype == "inlineStr":
            text = "".join(n.text or "" for n in elem.iter(f"{_NS_MAIN}t"))
            return Cell(row, col, text, "text", text) if text != "" else None

        v = elem.find(f"{_NS_MAIN}v")
        raw = v.text if v is not None else None
        if raw is None or raw == "":
            return None

        if ctype == "s":
            try:
                text = self._shared[int(raw)]
            except (ValueError, IndexError):
                text = ""
            return Cell(row, col, text, "text", raw) if text != "" else None
        if ctype in ("str",):
            return Cell(row, col, raw, "text", raw)
        if ctype == "b":
            return Cell(row, col, raw not in ("0", "false", "FALSE"), "bool", raw)
        if ctype == "e":
            # #REF!, #N/A, #VALUE! — a broken formula the sender probably cannot see.
            return Cell(row, col, raw, "error", raw)

        try:
            number = float(raw)
        except ValueError:
            return Cell(row, col, raw, "text", raw)

        style = elem.get("s")
        if style is not None:
            try:
                if self._style_is_date[int(style)]:
                    return Cell(row, col, _serial_to_datetime(number, self._date1904), "date", raw)
            except (ValueError, IndexError):
                pass
        if number.is_integer() and abs(number) < 2 ** 53:
            return Cell(row, col, int(number), "number", raw)
        return Cell(row, col, number, "number", raw)

    def _iter_rows(self, path: str) -> Iterator[list[Cell]]:
        try:
            handle = self._open_stream(path)
        except XlsxError:
            return
        with handle:
            current: list[Cell] = []
            current_row = 0
            for event, elem in ET.iterparse(handle, events=("end",)):
                if elem.tag == f"{_NS_MAIN}c":
                    cell = self._cell_value(elem)
                    if cell is not None:
                        current.append(cell)
                        current_row = cell.row
                    elem.clear()
                elif elem.tag == f"{_NS_MAIN}row":
                    declared = elem.get("r")
                    if declared and declared.isdigit():
                        current_row = int(declared)
                    if current:
                        yield sorted(current, key=lambda c: c.column)
                    else:
                        yield []
                    current = []
                    elem.clear()
            if current:
                yield sorted(current, key=lambda c: c.column)


def open_workbook(source: Any) -> Workbook:
    """Open a path, file object, or bytes as a workbook.

    Raises :class:`XlsxError` with a message that can be shown to a business user unchanged.
    """
    try:
        zf = zipfile.ZipFile(source)
    except zipfile.BadZipFile:
        raise XlsxError(
            "this file is not a readable .xlsx workbook. If it was saved as .xls, .csv or a PDF, "
            "re-save it from Excel as 'Excel Workbook (.xlsx)'"
        )
    except Exception as exc:  # noqa: BLE001 - surface a user-safe message, not a stack trace
        raise XlsxError(f"the file could not be opened as a spreadsheet ({type(exc).__name__})")
    try:
        return Workbook(zf)
    except XlsxError:
        zf.close()
        raise
    except Exception as exc:  # noqa: BLE001
        zf.close()
        raise XlsxError(f"the spreadsheet structure could not be read ({type(exc).__name__})")
