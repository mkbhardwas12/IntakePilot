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


# Weight of the measured info-gain signal relative to the static heuristic.
# Gain is in (0, 1), so history can reorder slots within the same tier but
# never outranks required-ness (+2.0).
HISTORY_WEIGHT = 1.0


async def historical_gain(store, keys: list[str]) -> dict[str, float]:
    """Measured info gain per slot from the question ledger:
    P(answered) × P(answer changed slots), Laplace-smoothed.
    With no history every slot gets the same prior (0.25), so cold-start
    ordering is identical to the static heuristic."""
    counts: dict[str, dict[str, int]] = {}
    for row in await store.query_ledger("question_ledger"):
        key = row.get("slot_key")
        if key not in keys:
            continue
        d = counts.setdefault(key, {"asked": 0, "answered": 0, "changed": 0})
        if row.get("outcome") in ("answered", "skipped", "dont_know"):
            d["asked"] += 1
        if row.get("outcome") == "answered":
            d["answered"] += 1
            # SQLite TEXT affinity can hand back '1' for this column.
            if int(row.get("changed_slots") or 0) > 0:
                d["changed"] += 1
    gains: dict[str, float] = {}
    for key in keys:
        d = counts.get(key, {"asked": 0, "answered": 0, "changed": 0})
        p_answered = (d["answered"] + 1) / (d["asked"] + 2)
        p_changed = (d["changed"] + 1) / (d["answered"] + 2)
        gains[key] = p_answered * p_changed
    return gains


async def rank(obj: RequirementObject, gaps: list[str],
               schema: SlotSchema, asked_before: set[str],
               store=None) -> list[RankedGap]:
    """Info-gain scoring: required beats optional, never-asked beats re-ask,
    then MEASURED gain from the question ledger — slots people actually
    answer (and whose answers change the draft) rise; slots people skip
    sink. Schema order breaks remaining ties."""
    order = list(schema.slots.keys())
    gains = await historical_gain(store, gaps) if store is not None else {}
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
            because.append("asked earlier — still open")
        score += HISTORY_WEIGHT * gains.get(key, 0.0)
        score += (len(order) - order.index(key)) / (len(order) * 10)
        ranked.append(RankedGap(key=key, score=score,
                                because="; ".join(because) or "helps route this correctly"))
    ranked.sort(key=lambda g: g.score, reverse=True)
    return ranked
