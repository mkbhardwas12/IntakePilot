"""Attachment validation for IntakePilot.

A business user attaches a spreadsheet; this tells them — immediately, in their own words — whether it
can be used, and if not, exactly which cell to fix. The delay being removed is the multi-day round trip
that happens when a malformed file is only discovered downstream.

Two questions are answered separately, because they fail independently:

* **Is the file well formed?** (`inspect`) — headers, types, formula errors, hidden tabs.
* **Does it carry what this requirement asked for?** (`fitness`) — coverage of the fields the requester
  themselves named.

Standard library only, streaming throughout. No cap on file size, sheet count, row count, column count,
or the character length of any cell.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .fitness import FieldCoverage, FitnessReport, assess_fitness, normalize_name
from .inspect import Finding, SheetReport, inspect_sheet, inspect_workbook
from .xlsx import Cell, Sheet, Workbook, XlsxError, column_label, open_workbook

__all__ = [
    "AttachmentReport",
    "Cell",
    "FieldCoverage",
    "Finding",
    "FitnessReport",
    "Sheet",
    "SheetReport",
    "Workbook",
    "XlsxError",
    "analyze_attachment",
    "assess_fitness",
    "column_label",
    "inspect_sheet",
    "inspect_workbook",
    "normalize_name",
    "open_workbook",
]

_ORDER = {"blocking": 0, "warning": 1, "info": 2}


@dataclass
class AttachmentReport:
    """Everything known about one attached workbook."""

    filename: str
    verdict: str                       # ready | needs_fixes | unusable | unreadable
    sheets: list[SheetReport] = field(default_factory=list)
    fitness: FitnessReport | None = None
    findings: list[Finding] = field(default_factory=list)

    @property
    def blocking(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "blocking"]

    def summary(self) -> str:
        """A short message for the requester. This is what removes the round trip."""
        if self.verdict == "unreadable":
            return self.findings[0].message if self.findings else "The file could not be read."
        blocking = self.blocking
        warnings = [f for f in self.findings if f.severity == "warning"]
        rows = sum(s.data_rows for s in self.sheets)
        head = (f"{self.filename}: {rows:,} data row(s) across "
                f"{len([s for s in self.sheets if s.data_rows])} sheet(s).")
        if blocking:
            return (f"{head} {len(blocking)} issue(s) must be fixed before this can be used — "
                    f"starting with: {blocking[0].message} {blocking[0].fix}")
        if warnings:
            return (f"{head} Usable, with {len(warnings)} thing(s) worth correcting — "
                    f"first: {warnings[0].message} {warnings[0].fix}")
        return f"{head} No problems found."

    def as_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "verdict": self.verdict,
            "summary": self.summary(),
            "sheets": [s.as_dict() for s in self.sheets],
            "fitness": self.fitness.as_dict() if self.fitness else None,
            "findings": [f.as_dict() for f in self.findings],
        }


def analyze_attachment(
    source: Any,
    *,
    filename: str = "attachment.xlsx",
    slots: Mapping[str, Any] | None = None,
    required_slot_keys: Sequence[str] | None = None,
) -> AttachmentReport:
    """Validate a spreadsheet and assess it against what the requirement asked for.

    ``source`` may be a path, a file object, or bytes. Nothing is written to disk and nothing is
    truncated. An unreadable file returns a report rather than raising, so the caller always has
    something to show the user.
    """
    try:
        book = open_workbook(source)
    except XlsxError as exc:
        return AttachmentReport(
            filename=filename, verdict="unreadable",
            findings=[Finding(code="file_unreadable", severity="blocking",
                              message=str(exc),
                              fix="Re-save the file from Excel as 'Excel Workbook (.xlsx)' and "
                                  "attach it again.")],
        )

    with book:
        sheets = inspect_workbook(book)
        fitness = assess_fitness(sheets, slots=slots, required_slot_keys=required_slot_keys)

    findings: list[Finding] = []
    for report in sheets:
        findings.extend(report.findings)
    findings.extend(fitness.findings)
    findings.sort(key=lambda f: (_ORDER.get(f.severity, 3), f.code))

    if any(f.severity == "blocking" for f in findings):
        verdict = "unusable"
    elif any(f.severity == "warning" for f in findings):
        verdict = "needs_fixes"
    else:
        verdict = "ready"

    return AttachmentReport(filename=filename, verdict=verdict, sheets=sheets,
                            fitness=fitness, findings=findings)
