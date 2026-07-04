"""Routing must actually use the vector index: similar past ROUTED tickets
pull new requirements toward their queue — the classifier improves with use
instead of being a static keyword list."""
from __future__ import annotations

from core.gates.routing import classify
from core.models import Budget, RequirementObject, Requester, Status
from core.agents.precedent import index_requirement
from core.providers.llm.mock import MockLLM
from core.providers.vector.local import LocalVectorIndex

QUEUES = [
    {"name": "data-platform", "keywords": ["report", "dashboard"]},
    {"name": "integrations", "keywords": ["api", "webhook"]},
]


def _obj(req_id: str, ask: str, status: Status = Status.CONFIRMED) -> RequirementObject:
    o = RequirementObject(req_id=req_id, requester=Requester(), ask_verbatim=ask,
                          question_budget=Budget(max=7, per_turn=3))
    o.status = status
    return o


def _vector():
    return LocalVectorIndex(MockLLM({"dim": 64}), {"path": ":memory:"})


async def test_precedent_routes_when_keywords_are_silent():
    vec = _vector()
    ask = "consolidate supplier spend numbers for the quarterly pack"
    routed = _obj("IPR-1", ask, Status.ROUTED)
    await index_requirement(vec, routed, queue="data-platform")

    decision = await classify(_obj("IPR-2", ask), QUEUES, vec)
    assert decision.queue == "data-platform"
    assert decision.confidence > 0
    assert "similar past ticket" in decision.explanation


async def test_unrouted_history_contributes_nothing():
    vec = _vector()
    ask = "consolidate supplier spend numbers for the quarterly pack"
    await index_requirement(vec, _obj("IPR-1", ask))  # draft: no queue meta
    decision = await classify(_obj("IPR-2", ask), QUEUES, vec)
    assert decision.queue == "triage"  # no keywords, no ROUTED precedent


async def test_own_requirement_excluded_from_precedent():
    vec = _vector()
    ask = "consolidate supplier spend numbers for the quarterly pack"
    await index_requirement(vec, _obj("IPR-1", ask, Status.ROUTED), queue="integrations")
    decision = await classify(_obj("IPR-1", ask), QUEUES, vec)
    assert decision.queue == "triage"


async def test_keywords_still_work_without_vector():
    decision = await classify(_obj("IPR-1", "need a report of vendor data"), QUEUES, None)
    assert decision.queue == "data-platform"
    assert "Matched" in decision.explanation