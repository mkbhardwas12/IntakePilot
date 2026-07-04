"""Question ranking must READ the question ledger it writes: slots people
answer (and whose answers change the draft) outrank slots people skip."""
from __future__ import annotations

from core.config import load_slot_schema
from core.models import Budget, RequirementObject, Requester
from core.agents.gap_analyzer import historical_gain, rank
from core.providers.store.sqlite import SqliteStore


def _obj() -> RequirementObject:
    return RequirementObject(req_id="IPR-1", requester=Requester(),
                             ask_verbatim="automate the weekly export",
                             question_budget=Budget(max=7, per_turn=3))


async def _log(store, slot_key: str, outcome: str, changed: int, times: int) -> None:
    for _ in range(times):
        await store.log("question_ledger", {
            "req_id": "IPR-0", "slot_key": slot_key, "question": "q?",
            "outcome": outcome, "changed_routing": False, "changed_slots": changed})


async def test_answered_and_changing_slot_outranks_skipped_slot():
    store = SqliteStore({"path": ":memory:"})
    schema = load_slot_schema()
    # urgency historically answered and impactful; success_criteria skipped.
    await _log(store, "urgency", "answered", changed=1, times=6)
    await _log(store, "success_criteria", "skipped", changed=0, times=6)

    ranked = await rank(_obj(), ["success_criteria", "urgency"], schema,
                        asked_before=set(), store=store)
    assert [g.key for g in ranked][0] == "urgency"


async def test_cold_start_matches_static_heuristic():
    store = SqliteStore({"path": ":memory:"})
    schema = load_slot_schema()
    gaps = ["urgency", "success_criteria"]
    with_history = await rank(_obj(), gaps, schema, set(), store=store)
    without = await rank(_obj(), gaps, schema, set(), store=None)
    assert [g.key for g in with_history] == [g.key for g in without]


async def test_history_never_outranks_requiredness():
    store = SqliteStore({"path": ":memory:"})
    schema = load_slot_schema()
    # scope_boundaries (optional) heavily answered; urgency (required) unseen.
    await _log(store, "scope_boundaries", "answered", changed=1, times=10)
    ranked = await rank(_obj(), ["scope_boundaries", "urgency"], schema,
                        set(), store=store)
    assert ranked[0].key == "urgency"


async def test_gain_math_is_smoothed():
    store = SqliteStore({"path": ":memory:"})
    gains = await historical_gain(store, ["urgency"])
    assert gains["urgency"] == 0.25  # (0+1)/(0+2) * (0+1)/(0+2)
    await _log(store, "urgency", "answered", changed=1, times=4)
    gains = await historical_gain(store, ["urgency"])
    assert gains["urgency"] > 0.5