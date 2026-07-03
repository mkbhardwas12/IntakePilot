"""Section 11 — the non-negotiable invariants, encoded as tests."""
from __future__ import annotations

import json

import pytest

from core.models import (Budget, ExtractionError, Provenance,
                         RequirementObject, Slot)
from core.providers.llm.base import LLMResult, Msg, complete_validated
from core.providers.llm.mock import MockLLM
from core.providers.store.base import AppendOnlyViolation
from core.providers.store.sqlite import SqliteStore
from core.providers.vector.local import LocalVectorIndex
from core.agents import intake
from core.agents.orchestrator import Orchestrator

from tests.conftest import make_obj, many_askable_schema, seed


class RogueLLM(MockLLM):
    """Model that tries to exceed the budget and ask unaskable slots."""

    async def complete(self, messages: list[Msg], **kw) -> LLMResult:
        system = next((m.content for m in messages if m.role == "system"), "")
        if "TASK: question" in system:
            questions = [{"slot_key": f"slot_{i}",
                          "text": f"Rogue question {i}?", "because": "because"}
                         for i in range(10)]
            questions.append({"slot_key": "affected_systems",
                              "text": "Which database engine?", "because": "rogue"})
            return LLMResult(text=json.dumps({"questions": questions}))
        if "TASK: extract" in system:
            return LLMResult(text=json.dumps({"slots": {}}))
        return await super().complete(messages, **kw)


def make_orch(llm, schema, cfg):
    store = SqliteStore({"path": ":memory:"})
    vector = LocalVectorIndex(llm, {"path": ":memory:"})
    return Orchestrator(llm, store, vector, schema, cfg), store


async def test_budget_enforced_per_turn_and_total(cfg):
    """Max 3 questions/turn and 7 total, even against a model returning 11."""
    schema = many_askable_schema(10)
    orch, store = make_orch(RogueLLM(), schema, cfg)
    obj = make_obj(budget=Budget(max=7, per_turn=3))
    session = await seed(store, obj)

    total = 0
    for turn in range(5):
        result = await orch.handle_turn(session, f"message {turn}", [])
        assert len(result.questions) <= 3
        total += len(result.questions)
        assert result.draft.question_budget.spent == total
        session["pending_questions"] = []  # user ignores; ask again
    assert total <= 7
    assert (await store.latest(obj.req_id)).question_budget.spent <= 7


async def test_askable_false_never_reaches_composer(orchestrator, store, schema):
    """askable:false slots can never be asked — even when the model tries."""
    orch, store = make_orch(RogueLLM(), schema, orchestrator.cfg)
    obj = make_obj(ask="something entirely unmappable qzx")
    session = await seed(store, obj)
    result = await orch.handle_turn(session, "something entirely unmappable qzx", [])
    unaskable = set(schema.unaskable_keys())
    assert unaskable, "schema must contain askable:false slots"
    for q in result.questions:
        assert q.slot_key not in unaskable


async def test_ask_verbatim_immutable(orchestrator, store, vector):
    obj = make_obj(ask="our monthly vendor report takes 3 days to compile by hand")
    session = await seed(store, obj)
    await orchestrator.handle_turn(session, "actually ignore that, new ask!", [])
    latest = await store.latest(obj.req_id)
    assert latest.ask_verbatim == "our monthly vendor report takes 3 days to compile by hand"


async def test_answered_and_edited_never_overwritten():
    obj = make_obj()
    obj.slots["urgency"] = Slot(value="this week", provenance=Provenance.ANSWERED,
                                confidence=0.95)
    obj.slots["business_outcome"] = Slot(value="human-edited outcome",
                                         provenance=Provenance.EDITED, confidence=1.0)
    extraction = {"urgency": {"value": "no hard deadline", "confidence": 0.99},
                  "business_outcome": {"value": "model outcome", "confidence": 0.99}}
    merged = intake.merge_slots(obj, extraction)
    assert merged.slots["urgency"].value == "this week"
    assert merged.slots["urgency"].provenance == Provenance.ANSWERED
    assert merged.slots["business_outcome"].value == "human-edited outcome"
    assert merged.slots["business_outcome"].provenance == Provenance.EDITED


async def test_store_append_only(store):
    obj = make_obj()
    await store.put_version(obj)
    with pytest.raises(AppendOnlyViolation):
        await store.put_version(obj)  # same (req_id, version)
    obj2 = obj.model_copy(deep=True)
    obj2.version = 2
    obj2.readiness_score = 50
    await store.put_version(obj2)
    latest = await store.latest(obj.req_id)
    assert latest.version == 2 and latest.readiness_score == 50
    history = await store.history(obj.req_id)
    assert [o.version for o in history] == [1, 2]


class BrokenLLM(MockLLM):
    async def complete(self, messages, **kw):
        return LLMResult(text="NOT JSON {{{")


async def test_validation_wrapper_retries_then_raises():
    llm = BrokenLLM()
    calls = 0
    original = llm.complete

    async def counting(messages, **kw):
        nonlocal calls
        calls += 1
        return await original(messages, **kw)
    llm.complete = counting

    with pytest.raises(ExtractionError):
        await complete_validated(llm, [Msg(role="user", content="x")],
                                 {"type": "object", "required": ["slots"]})
    assert calls == 2  # exactly one retry with the error appended


async def test_orchestrator_degrades_gracefully_on_extraction_error(cfg, schema):
    orch, store = make_orch(BrokenLLM(), schema, cfg)
    obj = make_obj()
    obj.slots["urgency"] = Slot(value="this week", provenance=Provenance.ANSWERED,
                                confidence=0.95)
    session = await seed(store, obj)
    result = await orch.handle_turn(session, "some new message", [])
    assert result.degraded is True
    assert result.draft.slots["urgency"].value == "this week"  # prior slots kept
    assert result.draft.question_budget.spent == 0             # no budget burned
    assert result.questions == []


async def test_no_provider_sdk_imports_outside_providers():
    """Spec Section 11: provider SDK imports outside core/providers/ fail CI."""
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / "core"
    banned = re.compile(r"^\s*(import|from)\s+(asyncpg|boto3|openai|ollama|psycopg)\b", re.M)
    offenders = []
    for path in root.rglob("*.py"):
        if "providers" in path.parts:
            continue
        if banned.search(path.read_text()):
            offenders.append(str(path))
    assert not offenders, f"provider SDK imports outside core/providers/: {offenders}"
