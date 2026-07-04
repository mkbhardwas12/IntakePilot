"""Mid-session revision + capability-failure intake — the transcript fixes.

Covers: (1) 'after the changes I am not able to X' classifies as bug_report
and the mock extractor fills the problem slots instead of asking generic
questions; (2) Shadow Draft revisions apply with EDITED provenance, feed
learning only when they correct a machine-filled slot, and never disturb
pending questions.
"""
from __future__ import annotations

import pytest

from core.models import Provenance, Slot
from core.providers.llm.mock import _extract_slots
from core.agents.request_type import classify_request_type

from tests.conftest import make_obj, seed

ASK = ("Can you check after last week of changes i am not able to extract "
       "VVIN info for similar product that has been used for Lexus TX and "
       "Toyota Highlander")


def test_capability_failure_classifies_as_bug_report():
    assert classify_request_type(ASK) == "bug_report"
    assert classify_request_type("we can't generate the invoice export anymore") == "bug_report"
    assert classify_request_type("the sync no longer works after the upgrade") == "bug_report"
    # plain data asks are unaffected
    assert classify_request_type(
        "we need a dashboard that shows open invoices by region") == "data_request"


def test_mock_extracts_problem_statement():
    slots = _extract_slots(ASK)["slots"]
    assert slots["business_outcome"]["value"].startswith("Restore ability to extract vvin info")
    assert "current_behavior" in slots
    assert slots["expected_behavior"]["value"].startswith("Able to extract vvin info")


@pytest.mark.asyncio
async def test_revision_applies_with_edited_provenance_and_learns(orchestrator, store):
    obj = make_obj(ask="vendor report ask")
    obj.slots["business_outcome"] = Slot(value="wrong summary",
                                         provenance=Provenance.EXTRACTED,
                                         confidence=0.6, source="user_text")
    session = await seed(store, obj)

    result = await orchestrator.handle_turn(
        session, "", revisions={"business_outcome": "right summary"})

    assert result.revised == 1
    slot = result.draft.slots["business_outcome"]
    assert slot.provenance == Provenance.EDITED
    assert slot.value == "right summary"
    # correcting a machine-filled slot is a learning signal
    edits = await store.query_ledger("edit_diffs")
    assert len(edits) == 1 and edits[0]["proposed"] == "wrong summary"
    assert any(e.event == "slot_revised" for e in result.draft.audit)


@pytest.mark.asyncio
async def test_revising_own_answer_does_not_pollute_learning(orchestrator, store):
    obj = make_obj()
    obj.slots["urgency"] = Slot(value="this month", provenance=Provenance.ANSWERED,
                                confidence=0.95, source="q1")
    session = await seed(store, obj)

    result = await orchestrator.handle_turn(
        session, "", revisions={"urgency": "this week"})

    assert result.draft.slots["urgency"].value == "this week"
    assert result.draft.slots["urgency"].provenance == Provenance.EDITED
    # the human changed their mind — that is not a model correction
    assert await store.query_ledger("edit_diffs") == []


@pytest.mark.asyncio
async def test_revision_only_turn_leaves_pending_questions_alone(orchestrator, store):
    obj = make_obj()
    obj.slots["business_outcome"] = Slot(value="old", provenance=Provenance.EXTRACTED,
                                         confidence=0.6)
    session = await seed(store, obj)
    session["pending_questions"] = [
        {"id": "q1", "slot_key": "urgency", "text": "How soon?"}]
    await store.put_session(session)

    result = await orchestrator.handle_turn(
        session, "", revisions={"business_outcome": "new"})

    # no new questions composed, pending set preserved, nothing logged skipped
    assert result.questions == []
    stored = await store.get_session(session["session_id"])
    assert [q["id"] for q in stored["pending_questions"]] == ["q1"]
    assert await store.query_ledger("question_ledger") == []
    # budget untouched by a revision
    assert result.draft.question_budget.spent == 0


@pytest.mark.asyncio
async def test_extraction_never_overwrites_a_revision(orchestrator, store):
    obj = make_obj()
    obj.slots["business_outcome"] = Slot(value="human truth",
                                         provenance=Provenance.EDITED,
                                         confidence=1.0, source="mid_session_revision")
    session = await seed(store, obj)

    # a message that would normally extract business_outcome
    result = await orchestrator.handle_turn(
        session, "we need to automate the monthly vendor report because it is manual")

    assert result.draft.slots["business_outcome"].value == "human truth"


@pytest.mark.asyncio
async def test_list_revision_restores_type(orchestrator, store):
    obj = make_obj()
    obj.slots["affected_systems"] = Slot(value=["SAP"], provenance=Provenance.RETRIEVED,
                                         confidence=0.7)
    session = await seed(store, obj)

    result = await orchestrator.handle_turn(
        session, "", revisions={"affected_systems": "SAP, Tableau"})

    assert result.draft.slots["affected_systems"].value == ["SAP", "Tableau"]
