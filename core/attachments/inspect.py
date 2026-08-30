"""Structural inspection of an attached spreadsheet.

The delay this exists to remove is not caused by exotic files. It is caused by ordinary ones: a title
row above the header, a column of IDs that Excel quietly stored as text so the join silently drops
rows, a `#REF!` the sender cannot see because their screen shows a cached value, two columns with the
same name, or the data sitting on the second tab while the first is blank. Each costs a round trip of
several days, and each is detectable in seconds.

Every finding carries a cell or row reference the user can type into Excel's name box, and a fix
written for the person who made the file rather than for a developer.

Three deliberate non-limits, because they are the point of the request:

* **no cap on rows, columns or sheets** — column statistics are accumulated in a single streaming pass,
  so a million-row sheet costs the same memory as a hundred-row one;
* **no cap on cell character length** — a 60,000-character comment is inspected and preserved in full.
  Findings show a short excerpt for readability, and `excerpt_of` records the true length so nobody
  mistakes the excerpt for the value;
* **nothing is rejected for being large.** Severity reflects whether the sheet is usable, never its size.
"""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Iterator

from .xlsx import Cell, Sheet, Workbook, column_label

__all__ = [
    "Finding",
    "SheetReport",
    "Severity",
    "inspect_sheet",
    "inspect_workbook",
]

Severity = str  # "blocking" | "warning" | "info"

_HEADER_SCAN_ROWS = 25          # how far to look for a header; not a limit on the file
_TYPE_SAMPLE_EXCERPT = 60       # display only — never a validation limit

_NUMERIC_TEXT = re.compile(r"^\s*[-+]?[\d,]*\.?\d+\s*%?\s*$")
_DATE_TEXT = re.compile(
    r"^\s*(\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}"
    r"|\d{1,2}[-\s][A-Za-z]{3,9}[-\s]\d{2,4}"
    r"|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})\s*$"
)
_DELIMITED_BLOB = re.compile(r"^[^,;|\t]+([,;|\t][^,;|\t]+){2,}$")
_ERROR_LITERAL = re.compile(r"^#(REF|N/A|VALUE|DIV/0|NAME\?|NULL|NUM)!?$", re.IGNORECASE)


def _excerpt(value: Any) -> tuple[str, int | None]:
    """Return a short display form plus the true length when it was shortened."""
    text = value if isinstance(value, str) else str(value)
    if len(text) <= _TYPE_SAMPLE_EXCERPT:
        return text, None
    return text[:_TYPE_SAMPLE_EXCERPT] + "…", len(text)


@dataclass
class Finding:
    code: str
    severity: Severity
    message: str
    fix: str
    sheet: str | None = None
    ref: str | None = None          # A1-style, so the user can jump straight to it
    column: str | None = None       # header name when the finding is column-scoped
    count: int = 1                  # how many cells/rows share this problem
    excerpt: str | None = None
    excerpt_of: int | None = None   # true character length when excerpt was shortened

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class ColumnProfile:
    index: int
    header: str | None
    kinds: dict[str, int] = field(default_factory=dict)
    populated: int = 0
    numeric_text: int = 0
    date_text: int = 0
    whitespace: int = 0
    errors: int = 0
    first_error_ref: str | None = None
    first_numeric_text_ref: str | None = None
    first_date_text_ref: str | None = None
    longest_value: int = 0

    @property
    def label(self) -> str:
        return self.header or f"column {column_label(self.index)}"

    def dominant_kind(self) -> str | None:
        if not self.kinds:
            return None
        return max(self.kinds.items(), key=lambda kv: kv[1])[0]


@dataclass
class SheetReport:
    name: str
    index: int
    hidden: bool
    header_row: int | None
    headers: list[str]
    data_rows: int
    columns: list[ColumnProfile]
    findings: list[Finding]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "index": self.index,
            "hidden": self.hidden,
            "header_row": self.header_row,
            "headers": self.headers,
            "data_rows": self.data_rows,
            "findings": [f.as_dict() for f in self.findings],
        }


