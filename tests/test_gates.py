"""Gates 1 and 3 are deterministic pure functions — test them exactly."""
from __future__ import annotations

from core.models import Confirmation, Provenance, Slot
from core.gates import pipeline
from core.gates.routing import classify
from core.config import load_config

from tests.conftest import make_obj


def filled_obj():
    obj = make_obj(ask="our monthly vendor report takes 3 days to compile by hand")
    obj.slots = {
        "business_outcome": Slot(value="Automate the monthly vendor report — currently 3 days",
                                 provenance=Provenance.EXTRACTED, confidence=0.85),
        "affected_systems": Slot(value=["ERP-VendorMaster", "BI-Reporting"],
                                 provenance=Provenance.RETRIEVED, confidence=0.75),
        "urgency": Slot(value="this month", provenance=Provenance.ANSWERED, confidence=0.95),
        "success_criteria": Slot(value="report compiles in under 1 hour",
                                 provenance=Provenance.ANSWERED, confidence=0.95),
        "data_sensitivity": Slot(value="internal", provenance=Provenance.ASSUMED,
                                 confidence=0.5, default_reason="org norm"),
    }
    obj.confirmation = Confirmation(confirmed_by="Test")
    return obj


def test_gate1_passes_complete_confirmed_object(schema):
    assert pipeline.gate1_schema(filled_obj(), schema).passed


def test_gate1_fails_on_missing_required_slot(schema):
    obj = filled_obj()
    del obj.slots["urgency"]
    result = pipeline.gate1_schema(obj, schema)
    assert not result.passed and "urgency" in result.reason


def test_gate1_fails_without_confirmation_record(schema):
    """Nothing routes without a confirmation record (spec Section 11)."""
    obj = filled_obj()
    obj.confirmation = None
    result = pipeline.gate1_schema(obj, schema)
    assert not result.passed and "confirmation" in result.reason


def test_gate3_flags_weak_words_without_anchors(schema):
    obj = filled_obj()
    obj.slots["business_outcome"] = Slot(value="make reports better asap",
                                         provenance=Provenance.EXTRACTED, confidence=0.6)
    result = pipeline.gate3_ambiguity(obj, schema)
    assert not result.passed
    assert "asap" in result.reason or "better" in result.reason


def test_gate3_tolerates_weak_words_with_concrete_anchor(schema):
    obj = filled_obj()
    obj.slots["business_outcome"] = Slot(
        value="cut report time from 3 days to 1 hour, better for month-end close",
        provenance=Provenance.EXTRACTED, confidence=0.8)
    assert pipeline.gate3_ambiguity(obj, schema).passed


async def test_routing_classifier_explains_itself():
    queues = load_config().routing_queues
    decision = await classify(filled_obj(), queues)
    assert decision.queue == "data-platform"
    assert 0 < decision.confidence <= 0.99
    assert "report" in decision.explanation
    assert decision.alternatives


async def test_routing_falls_back_to_triage():
    obj = make_obj(ask="qwzx blorp")
    decision = await classify(obj, load_config().routing_queues)
    assert decision.queue == "triage" and decision.confidence == 0.0
