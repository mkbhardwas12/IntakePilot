"""Readiness weights calibrate from the edit ledger: provenances that humans
routinely correct at confirmation earn less trust — per context bucket, with
smoothing and a hard floor, and identical to the base weights cold-start."""
from __future__ import annotations

from core.config import load_slot_schema
from core.models import Budget, Provenance, RequirementObject, Requester, Slot
from core.agents.orchestrator import (CALIBRATION_MAX_DISCOUNT,
                                      PROVENANCE_WEIGHTS, calibrated_weights,
                                      readiness)
from core.learning import exemplars as learning
from core.providers.llm.mock import MockLLM
from core.providers.store.sqlite import SqliteStore
from core.providers.vector.local import LocalVectorIndex

BUCKET = "Finance Ops:default"


def _obj() -> RequirementObject:
    return RequirementObject(
        req_id="IPR-1", requester=Requester(dept="Finance Ops"),
        ask_verbatim="automate the vendor report",
        question_budget=Budget(max=7, per_turn=3))


async def _seed(store, *, edits_inferred: int, confirms: int) -> None:
    vector = LocalVectorIndex(MockLLM({"dim": 32}), {"path": ":memory:"})
    obj = _obj()
    for i in range(edits_inferred):
        await learning.capture_edit(store, vector, obj, "stakeholders",
                                    ["a"], ["b"], provenance="inferred")
    for _ in range(confirms):
        await store.log("outcome_ledger", {
            "req_id": "IPR-0", "stage": "confirmed", "verdict": "ok",
            "detail": {"bucket": BUCKET, "edits": 0}})


async def test_cold_start_returns_base_weights():
    store = SqliteStore({"path": ":memory:"})
    assert await calibrated_weights(store, BUCKET) == PROVENANCE_WEIGHTS


async def test_frequently_edited_provenance_is_discounted():
    store = SqliteStore({"path": ":memory:"})
    await _seed(store, edits_inferred=6, confirms=6)
    weights = await calibrated_weights(store, BUCKET)
    assert weights[Provenance.INFERRED] < PROVENANCE_WEIGHTS[Provenance.INFERRED]
    # untouched provenances keep their base weight
    assert weights[Provenance.EXTRACTED] == PROVENANCE_WEIGHTS[Provenance.EXTRACTED]


async def test_discount_is_floored_at_half_base():
    store = SqliteStore({"path": ":memory:"})
    await _seed(store, edits_inferred=50, confirms=1)  # rate saturates at 1.0
    weights = await calibrated_weights(store, BUCKET)
    floor = PROVENANCE_WEIGHTS[Provenance.INFERRED] * (1 - CALIBRATION_MAX_DISCOUNT)
    assert abs(weights[Provenance.INFERRED] - floor) < 1e-9


async def test_buckets_are_isolated():
    store = SqliteStore({"path": ":memory:"})
    await _seed(store, edits_inferred=6, confirms=6)
    other = await calibrated_weights(store, "Sales:default")
    assert other == PROVENANCE_WEIGHTS


async def test_readiness_drops_with_discounted_weights():
    schema = load_slot_schema()
    obj = _obj()
    obj.slots["stakeholders"] = Slot(value=["finance-systems"],
                                     provenance=Provenance.INFERRED,
                                     confidence=0.9, source="dept")
    base = readiness(obj, schema)
    discounted = readiness(obj, schema, {
        **PROVENANCE_WEIGHTS,
        Provenance.INFERRED: PROVENANCE_WEIGHTS[Provenance.INFERRED] * 0.5})
    assert discounted <= base