def _looks_like_header(row: list[Cell]) -> bool:
    """A header row is mostly short text, with no formula errors and few numbers.

    Single-column sheets are legitimate and common — a list of material numbers, cost centres or
    document numbers — so width one is accepted when the cell is text. A lone title row is excluded
    separately in :func:`_detect_header`, by requiring data on the very next row.
    """
    if not row:
        return False
    if any(c.kind == "error" for c in row):
        return False
    if len(row) == 1:
        return row[0].kind == "text"
    text = sum(1 for c in row if c.kind == "text")
    numeric = sum(1 for c in row if c.kind in ("number", "date"))
    return text >= max(2, len(row) - numeric) and text > numeric


def _detect_header(buffered: list[list[Cell]]) -> int | None:
    """Return the index within ``buffered`` of the most plausible header row.

    The header is the *earliest* row that both looks like a header and is about as wide as the data
    beneath it. Scoring on width alone is wrong: a data row of mostly-text values is often wider than
    the real header (a header with a merged or empty cell has fewer populated cells than its rows),
    and picking it silently discards the first data rows and renames every column after a value.

    Width relative to the body is what separates a header from a title. A title sits alone in column A
    while the data runs five columns wide; a header spans roughly the same width as its rows.
    """
    populated = [(i, r) for i, r in enumerate(buffered) if r]
    if not populated:
        return None

    widths = [len(r) for _, r in populated]
    # Tie-break toward the wider shape: with equal votes, narrow rows are titles and notes,
    # wide rows are the table. (Two title lines above two data rows is a real, observed case.)
    modal = max(set(widths), key=lambda w: (widths.count(w), w))
    floor = max(1, int(modal * 0.6))

    for position, row in populated:
        if not _looks_like_header(row):
            continue
        if len(row) < floor:
            continue  # too narrow for the body — a title or a stray note
        following = buffered[position + 1] if position + 1 < len(buffered) else []
        if len(row) == 1 and not following:
            continue  # a lone text cell with nothing beneath it is a title
        return position
    return None


