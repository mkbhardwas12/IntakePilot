"""F: dynamic question budget — blast radius scales the total between floor
and cap, in code; static behavior is byte-identical when the flag is off."""
from __future__ import annotations

from core.config import Config
from core.models import Budget, Provenance, RequirementObject, Requester, Slot
from core.agents.orchestrator import dynamic_budget_max

CFG = Config(budget_dynamic=True, budget_floor=3, budget_cap=9)


def _obj(systems: list[str] | None = None, urgency: str | None = None,
         spent: int = 0) -> RequirementObject:
    obj = RequirementObject(req_id="IPR-1", requester=Requester(),
                            ask_verbatim="ask",
                            question_budget=Budget(max=7, per_turn=3, spent=spent))
    if systems is not None:
        obj.slots["affected_systems"] = Slot(value=systems,
                                             provenance=Provenance.RETRIEVED,
                                             confidence=0.8, source="t")
    if urgency is not None:
        obj.slots["urgency"] = Slot(value=urgency, provenance=Provenance.ANSWERED,
                                    confidence=0.95, source="t")
    return obj


def test_trivial_ask_gets_the_floor():
    assert dynamic_budget_max(_obj(), CFG) == 3
    assert dynamic_budget_max(_obj(systems=["A"]), CFG) == 3


def test_cross_system_and_deadline_scale_up():
    assert dynamic_budget_max(_obj(systems=["A", "B"]), CFG) == 5
    assert dynamic_budget_max(_obj(systems=["A", "B"], urgency="this week"), CFG) == 7
    assert dynamic_budget_max(
        _obj(systems=["A", "B", "C"], urgency="this week"), CFG) == 9


def test_cap_is_a_hard_ceiling():
    obj = _obj(systems=["A", "B", "C", "D", "E"], urgency="this week")
    assert dynamic_budget_max(obj, CFG) == CFG.budget_cap


def test_never_below_already_spent():
    obj = _obj(spent=6)  # trivial ask would score floor=3, but 6 are spent
    assert dynamic_budget_max(obj, CFG) == 6


def test_flag_off_is_default():
    assert Config().budget_dynamic is False  # spec behavior stays the default