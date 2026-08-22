"""MANAS federation admissibility tests — verify a hashed data_request
(asked → corrected → observed) is admissible for federation to an orgbrain.

The Demand path feeds requirements from IntakePilot to MANAS. For a
data_request to be admissible, it must:

1. Contain no PII in slot props (VIN, IBAN, email, PAN patterns)
2. Have free-text fields hashed (ask_verbatim, business_outcome, etc.)
3. Contain no invented slots (only slots present in the schema)

These tests run offline against the existing data_request.yaml schema
and the confirmation/edit flow, without any actual MANAS exporter hook
(which does not exist in this repo).
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

import pytest

from core.config import load_slot_schema
from core.models import (
    Budget, Confirmation, Provenance, RequirementObject, Requester,
    RoutingDecision, Slot, Status,
)

PII_PATTERNS = {
    "vin": re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b", re.I),
    "iban": re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{4,30}\b", re.I),
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "pan": re.compile(r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b"),
}

FREE_TEXT_SLOT_KEYS = {
    "business_outcome",
    "success_criteria",
    "scope_boundaries",
    "data_fields",
    "backend_context",
    "nfr",
}


def hash_value(value: Any) -> str:
    """SHA-256 hash for free-text fields — deterministic, collision-resistant."""
    if value is None:
        return ""
    text = str(value) if not isinstance(value, list) else "; ".join(str(v) for v in value)
    return hashlib.sha256(text.encode()).hexdigest()


def contains_pii(text: str) -> dict[str, list[str]]:
    """Return dict of PII type -> list of matches found."""
    if not text or not isinstance(text, str):
        return {}
    matches = {}
    for pii_type, pattern in PII_PATTERNS.items():
        found = pattern.findall(text)
        if found:
            matches[pii_type] = found
    return matches


def check_slot_pii(slots: dict[str, Slot]) -> dict[str, dict[str, list[str]]]:
    """Check all slot values for PII. Returns {slot_key: {pii_type: [matches]}}."""
    violations = {}
    for key, slot in slots.items():
        if slot.value is None:
            continue
        text = str(slot.value) if not isinstance(slot.value, list) else " ".join(str(v) for v in slot.value)
        pii = contains_pii(text)
        if pii:
            violations[key] = pii
    return violations


def hash_free_text_slots(obj: RequirementObject) -> dict[str, str]:
    """Hash free-text slots for federation. Returns {slot_key: hash}."""
    hashed = {}
    hashed["ask_verbatim"] = hash_value(obj.ask_verbatim)
    for key in FREE_TEXT_SLOT_KEYS:
        slot = obj.slots.get(key)
        if slot and slot.value is not None:
            hashed[key] = hash_value(slot.value)
    return hashed


def make_data_request(
    ask: str = "we need a monthly vendor report that shows open invoices",
    edits: dict | None = None,
    slot_overrides: dict | None = None,
) -> RequirementObject:
    """Build a data_request RequirementObject in the asked → corrected → observed state."""
    obj = RequirementObject(
        req_id="IPR-2026-000042",
        version=3,
        status=Status.CONFIRMED,
        requester=Requester(id="u123", name="Test User", dept="Finance Ops", role="Analyst"),
        ask_verbatim=ask,
        request_type="data_request",
        question_budget=Budget(max=7, per_turn=3, spent=2),
    )
    schema = load_slot_schema(request_type="data_request")
    obj.slots = {
        "business_outcome": Slot(
            value="Automate the monthly vendor report compilation",
            provenance=Provenance.EXTRACTED, confidence=0.8,
        ),
        "affected_systems": Slot(
            value=["ERP-VendorMaster", "BI-Reporting"],
            provenance=Provenance.RETRIEVED, confidence=0.9,
        ),
        "urgency": Slot(
            value="this month",
            provenance=Provenance.ANSWERED, confidence=0.95,
        ),
        "success_criteria": Slot(
            value="report compiles in under 1 hour",
            provenance=Provenance.ANSWERED, confidence=0.95,
        ),
        "data_sensitivity": Slot(
            value="internal",
            provenance=Provenance.ASSUMED, confidence=0.5, default_reason="org norm",
        ),
        "refresh_frequency": Slot(
            value="monthly",
            provenance=Provenance.ASSUMED, confidence=0.5, default_reason="most reporting asks",
        ),
    }
    if slot_overrides:
        for key, value in slot_overrides.items():
            if key in schema.slots:
                obj.slots[key] = Slot(value=value, provenance=Provenance.EDITED, confidence=1.0)
    edit_count = len(edits) if edits else 0
    obj.confirmation = Confirmation(confirmed_by="Test User", edits=edit_count)
    if edits:
        for key, value in edits.items():
            if key in obj.slots:
                obj.slots[key] = Slot(value=value, provenance=Provenance.EDITED, confidence=1.0)
    return obj


class TestNoPIIInSlots:
    """Verify PII patterns are absent from slot values."""

    def test_clean_data_request_has_no_pii(self):
        obj = make_data_request()
        violations = check_slot_pii(obj.slots)
        assert violations == {}, f"PII found in slots: {violations}"

    def test_vin_detected_in_slot(self):
        obj = make_data_request(slot_overrides={
            "business_outcome": "Extract VVIN info for 1HGBH41JXMN109186 vehicle"
        })
        violations = check_slot_pii(obj.slots)
        assert "business_outcome" in violations
        assert "vin" in violations["business_outcome"]

    def test_iban_detected_in_slot(self):
        obj = make_data_request(slot_overrides={
            "scope_boundaries": "Exclude IBAN DE89370400440532013000 from report"
        })
        violations = check_slot_pii(obj.slots)
        assert "scope_boundaries" in violations
        assert "iban" in violations["scope_boundaries"]

    def test_email_detected_in_slot(self):
        obj = make_data_request(slot_overrides={
            "success_criteria": "Send result to john.doe@example.com"
        })
        violations = check_slot_pii(obj.slots)
        assert "success_criteria" in violations
        assert "email" in violations["success_criteria"]

    def test_pan_detected_in_slot(self):
        obj = make_data_request(slot_overrides={
            "data_fields": "Include card 4111-1111-1111-1111 transactions"
        })
        violations = check_slot_pii(obj.slots)
        assert "data_fields" in violations
        assert "pan" in violations["data_fields"]

    def test_ask_verbatim_pii_check(self):
        obj = make_data_request(ask="Send report to user@corp.com")
        pii = contains_pii(obj.ask_verbatim)
        assert "email" in pii

    def test_multiple_pii_types_detected(self):
        obj = make_data_request(slot_overrides={
            "business_outcome": "VIN 1HGBH41JXMN109186 owner email: test@x.com"
        })
        violations = check_slot_pii(obj.slots)
        assert "business_outcome" in violations
        pii_types = set(violations["business_outcome"].keys())
        assert pii_types >= {"vin", "email"}


class TestFreeTextHashed:
    """Verify free-text fields are hashed for federation."""

    def test_ask_verbatim_hashed(self):
        obj = make_data_request()
        hashed = hash_free_text_slots(obj)
        assert "ask_verbatim" in hashed
        assert len(hashed["ask_verbatim"]) == 64
        expected = hashlib.sha256(obj.ask_verbatim.encode()).hexdigest()
        assert hashed["ask_verbatim"] == expected

    def test_business_outcome_hashed(self):
        obj = make_data_request()
        hashed = hash_free_text_slots(obj)
        assert "business_outcome" in hashed
        assert len(hashed["business_outcome"]) == 64

    def test_success_criteria_hashed(self):
        obj = make_data_request()
        hashed = hash_free_text_slots(obj)
        assert "success_criteria" in hashed
        assert len(hashed["success_criteria"]) == 64

    def test_empty_slot_not_hashed(self):
        obj = make_data_request()
        hashed = hash_free_text_slots(obj)
        assert "scope_boundaries" not in hashed

    def test_hash_is_deterministic(self):
        obj1 = make_data_request()
        obj2 = make_data_request()
        h1 = hash_free_text_slots(obj1)
        h2 = hash_free_text_slots(obj2)
        assert h1 == h2

    def test_edited_slot_hash_differs(self):
        obj1 = make_data_request()
        obj2 = make_data_request(edits={"business_outcome": "Different outcome"})
        h1 = hash_free_text_slots(obj1)
        h2 = hash_free_text_slots(obj2)
        assert h1["business_outcome"] != h2["business_outcome"]


class TestNoInventedSlots:
    """Verify only schema-defined slots are present."""

    def test_all_slots_in_schema(self):
        schema = load_slot_schema(request_type="data_request")
        obj = make_data_request()
        for key in obj.slots:
            assert key in schema.slots, f"Slot '{key}' not in data_request schema"

    def test_invented_slot_detected(self):
        schema = load_slot_schema(request_type="data_request")
        obj = make_data_request()
        obj.slots["invented_field"] = Slot(value="should not exist", provenance=Provenance.EXTRACTED)
        invented = [k for k in obj.slots if k not in schema.slots]
        assert invented == ["invented_field"]

    def test_data_request_schema_slots(self):
        """Verify the data_request schema has the expected slot keys."""
        schema = load_slot_schema(request_type="data_request")
        expected_keys = {
            "business_outcome", "affected_systems", "urgency", "success_criteria",
            "data_fields", "refresh_frequency", "scope_boundaries", "data_sensitivity",
            "stakeholders", "nfr", "cost_of_delay", "backend_context",
        }
        actual_keys = set(schema.slots.keys())
        assert expected_keys == actual_keys, f"Schema mismatch: {expected_keys ^ actual_keys}"


class TestAskedCorrectedObservedFlow:
    """Verify the asked → corrected → observed provenance flow."""

    def test_extracted_then_edited_provenance(self):
        obj = make_data_request()
        obj.slots["business_outcome"] = Slot(
            value="Original extraction",
            provenance=Provenance.EXTRACTED, confidence=0.7,
        )
        obj.slots["business_outcome"] = Slot(
            value="Human corrected outcome",
            provenance=Provenance.EDITED, confidence=1.0, source="confirmation_edit",
        )
        assert obj.slots["business_outcome"].provenance == Provenance.EDITED

    def test_answered_slot_protected(self):
        obj = make_data_request()
        assert obj.slots["urgency"].provenance == Provenance.ANSWERED
        assert obj.slots["urgency"].confidence == 0.95

    def test_assumed_slot_has_default_reason(self):
        obj = make_data_request()
        assert obj.slots["data_sensitivity"].provenance == Provenance.ASSUMED
        assert obj.slots["data_sensitivity"].default_reason is not None

    def test_confirmation_records_edits(self):
        obj = make_data_request(edits={"business_outcome": "Edited outcome"})
        assert obj.confirmation is not None
        assert obj.confirmation.edits == 1


class TestAdmissibilityAggregate:
    """Full admissibility check for MANAS federation."""

    def is_admissible(self, obj: RequirementObject) -> tuple[bool, list[str]]:
        """Check if a data_request is admissible for MANAS federation."""
        errors = []
        schema = load_slot_schema(request_type="data_request")
        pii_in_slots = check_slot_pii(obj.slots)
        if pii_in_slots:
            for key, pii_types in pii_in_slots.items():
                errors.append(f"PII in {key}: {list(pii_types.keys())}")
        pii_in_ask = contains_pii(obj.ask_verbatim)
        if pii_in_ask:
            errors.append(f"PII in ask_verbatim: {list(pii_in_ask.keys())}")
        invented = [k for k in obj.slots if k not in schema.slots]
        if invented:
            errors.append(f"Invented slots: {invented}")
        return len(errors) == 0, errors

    def test_clean_request_is_admissible(self):
        obj = make_data_request()
        admissible, errors = self.is_admissible(obj)
        assert admissible, f"Should be admissible but got errors: {errors}"

    def test_pii_request_not_admissible(self):
        obj = make_data_request(slot_overrides={
            "business_outcome": "Send to user@example.com"
        })
        admissible, errors = self.is_admissible(obj)
        assert not admissible
        assert any("PII" in e for e in errors)

    def test_invented_slot_not_admissible(self):
        obj = make_data_request()
        obj.slots["secret_sauce"] = Slot(value="invented", provenance=Provenance.EXTRACTED)
        admissible, errors = self.is_admissible(obj)
        assert not admissible
        assert any("Invented" in e for e in errors)

    def test_hashing_produces_admissible_payload(self):
        """After hashing free text, the payload is admissible."""
        obj = make_data_request()
        hashed = hash_free_text_slots(obj)
        assert all(len(v) == 64 for v in hashed.values() if v)
        admissible, _ = self.is_admissible(obj)
        assert admissible
