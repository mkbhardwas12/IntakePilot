"""Gate 4 must compare against KNOWN WORK: near-identical past requirements
fail deterministically; otherwise the rubric prompt carries real candidates."""
from __future__ import annotations

from core.config import load_slot_schema
from core.models import Budget, RequirementObject, Requester
from core.gates.pipeline import DUPLICATE_FAIL_SCORE, gate4_conflict
from core.providers.llm.mock import MockLLM
from core.providers.vector.local import LocalVectorIndex


def _obj(req_id: str, ask: str) -> RequirementObject:
    return RequirementObject(req_id=req_id, requester=Requester(),
                             ask_verbatim=ask,
                             question_budget=Budget(max=7, per_turn=3))


def _vector():
    return LocalVectorIndex(MockLLM({"dim": 64}), {"path": ":memory:"})


async def test_near_duplicate_fails_deterministically():
    vec = _vector()
    ask = "our monthly vendor report takes 3 days to compile by hand"
    await vec.upsert("req:IPR-2026-000001", ask,
                     {"table": "requirements", "req_id": "IPR-2026-000001"})
    result = await gate4_conflict(MockLLM({}), _obj("IPR-2026-000002", ask), vec)
    assert not result.passed
    assert "IPR-2026-000001" in result.reason
    assert "IPR-2026-000001" in result.suggestion


async def test_own_requirement_is_never_its_own_duplicate():
    vec = _vector()
    ask = "our monthly vendor report takes 3 days to compile by hand"
    await vec.upsert("req:IPR-2026-000001", ask,
                     {"table": "requirements", "req_id": "IPR-2026-000001"})
    result = await gate4_conflict(MockLLM({}), _obj("IPR-2026-000001", ask), vec)
    assert result.passed  # only itself in the index -> no candidates -> rubric passes


async def test_distinct_ask_passes_with_candidates_in_prompt():
    vec = _vector()
    await vec.upsert("req:IPR-2026-000001",
                     "onboard new hires into the HR portal automatically",
                     {"table": "requirements", "req_id": "IPR-2026-000001"})
    result = await gate4_conflict(
        MockLLM({}), _obj("IPR-2026-000002", "sync invoices from the ERP nightly"), vec)
    assert result.passed  # dissimilar -> below threshold -> rubric (mock passes)


async def test_no_vector_index_still_works():
    result = await gate4_conflict(MockLLM({}), _obj("IPR-1", "anything"), None)
    assert result.passed


def test_threshold_is_conservative():
    assert DUPLICATE_FAIL_SCORE >= 0.9