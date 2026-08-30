"""Attachment validation — the spreadsheet problems that actually cause round trips.

Each test names a real failure mode a business user hits, because that is the thing being removed.
The last group pins the three explicit non-limits: file size, row count, and cell character length.
"""
from __future__ import annotations

import io
import zipfile

import pytest

from core.attachments import (
    AttachmentReport,
    XlsxError,
    analyze_attachment,
    column_label,
    normalize_name,
    open_workbook,
)
from tests.xlsx_factory import build_xlsx


def analyze(sheets, *, hidden=(), fields=None, filename="attachment.xlsx") -> AttachmentReport:
    data = build_xlsx(sheets, hidden=hidden)
    slots = {"data_fields": fields} if fields else None
    return analyze_attachment(io.BytesIO(data), filename=filename, slots=slots)


def codes(report: AttachmentReport) -> set[str]:
    return {f.code for f in report.findings}


# ------------------------------------------------------------------ the good case

def test_a_clean_sheet_is_ready():
    r = analyze({"Data": [["Customer", "Material", "Quantity"],
                          ["C-1", "M-1", 5], ["C-2", "M-2", 7]]})
    assert r.verdict == "ready"
    assert [f for f in r.findings if f.severity != "info"] == []
    assert "No problems found" in r.summary()
    assert r.sheets[0].header_row == 1
    assert r.sheets[0].data_rows == 2


# ------------------------------------------------------------------ shape problems

def test_title_rows_above_the_header_are_found_and_located():
    r = analyze({"Data": [["Q3 Data Request"], [], ["Customer", "Qty"], ["C-1", 5]]})
    assert "preamble_before_header" in codes(r)
    f = next(f for f in r.findings if f.code == "preamble_before_header")
    assert f.ref == "A1"
    assert r.sheets[0].header_row == 3


def test_duplicate_column_names_block():
    r = analyze({"Data": [["Customer", "Qty", "Customer"], ["C-1", 5, "C-2"]]})
    assert "duplicate_header" in codes(r)
    assert r.verdict == "unusable"


def test_header_whitespace_is_reported():
    r = analyze({"Data": [["Customer ", "Qty"], ["C-1", 5]]})
    assert "header_whitespace" in codes(r)


def test_a_gap_between_headers_is_reported():
    """This is also how a merged header cell presents."""
    r = analyze({"Data": [["Customer", "", "Qty"], ["C-1", "x", 5]]})
    assert "header_gap" in codes(r)


def test_values_beyond_the_last_header_are_reported():
    r = analyze({"Data": [["Customer", "Qty"], ["C-1", 5, "stray"]]})
    assert "ragged_rows" in codes(r)


def test_headers_with_no_data_block():
    r = analyze({"Data": [["Customer", "Qty"]]})
    assert "headers_without_data" in codes(r)
    assert r.verdict == "unusable"


def test_an_entirely_empty_workbook_blocks():
    r = analyze({"Sheet1": [[]]})
    assert "workbook_empty" in codes(r)
    assert r.verdict == "unusable"


def test_data_only_on_a_hidden_sheet_blocks():
    r = analyze({"Visible": [[]], "Secret": [["Customer", "Qty"], ["C-1", 5]]},
                hidden=["Secret"])
    assert "data_only_on_hidden_sheet" in codes(r)
    assert r.verdict == "unusable"


def test_a_hidden_sheet_alongside_visible_data_is_only_flagged():
    r = analyze({"Visible": [["Customer"], ["C-1"]], "Extra": [["Customer"], ["C-9"]]},
                hidden=["Extra"])
    assert "hidden_sheet_with_data" in codes(r)
    assert r.verdict != "unusable"


def test_csv_pasted_into_one_column_blocks():
    r = analyze({"Data": [["Everything"],
                          ["C-1,M-1,5"], ["C-2,M-2,7"], ["C-3,M-3,9"]]})
    assert "delimited_blob" in codes(r)


# ------------------------------------------------------------------ type problems

def test_formula_errors_block_and_point_at_the_first_cell():
    r = analyze({"Data": [["Customer", "Qty"],
                          ["C-1", ("error", "#REF!")], ["C-2", 5]]})
    assert "formula_errors" in codes(r)
    f = next(f for f in r.findings if f.code == "formula_errors")
    assert f.ref == "B2"
    assert r.verdict == "unusable"


def test_an_error_typed_as_plain_text_is_still_caught():
    r = analyze({"Data": [["Customer", "Qty"], ["C-1", ("text", "#N/A")], ["C-2", ("text", "#N/A")]]})
    assert "formula_errors" in codes(r)


def test_numbers_stored_as_text_are_flagged_with_a_fix():
    r = analyze({"Data": [["Customer", "Amount"],
                          ["C-1", ("text", "1234")], ["C-2", ("text", "5678")]]})
    assert "numbers_stored_as_text" in codes(r)
    f = next(f for f in r.findings if f.code == "numbers_stored_as_text")
    assert "Text to Columns" in f.fix
    assert f.ref == "B2"


