"""Does this spreadsheet actually carry what the requirement asked for?

Structural validity and fitness are different questions. A workbook can be perfectly formed and still
be the wrong file — the right shape, the wrong quarter, or missing the one column the whole request
turns on. Answering only the first question is how a clean-looking attachment still costs a round trip.

So this module compares the columns that are present against the fields the requester themselves named
in the requirement (the `data_fields` slot, and the request's own slot schema), and reports coverage
rather than guessing intent.

Matching is deterministic — normalised names, known synonyms, and containment — for three reasons: it
is reproducible for the same inputs, it is testable without a model, and a wrong automated guess about
which column means what is more expensive than saying "we could not tell". Where nothing matches, the
column is reported as unmapped rather than forced into a slot.

No limits here either: any number of columns, any number of requested fields, any name length.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from .inspect import Finding, SheetReport

__all__ = [
    "FieldCoverage",
    "FitnessReport",
    "assess_fitness",
    "normalize_name",
]

_SEPARATORS = re.compile(r"[\s_\-./\\]+")
_NON_WORD = re.compile(r"[^a-z0-9]+")

# Everyday spreadsheet naming, so "Cust #" and "customer_number" are recognised as the same ask.
_SYNONYMS: dict[str, str] = {
    "no": "number", "num": "number", "nbr": "number", "#": "number", "id": "number",
    "qty": "quantity", "amt": "amount", "val": "value", "cust": "customer",
    "mat": "material", "matl": "material", "desc": "description", "dt": "date",
    "org": "organisation", "org.": "organisation", "co": "company", "cc": "costcenter",
    "costcentre": "costcenter", "plnt": "plant", "vend": "vendor", "supp": "supplier",
    "curr": "currency", "uom": "unit", "fy": "fiscalyear", "yr": "year", "mth": "month",
    "po": "purchaseorder", "so": "salesorder", "gl": "generalledger", "wbs": "workbreakdown",
}


def normalize_name(name: str) -> str:
    """Fold a human column name to a comparable key. 'Cust #' and 'customer_number' converge."""
    lowered = name.strip().casefold()
    parts = [p for p in _SEPARATORS.split(lowered) if p]
    expanded = [_SYNONYMS.get(_NON_WORD.sub("", p) or p, _NON_WORD.sub("", p) or p) for p in parts]
    return "".join(expanded)


def _requested_fields(
    slots: Mapping[str, Any] | None, schema_required: Sequence[str] | None
) -> list[str]:
    """What did the requester actually name? Free text, a list, or nothing at all."""
    named: list[str] = []
    if slots:
        raw = slots.get("data_fields")
        value = getattr(raw, "value", raw)
        if isinstance(value, str):
            named.extend(p.strip() for p in re.split(r"[,;\n]+", value) if p.strip())
        elif isinstance(value, (list, tuple)):
            named.extend(str(v).strip() for v in value if str(v).strip())
    seen: set[str] = set()
    ordered: list[str] = []
    for item in named:
        key = normalize_name(item)
        if key and key not in seen:
            seen.add(key)
            ordered.append(item)
    return ordered


@dataclass
class FieldCoverage:
    requested: str
    matched_column: str | None = None
    matched_sheet: str | None = None
    match_kind: str | None = None      # exact | normalised | contained
    populated: int = 0
    blank_rows: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class FitnessReport:
    verdict: str                        # ready | needs_fixes | unusable | not_assessable
    requested_fields: list[str]
    covered: list[FieldCoverage]
    missing: list[FieldCoverage]
    unmapped_columns: list[str]
    findings: list[Finding] = field(default_factory=list)

    @property
    def coverage_ratio(self) -> float:
        total = len(self.covered) + len(self.missing)
        return (len(self.covered) / total) if total else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "requested_fields": self.requested_fields,
            "coverage_ratio": round(self.coverage_ratio, 4),
            "covered": [c.as_dict() for c in self.covered],
            "missing": [m.as_dict() for m in self.missing],
            "unmapped_columns": self.unmapped_columns,
            "findings": [f.as_dict() for f in self.findings],
        }


def _match(requested: str, index: Mapping[str, tuple[str, str, int, int]]) -> FieldCoverage:
    """Resolve one requested field against the available columns."""
    key = normalize_name(requested)
    if key in index:
        header, sheet, populated, blanks = index[key]
        kind = "exact" if header.strip().casefold() == requested.strip().casefold() else "normalised"
        return FieldCoverage(requested, header, sheet, kind, populated, blanks)
    # Containment, longest candidate first, so "customernumber" prefers a more specific column.
    for candidate in sorted(index, key=len, reverse=True):
        if len(key) >= 4 and (key in candidate or candidate in key):
            header, sheet, populated, blanks = index[candidate]
            return FieldCoverage(requested, header, sheet, "contained", populated, blanks)
    return FieldCoverage(requested)


def assess_fitness(
    reports: Sequence[SheetReport],
    *,
    slots: Mapping[str, Any] | None = None,
    required_slot_keys: Sequence[str] | None = None,
) -> FitnessReport:
    """Compare what the workbook supplies against what the requirement asked for."""
    findings: list[Finding] = []

    index: dict[str, tuple[str, str, int, int]] = {}
    all_headers: list[str] = []
    for report in reports:
        if not report.data_rows:
            continue
        for profile in report.columns:
            if not profile.header:
                continue
            all_headers.append(profile.header)
            key = normalize_name(profile.header)
            if not key or key in index:
                continue
            blanks = max(0, report.data_rows - profile.populated)
            index[key] = (profile.header, report.name, profile.populated, blanks)

    requested = _requested_fields(slots, required_slot_keys)

    if not requested:
        if all_headers:
            findings.append(Finding(
                code="no_requested_fields_to_check", severity="info",
                message="The requirement does not yet name the fields it needs, so the columns "
                        "could only be checked for structure, not for fit.",
                fix="Answer 'which fields or columns matter most?' and the attachment will be "
                    "re-checked against it.",
            ))
        return FitnessReport("not_assessable", [], [], [], sorted(set(all_headers)), findings)

    covered: list[FieldCoverage] = []
    missing: list[FieldCoverage] = []
    matched_keys: set[str] = set()
    for name in requested:
        result = _match(name, index)
        if result.matched_column:
            covered.append(result)
            matched_keys.add(normalize_name(result.matched_column))
            if result.blank_rows:
                findings.append(Finding(
                    code="requested_field_partially_blank", severity="warning",
                    sheet=result.matched_sheet, column=result.matched_column,
                    count=result.blank_rows,
                    message=f"'{result.matched_column}' was asked for but is blank on "
                            f"{result.blank_rows} row(s).",
                    fix="Fill the gaps, or say explicitly that blanks are expected.",
                ))
            if result.match_kind == "contained":
                findings.append(Finding(
                    code="field_matched_loosely", severity="info",
                    sheet=result.matched_sheet, column=result.matched_column,
                    message=f"Requested '{result.requested}' was matched to column "
                            f"'{result.matched_column}' by similarity, not by an exact name.",
                    fix="Confirm this is the right column, or rename it to match.",
                ))
        else:
            missing.append(result)
            findings.append(Finding(
                code="requested_field_missing", severity="blocking",
                message=f"The requirement asks for '{result.requested}', but no column with that "
                        "name is present.",
                fix=f"Add a '{result.requested}' column, or tell us which existing column holds it.",
            ))

    unmapped = sorted({h for h in all_headers if normalize_name(h) not in matched_keys})
    if unmapped and covered:
        findings.append(Finding(
            code="columns_not_requested", severity="info", count=len(unmapped),
            message=f"{len(unmapped)} column(s) are present that the requirement did not ask for: "
                    + ", ".join(f"'{u}'" for u in unmapped[:8])
                    + ("…" if len(unmapped) > 8 else ""),
            fix="Harmless if intentional — worth confirming none of them is sensitive.",
        ))

    if missing and not covered:
        verdict = "unusable"
    elif missing:
        verdict = "needs_fixes"
    else:
        verdict = "ready"
    return FitnessReport(verdict, requested, covered, missing, unmapped, findings)
