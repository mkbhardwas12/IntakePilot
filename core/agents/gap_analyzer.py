"""Gap scan + info-gain scoring + the INFER step of the Gap Resolution Ladder."""
from __future__ import annotations

from dataclasses import dataclass

from core.config import SlotSchema
from core.models import Provenance, RequirementObject, Slot


def is_empty(slot: Slot | None) -> bool:
    return slot is None or slot.value in (None, "", [])


def open_required_slots(obj: RequirementObject, schema: SlotSchema) -> list[str]:
    return [k for k in schema.required_keys() if is_empty(obj.slots.get(k))]


async def infer_pass(obj: RequirementObject, gaps: list[str], store,
                     schema: SlotSchema) -> list[str]:
    """Fill gaps from requester context (role/dept/org). Uses the glossary's
    dept:* entries. Dept context is deliberately too coarse to claim
    affected_systems (the RETRIEVE step owns that with term-level evidence);
    it infers stakeholders, an optional unaskable slot — see SPEC-REVIEW."""
    rows = await store.query_ledger("glossary", term=f"dept:{obj.requester.dept}")
    if not rows:
        return gaps
    maps_to = rows[0].get("maps_to") or {}
    if is_empty(obj.slots.get("stakeholders")) and maps_to.get("team"):
        obj.slots["stakeholders"] = Slot(
            value=[maps_to["team"]], provenance=Provenance.INFERRED,
            confidence=0.55, source=f"dept:{obj.requester.dept}")
    return [k for k in gaps if is_empty(obj.slots.get(k))]


@dataclass
class RankedGap:
    key: str
    score: float
    because: str


async def rank(obj: RequirementObject, gaps: list[str],
               schema: SlotSchema, asked_before: set[str]) -> list[RankedGap]:
    """Info-gain heuristic: required beats optional, never-asked beats re-ask,
    schema order breaks ties. (Milestone 7 recalibrates from question_ledger.)"""
    order = list(schema.slots.keys())
    ranked = []
    for key in gaps:
        spec = schema.slots[key]
        score = 0.0
        because = []
        if spec.required:
            score += 2.0
            because.append("required before this can be routed")
        if key not in asked_before:
            score += 1.0
        else:
            because.append("asked earlier without an answer")
        score += (len(order) - order.index(key)) / (len(order) * 10)
        ranked.append(RankedGap(key=key, score=score,
                                because="; ".join(because) or "helps route this correctly"))
    ranked.sort(key=lambda g: g.score, reverse=True)
    return ranked