def test_dates_stored_as_text_are_flagged():
    r = analyze({"Data": [["Customer", "Posted"],
                          ["C-1", ("text", "2026-03-01")], ["C-2", ("text", "2026-03-02")]]})
    assert "dates_stored_as_text" in codes(r)


def test_a_real_excel_date_is_decoded_not_flagged():
    r = analyze({"Data": [["Customer", "Posted"],
                          ["C-1", ("date", 46082)], ["C-2", ("date", 46083)]]})
    assert "dates_stored_as_text" not in codes(r)
    posted = next(c for c in r.sheets[0].columns if c.header == "Posted")
    assert posted.dominant_kind() == "date"


def test_trailing_spaces_in_values_are_reported():
    r = analyze({"Data": [["Customer"], [("text", "C-1 ")], [("text", "C-2 ")]]})
    assert "value_whitespace" in codes(r)


def test_a_mostly_numeric_column_with_a_stray_string_is_flagged():
    r = analyze({"Data": [["Customer", "Qty"], ["C-1", 5], ["C-2", 6], ["C-3", 7],
                          ["C-4", ("text", "n/a")]]})
    assert "mixed_types_in_column" in codes(r)


# ------------------------------------------------------------------ fitness

def test_a_requested_field_that_is_absent_blocks():
    r = analyze({"Data": [["Customer", "Qty"], ["C-1", 5]]},
                fields="customer, quantity, plant")
    assert r.fitness.verdict == "needs_fixes"
    assert [m.requested for m in r.fitness.missing] == ["plant"]
    assert "requested_field_missing" in codes(r)


def test_nothing_matching_at_all_is_unusable():
    r = analyze({"Data": [["Alpha", "Beta"], ["a", "b"]]}, fields="plant, vendor")
    assert r.fitness.verdict == "unusable"


def test_abbreviated_headers_still_match_what_was_asked_for():
    r = analyze({"Data": [["Cust #", "Matl Desc", "Qty"], ["C-1", "widget", 5]]},
                fields="customer number, material description, quantity")
    assert r.fitness.verdict == "ready"
    assert {c.matched_column for c in r.fitness.covered} == {"Cust #", "Matl Desc", "Qty"}


def test_a_loose_match_is_reported_so_a_human_can_confirm_it():
    r = analyze({"Data": [["Customer Number Extended"], ["C-1"]]}, fields="customer number")
    assert "field_matched_loosely" in codes(r)


def test_blanks_in_a_requested_column_are_reported():
    r = analyze({"Data": [["Customer", "Plant"], ["C-1", "P1"], ["C-2", None], ["C-3", None]]},
                fields="customer, plant")
    f = next(f for f in r.findings if f.code == "requested_field_partially_blank")
    assert f.count == 2


def test_extra_columns_are_noted_but_not_blocking():
    r = analyze({"Data": [["Customer", "Salary"], ["C-1", 100]]}, fields="customer")
    f = next(f for f in r.findings if f.code == "columns_not_requested")
    assert "Salary" in f.message
    assert f.severity == "info"


def test_without_stated_fields_fitness_says_so_rather_than_guessing():
    r = analyze({"Data": [["Customer", "Qty"], ["C-1", 5]]})
    assert r.fitness.verdict == "not_assessable"
    assert "no_requested_fields_to_check" in codes(r)


# ------------------------------------------------------------------ bad input

def test_a_non_spreadsheet_returns_advice_not_a_crash():
    r = analyze_attachment(io.BytesIO(b"just,a,csv\n1,2,3"), filename="data.csv")
    assert r.verdict == "unreadable"
    assert "re-save" in r.summary().lower()


def test_a_zip_that_is_not_a_workbook_is_refused():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("hello.txt", "hi")
    r = analyze_attachment(buf, filename="notes.zip")
    assert r.verdict == "unreadable"


def test_an_xml_doctype_is_refused():
    """Closes XXE and billion-laughs at the door rather than trusting parser defaults."""
    data = bytearray(build_xlsx({"Data": [["Customer"], ["C-1"]]}))
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(bytes(data))) as src, zipfile.ZipFile(buf, "w") as dst:
        for item in src.namelist():
            payload = src.read(item)
            if item == "xl/workbook.xml":
                payload = payload.replace(
                    b"<?xml version=\"1.0\"?>",
                    b"<?xml version=\"1.0\"?><!DOCTYPE x [<!ENTITY a \"b\">]>")
            dst.writestr(item, payload)
    with pytest.raises(XlsxError, match="document type"):
        open_workbook(buf)


def test_a_compression_bomb_is_refused_by_ratio_not_by_size():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/workbook.xml", "\0" * (40 << 20))   # ~40 MB of zeros, ~1000:1
    with pytest.raises(XlsxError, match="expands far more"):
        open_workbook(buf)


# ------------------------------------------------------------------ the three non-limits

