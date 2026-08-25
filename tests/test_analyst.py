"""The Analyst — process placement, the live unstated-needs checklist, and
the interpretation's degradation path.

Placement is deterministic by design (a model never decides which business
process an ask belongs to), so these tests are exact.
"""
from __future__ import annotations

import pytest

from core.agents import analyst
from core.agents.orchestrator import Orchestrator
from core.config import load_slot_schema
from core.models import ExtractionError, Provenance, Slot

from tests.conftest import make_obj


# ------------------------------------------------------------------ placement

def test_vendor_spend_is_placed_in_procure_to_pay():
    m = analyst.classify_process(
        "our monthly vendor spend report takes 3 days to compile by hand")
    assert m is not None and m.key == "procure_to_pay"
    assert "vendor" in m.evidence and "spend" in m.evidence
    assert 0 < m.confidence <= 0.9


def test_customer_orders_are_placed_in_order_to_cash():
    m = analyst.classify_process(
        "I need a report of goods details for product line X with the order info")
    assert m is not None and m.key == "order_to_cash"


def test_month_end_close_is_placed_in_record_to_report():
    m = analyst.classify_process(
        "the month-end reconciliation of journals to the general ledger is late")
    assert m is not None and m.key == "record_to_report"


def test_an_unplaceable_ask_returns_none():
    assert analyst.classify_process("we would like an improvement") is None


def test_more_votes_beat_fewer():
    """'vendor' alone votes P2P, but the O2C evidence outweighs it."""
    m = analyst.classify_process(
        "customer orders and billing for deliveries, plus one vendor field")
    assert m is not None and m.key == "order_to_cash"


# ------------------------------------------------------------------ the read

@pytest.fixture
def schema():
    return load_slot_schema(request_type="data_request")


async def test_read_places_interprets_and_lists_needs(llm, schema):
    obj = make_obj(ask="our monthly vendor spend report takes 3 days to compile by hand")
    read = await analyst.read(llm, obj, schema)
    assert read.process is not None and read.process.key == "procure_to_pay"
    assert read.interpretation_source == "llm"
    assert "Procure-to-Pay" in read.interpretation
    assert any(n.need == "Refresh cadence" for n in read.unstated_needs)
    assert read.risks and read.kpis


async def test_read_is_deterministic(llm, schema):
    obj = make_obj(ask="our monthly vendor spend report takes 3 days to compile by hand")
    assert (await analyst.read(llm, obj, schema)) == (await analyst.read(llm, obj, schema))


async def test_needs_flip_to_covered_as_slots_fill(llm, schema):
    obj = make_obj(ask="our monthly vendor spend report takes 3 days to compile by hand")
    before = await analyst.read(llm, obj, schema)
    cadence = next(n for n in before.unstated_needs if n.need == "Refresh cadence")
    assert cadence.status == "open"

    obj.slots["refresh_frequency"] = Slot(
        value="monthly", provenance=Provenance.ANSWERED, confidence=0.95)
    after = await analyst.read(llm, obj, schema)
    cadence = next(n for n in after.unstated_needs if n.need == "Refresh cadence")
    assert cadence.status == "covered" and cadence.covered_by == "refresh_frequency"


async def test_needs_outside_the_schema_fork_are_dropped(llm):
    """current_behavior only exists on the bug_report fork; on default the
    issue-to-resolution 'Reproduction path' need must not dangle open forever
    on a slot the schema cannot fill... unless another covering slot exists."""
    obj = make_obj(ask="the invoice job fails with an error every night")
    read = await analyst.read(llm, obj, load_slot_schema())
    assert read.process is not None and read.process.key == "issue_to_resolution"
    repro = [n for n in read.unstated_needs if n.need == "Reproduction path and blast radius"]
    # scope_boundaries exists on default, so the need survives via that key.
    assert repro and repro[0].status == "open"


async def test_unplaced_ask_gets_the_general_checklist(llm, schema):
    obj = make_obj(ask="we would like an improvement please")
    read = await analyst.read(llm, obj, schema)
    assert read.process is None
    assert any(n.need == "An accountable owner on the business side"
               for n in read.unstated_needs)


async def test_model_failure_degrades_to_deterministic_restatement(schema):
    class BrokenLLM:
        async def complete(self, *a, **kw):
            raise ExtractionError("provider down")

    obj = make_obj(ask="our monthly vendor spend report takes 3 days to compile by hand")

    async def failing(*a, **kw):
        raise ExtractionError("no model")

    import core.agents.analyst as mod
    original = mod.complete_validated
    mod.complete_validated = failing
    try:
        read = await analyst.read(BrokenLLM(), obj, schema)
    finally:
        mod.complete_validated = original
    assert read.interpretation_source == "deterministic"
    assert "vendor spend report" in read.interpretation
    assert read.process is not None  # placement never depends on the model


# ------------------------------------------------------------------ in the turn loop

async def test_turn_produces_and_streams_the_analyst_read(orchestrator, store):
    obj = make_obj(ask="")
    obj.ask_verbatim = "our monthly vendor spend report takes 3 days to compile by hand"
    await store.put_version(obj)
    session = {"session_id": "s1", "req_id": obj.req_id, "turns": [],
               "pending_questions": []}
    await store.put_session(session)

    events: list[tuple[str, dict]] = []

    async def emit(event, data):
        events.append((event, data))

    result = await orchestrator.handle_turn(
        session, obj.ask_verbatim, emit=emit)

    read = result.draft.analyst
    assert read is not None and read.process.key == "procure_to_pay"
    assert result.draft.analyst.interpretation
    analyst_events = [d for e, d in events if e == "analyst"]
    assert len(analyst_events) == 1
    assert analyst_events[0]["process"]["key"] == "procure_to_pay"

    stored = await store.latest(obj.req_id)
    assert stored.analyst is not None  # persisted with the version


async def test_revision_only_turn_does_not_recompute_the_read(orchestrator, store):
    obj = make_obj(ask="")
    obj.ask_verbatim = "our monthly vendor spend report takes 3 days to compile by hand"
    await store.put_version(obj)
    session = {"session_id": "s2", "req_id": obj.req_id, "turns": [],
               "pending_questions": []}
    await store.put_session(session)
    await orchestrator.handle_turn(session, obj.ask_verbatim)

    events: list[str] = []

    async def emit(event, data):
        events.append(event)

    await orchestrator.handle_turn(
        session, "", revisions={"urgency": "this month"}, emit=emit)
    assert "analyst" not in events