def inspect_sheet(sheet: Sheet) -> SheetReport:
    """Stream one sheet and describe everything wrong with its shape."""
    findings: list[Finding] = []
    rows_iter = sheet.rows()

    buffered: list[list[Cell]] = []
    for row in rows_iter:
        buffered.append(row)
        if len(buffered) >= _HEADER_SCAN_ROWS:
            break

    populated_buffered = [r for r in buffered if r]
    if not populated_buffered:
        findings.append(Finding(
            code="sheet_empty", severity="info", sheet=sheet.name,
            message=f"Sheet '{sheet.name}' is empty.",
            fix="If the data should be here, check you saved the right tab.",
        ))
        return SheetReport(sheet.name, sheet.index, sheet.hidden, None, [], 0, [], findings)

    header_position = _detect_header(buffered)
    if header_position is None:
        findings.append(Finding(
            code="header_not_found", severity="blocking", sheet=sheet.name,
            message=f"No column header row could be identified on '{sheet.name}'.",
            fix="Put one row of short column names directly above the data, with no blank row "
                "between them.",
        ))
        header_row_cells: list[Cell] = []
        header_row_number = None
    else:
        header_row_cells = buffered[header_position]
        header_row_number = header_row_cells[0].row if header_row_cells else None
        preamble = [r for r in buffered[:header_position] if r]
        if preamble:
            first = preamble[0][0]
            excerpt, true_len = _excerpt(first.value)
            findings.append(Finding(
                code="preamble_before_header", severity="warning", sheet=sheet.name,
                ref=first.ref, count=len(preamble),
                message=f"{len(preamble)} row(s) sit above the column headers on '{sheet.name}' "
                        f"(headers are on row {header_row_number}).",
                fix="Delete the title/notes rows so the header is row 1, or tell us which row the "
                    "headers are on.",
                excerpt=excerpt, excerpt_of=true_len,
            ))

    # ---- header quality -------------------------------------------------
    headers: list[str] = []
    columns: dict[int, ColumnProfile] = {}
    seen: dict[str, int] = {}
    for cell in header_row_cells:
        raw = cell.value if isinstance(cell.value, str) else str(cell.value)
        name = raw.strip()
        if name != raw:
            findings.append(Finding(
                code="header_whitespace", severity="warning", sheet=sheet.name, ref=cell.ref,
                message=f"Header '{name}' has leading or trailing spaces.",
                fix="Remove the extra spaces — they stop the column being matched by name.",
            ))
        key = name.casefold()
        if key in seen:
            findings.append(Finding(
                code="duplicate_header", severity="blocking", sheet=sheet.name, ref=cell.ref,
                column=name,
                message=f"Column name '{name}' appears more than once on '{sheet.name}'.",
                fix="Give each column a distinct name — duplicates make it ambiguous which one to use.",
            ))
        seen[key] = cell.column
        headers.append(name)
        columns[cell.column] = ColumnProfile(index=cell.column, header=name)

    if header_row_cells:
        span = range(header_row_cells[0].column, header_row_cells[-1].column + 1)
        gaps = [c for c in span if c not in columns]
        if gaps:
            findings.append(Finding(
                code="header_gap", severity="warning", sheet=sheet.name,
                ref=f"{column_label(gaps[0])}{header_row_number}", count=len(gaps),
                message=f"{len(gaps)} column(s) between the headers have no name "
                        f"(e.g. {column_label(gaps[0])}).",
                fix="Name every column that holds data, or delete the empty ones. Merged header "
                    "cells also show up this way — unmerge them.",
            ))

    # ---- data pass (streaming, unbounded) --------------------------------
    header_width = header_row_cells[-1].column if header_row_cells else 0
    data_rows = 0
    ragged: list[str] = []
    blob_hits: list[str] = []

    def _remaining() -> Iterator[list[Cell]]:
        start = 0 if header_position is None else header_position + 1
        yield from buffered[start:]
        yield from rows_iter

    for row in _remaining():
        if not row:
            continue
        data_rows += 1
        if header_width and row[-1].column > header_width:
            if len(ragged) < 3:
                ragged.append(row[-1].ref)
        for cell in row:
            profile = columns.get(cell.column)
            if profile is None:
                profile = ColumnProfile(index=cell.column, header=None)
                columns[cell.column] = profile
            profile.populated += 1
            profile.kinds[cell.kind] = profile.kinds.get(cell.kind, 0) + 1

            if cell.kind == "error":
                profile.errors += 1
                profile.first_error_ref = profile.first_error_ref or cell.ref
            elif cell.kind == "text":
                text = cell.value
                profile.longest_value = max(profile.longest_value, len(text))
                if text.strip() != text:
                    profile.whitespace += 1
                stripped = text.strip()
                if _ERROR_LITERAL.match(stripped):
                    profile.errors += 1
                    profile.first_error_ref = profile.first_error_ref or cell.ref
                elif _NUMERIC_TEXT.match(stripped) and len(stripped) > 0:
                    profile.numeric_text += 1
                    profile.first_numeric_text_ref = profile.first_numeric_text_ref or cell.ref
                elif _DATE_TEXT.match(stripped):
                    profile.date_text += 1
                    profile.first_date_text_ref = profile.first_date_text_ref or cell.ref
                elif _DELIMITED_BLOB.match(stripped) and len(blob_hits) < 3:
                    blob_hits.append(cell.ref)

    if ragged:
        findings.append(Finding(
            code="ragged_rows", severity="warning", sheet=sheet.name, ref=ragged[0],
            count=len(ragged),
            message="Some rows have values in columns to the right of the last header "
                    f"(e.g. {', '.join(ragged)}).",
            fix="Either add a header for those columns or clear the stray values.",
        ))

    if blob_hits and len(columns) <= 2:
        findings.append(Finding(
            code="delimited_blob", severity="blocking", sheet=sheet.name, ref=blob_hits[0],
            message="The data looks like comma- or semicolon-separated text pasted into a single "
                    "column rather than split across columns.",
            fix="In Excel use Data → Text to Columns to split it, then re-save.",
        ))

    ordered = [columns[k] for k in sorted(columns)]
    for profile in ordered:
        if profile.header is None and profile.populated:
            findings.append(Finding(
                code="unnamed_column_with_data", severity="warning", sheet=sheet.name,
                ref=f"{column_label(profile.index)}{(header_row_number or 0) + 1}",
                count=profile.populated,
                message=f"Column {column_label(profile.index)} holds {profile.populated} value(s) "
                        "but has no header.",
                fix="Give the column a name so it can be matched, or remove it.",
            ))
        if profile.errors:
            findings.append(Finding(
                code="formula_errors", severity="blocking", sheet=sheet.name,
                ref=profile.first_error_ref, column=profile.header, count=profile.errors,
                message=f"'{profile.label}' contains {profile.errors} formula error(s) such as "
                        "#REF! or #N/A.",
                fix="Fix the formulas, or paste the values only (Paste Special → Values) before "
                    "sending.",
            ))
        if profile.numeric_text and profile.numeric_text >= max(1, profile.populated // 2):
            findings.append(Finding(
                code="numbers_stored_as_text", severity="warning", sheet=sheet.name,
                ref=profile.first_numeric_text_ref, column=profile.header,
                count=profile.numeric_text,
                message=f"'{profile.label}' looks numeric but {profile.numeric_text} value(s) are "
                        "stored as text.",
                fix="Select the column and use Data → Text to Columns → Finish to convert it. Text "
                    "numbers silently fail to match when the data is joined.",
            ))
        if profile.date_text and profile.date_text >= max(1, profile.populated // 2):
            findings.append(Finding(
                code="dates_stored_as_text", severity="warning", sheet=sheet.name,
                ref=profile.first_date_text_ref, column=profile.header, count=profile.date_text,
                message=f"'{profile.label}' looks like dates but {profile.date_text} value(s) are "
                        "stored as text.",
                fix="Format the column as a date so the order and range are unambiguous.",
            ))
        if profile.whitespace:
            findings.append(Finding(
                code="value_whitespace", severity="info", sheet=sheet.name, column=profile.header,
                count=profile.whitespace,
                message=f"'{profile.label}' has {profile.whitespace} value(s) with leading or "
                        "trailing spaces.",
                fix="Trim them — spaces stop values matching exactly.",
            ))
        kinds = {k: v for k, v in profile.kinds.items() if k != "empty"}
        if len(kinds) > 1:
            major = profile.dominant_kind()
            minor = sum(v for k, v in kinds.items() if k != major)
            if minor and minor < profile.populated // 2:
                findings.append(Finding(
                    code="mixed_types_in_column", severity="warning", sheet=sheet.name,
                    column=profile.header, count=minor,
                    message=f"'{profile.label}' is mostly {major} but {minor} value(s) are a "
                            "different type.",
                    fix="Make the column consistent, or tell us which rows are the exception.",
                ))
        if profile.header and profile.populated == 0:
            findings.append(Finding(
                code="empty_column", severity="info", sheet=sheet.name, column=profile.header,
                message=f"Column '{profile.header}' has a header but no data.",
                fix="Fill it in or remove it, so we do not treat it as a gap.",
            ))

    if header_row_cells and data_rows == 0:
        findings.append(Finding(
            code="headers_without_data", severity="blocking", sheet=sheet.name,
            message=f"'{sheet.name}' has column headers but no data rows.",
            fix="Add the rows, or point us at the tab that has them.",
        ))

    return SheetReport(sheet.name, sheet.index, sheet.hidden, header_row_number, headers,
                       data_rows, ordered, findings)


def inspect_workbook(book: Workbook) -> list[SheetReport]:
    """Inspect every sheet, including hidden ones — hidden tabs often hold the real data."""
    reports = [inspect_sheet(sheet) for sheet in book.sheets]

    visible_with_data = [r for r in reports if not r.hidden and r.data_rows]
    hidden_with_data = [r for r in reports if r.hidden and r.data_rows]

    if not visible_with_data and hidden_with_data:
        names = ", ".join(f"'{r.name}'" for r in hidden_with_data)
        reports[0].findings.insert(0, Finding(
            code="data_only_on_hidden_sheet", severity="blocking",
            message=f"Every visible sheet is empty; the data is on hidden sheet(s): {names}.",
            fix="Unhide the sheet with the data, or move it to a visible tab.",
        ))
    elif hidden_with_data:
        names = ", ".join(f"'{r.name}'" for r in hidden_with_data)
        reports[0].findings.append(Finding(
            code="hidden_sheet_with_data", severity="info",
            message=f"Hidden sheet(s) also contain data: {names}.",
            fix="Confirm whether they should be included — hidden tabs are easy to miss.",
        ))
    if not any(r.data_rows for r in reports):
        reports[0].findings.insert(0, Finding(
            code="workbook_empty", severity="blocking",
            message="The workbook contains no data on any sheet.",
            fix="Check that you attached the right file and that the data was saved.",
        ))
    return reports