def test_no_row_limit_a_large_sheet_streams_and_is_fully_counted():
    rows = [["Customer", "Qty"]] + [[f"C-{i}", i] for i in range(50_000)]
    r = analyze({"Data": rows}, fields="customer, quantity")
    assert r.sheets[0].data_rows == 50_000
    assert r.fitness.verdict == "ready"
    assert r.verdict == "ready"


def test_no_character_limit_a_very_long_cell_is_preserved_in_full():
    long_text = "x" * 120_000
    data = build_xlsx({"Data": [["Customer", "Notes"], ["C-1", long_text]]})
    with open_workbook(io.BytesIO(data)) as book:
        rows = list(book.sheets[0].rows())
    assert len(rows[1][1].value) == 120_000, "the cell must not be truncated"

    r = analyze({"Data": [["Customer", "Notes"], ["C-1", long_text]]})
    assert r.verdict != "unusable", "length alone must never make a file unusable"
    notes = next(c for c in r.sheets[0].columns if c.header == "Notes")
    assert notes.longest_value == 120_000


def test_an_excerpt_in_a_finding_declares_the_true_length():
    long_title = "y" * 5_000
    r = analyze({"Data": [[long_title], [], ["Customer"], ["C-1"]]})
    f = next(f for f in r.findings if f.code == "preamble_before_header")
    assert f.excerpt_of == 5_000
    assert len(f.excerpt) < 100


def test_no_column_or_sheet_limit():
    wide = [[f"Col{i}" for i in range(400)], [i for i in range(400)]]
    many = {f"S{i}": wide for i in range(30)}
    r = analyze(many)
    assert len(r.sheets) == 30
    assert len(r.sheets[0].headers) == 400


# ------------------------------------------------------------------ helpers

def test_column_labels_match_excel():
    assert [column_label(i) for i in (1, 26, 27, 702, 703)] == ["A", "Z", "AA", "ZZ", "AAA"]


def test_name_normalisation_folds_everyday_abbreviations():
    assert normalize_name("Cust #") == normalize_name("customer_number")
    assert normalize_name("PO No") == normalize_name("purchase order number")
    assert normalize_name("  Plant  ") == normalize_name("PLNT")


def test_the_report_serialises_for_an_api_response():
    r = analyze({"Data": [["Customer"], ["C-1"]]}, fields="customer")
    payload = r.as_dict()
    assert payload["verdict"] == "ready"
    assert payload["fitness"]["coverage_ratio"] == 1.0
    assert isinstance(payload["summary"], str)


def test_a_single_column_sheet_is_valid():
    """Regression: a one-column list — material numbers, cost centres — is a normal attachment.

    An earlier header detector required at least two columns and made every such file 'unusable'.
    """
    r = analyze({"Data": [["Material"], ["M-1"], ["M-2"], ["M-3"]]}, fields="material")
    assert r.verdict == "ready"
    assert r.sheets[0].headers == ["Material"]
    assert r.sheets[0].data_rows == 3
    assert r.fitness.verdict == "ready"


def test_a_lone_title_with_no_data_beneath_is_not_treated_as_a_header():
    r = analyze({"Data": [["Monthly Report"]]})
    assert "header_not_found" in codes(r) or "workbook_empty" in codes(r)


def test_a_wide_text_data_row_does_not_win_over_a_narrower_real_header():
    """Regression: a header with an empty cell has fewer populated cells than its data rows.

    Scoring on width alone picked a data row as the header, which silently dropped the rows above it
    and renamed every column after a value.
    """
    r = analyze({"Sheet1": [
        ["Open Purchase Orders - Q3"],
        ["Extracted 14 Aug"],
        [],
        ["PO Number", "", "Vendor", "Amount", "Currency"],
        [("text", "4500012345"), "x", "V-100", 100, "EUR"],
        [("text", "4500012346"), "x", "V-101", 200, "EUR"],
        [("text", "4500012347"), "x", "V-102", 300, "EUR"],
    ]})
    assert r.sheets[0].header_row == 4
    assert r.sheets[0].data_rows == 3
    assert "PO Number" in r.sheets[0].headers
    assert "V-100" not in r.sheets[0].headers


def test_two_title_rows_tied_with_two_data_rows_still_finds_the_header():
    """Regression from a live-server run: a width-vote TIE (two narrow title rows vs two wide
    data rows) picked the title as the header. Ties must break toward the wider shape."""
    r = analyze({"Sheet1": [
        ["Open Purchase Orders - Q3"],
        ["Extracted 14 Aug"],
        [],
        ["PO Number", "", "Vendor", "Amount", "Currency"],
        [("text", "4500012345"), "x", "V-100", 100, "EUR"],
        [("text", "4500012346"), "x", "V-101", 200, "EUR"],
    ]})
    assert r.sheets[0].header_row == 4
    assert r.sheets[0].data_rows == 2
    assert "PO Number" in r.sheets[0].headers
