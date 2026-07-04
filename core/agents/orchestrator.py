"""THE bounded loop (deterministic) — spec Section 6.1 implemented verbatim
in spirit: extract -> merge -> gap ladder (infer, retrieve) -> budgeted
questions -> defaults -> readiness -> append version.

Everything the model must not control is decided here in code: the question
budget, the askable filter, the ladder order, merges, and status transitions.

Readiness rubric (the spec references readiness(obj) but never defines it —
see docs/SPEC-REVIEW.md finding #1). Our definition:

    readiness = round(100 * (0.85 * required_cov + 0.15 * optional_cov))

    each FILLED slot contributes: 0.7 + 0.3 * provenance_weight * confidence
    (a filled slot is mostly ready; how it was filled tunes the rest)
    provenance weights: answered/edited 1.0, extracted 0.9, retrieved 0.85,
                        inferred 0.75, assumed 0.6
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Awaitable, Callable

from core.config import Config, SlotSchema
from core.models import (ExtractionError, Provenance, Question,
                         RequirementObject, Slot, Status, TurnResult)
from core.agents import gap_analyzer, intake, precedent, question_composer
from core.learning import exemplars as learning

Emit = Callable[[str, dict], Awaitable[None]]

PROVENANCE_WEIGHTS = {
    Provenance.ANSWERED: 1.0, Provenance.EDITED: 1.0,
    Provenance.EXTRACTED: 0.9, Provenance.RETRIEVED: 0.85,
    Provenance.INFERRED: 0.75, Provenance.ASSUMED: 0.6,
}

# Calibration: how strongly the edit ledger can discount a provenance weight,
# and the Laplace-style smoothing on the confirm denominator.
CALIBRATION_MAX_DISCOUNT = 0.5   # a weight never drops below half its base
CALIBRATION_SMOOTHING = 2        # pseudo-confirmations

SKIP_VALUES = {"skip", "don't know", "dont know", "not sure", "unknown"}


async def calibrated_weights(store, bucket: str) -> dict[Provenance, float]:
    """Per-bucket provenance weights, learned from edit_diffs: if humans in
    this context routinely correct slots of a given provenance at
    confirmation, that provenance contributes less to readiness. Only
    human-originated signals feed this (spec Section 11); with an empty
    ledger the base weights are returned unchanged."""
    confirms = sum(
        1 for r in await store.query_ledger("outcome_ledger", stage="confirmed")
        if (r.get("detail") or {}).get("bucket") == bucket)
    counts: dict[str, int] = {}
    for row in await store.query_ledger("edit_diffs", context_bucket=bucket):
        prov = row.get("provenance")
        if prov:
            counts[prov] = counts.get(prov, 0) + 1
    weights = dict(PROVENANCE_WEIGHTS)
    for prov in weights:
        edited = counts.get(prov.value, 0)
        if not edited:
            continue
        rate = min(1.0, edited / (confirms + CALIBRATION_SMOOTHING))
        weights[prov] = round(weights[prov] * (1 - CALIBRATION_MAX_DISCOUNT * rate), 4)
    return weights


def readiness(obj: RequirementObject, schema: SlotSchema,
              weights: dict[Provenance, float] | None = None) -> int:
    weights = weights or PROVENANCE_WEIGHTS

    def coverage(keys: list[str]) -> float:
        if not keys:
            return 1.0
        total = 0.0
        for key in keys:
            slot = obj.slots.get(key)
            if slot is None or slot.value in (None, "", []):
                continue
            weight = weights.get(slot.provenance, 0.6)
            total += 0.7 + 0.3 * weight * max(0.0, min(1.0, slot.confidence))
        return total / len(keys)

    required = schema.required_keys()
    optional = [k for k in schema.slots if k not in required]
    return round(100 * (0.85 * coverage(required) + 0.15 * coverage(optional)))


def dynamic_budget_max(obj: RequirementObject, cfg: Config) -> int:
    """F: budget scales with blast radius — trivial asks earn few questions,
    cross-system or deadline-driven asks earn more. Enforcement stays in
    code: the result is clamped to [floor, cap] and never drops below what
    is already spent (the meter can grow mid-session as systems are
    discovered, but a shrink can never strand the requirement)."""
    systems = obj.slots.get("affected_systems")
    n_systems = (len(systems.value)
                 if systems and isinstance(systems.value, list) else 0)
    urgency = obj.slots.get("urgency")
    urgency_val = str(urgency.value).lower() if urgency and urgency.value else ""

    score = 0  # 0..3
    if n_systems >= 2:
        score += 1
    if n_systems >= 3:
        score += 1
    if urgency_val in ("this week", "this month"):
        score += 1

    span = max(0, cfg.budget_cap - cfg.budget_floor)
    scaled = cfg.budget_floor + round(span * score / 3)
    return max(min(scaled, cfg.budget_cap), obj.question_budget.spent)


def apply_defaults(obj: RequirementObject, remaining: list[str],
                   schema: SlotSchema) -> RequirementObject:
    """Budget exhausted (or nothing askable) -> assumptions with stated defaults.
    Slots without a schema default stay open for tech enrichment."""
    for key in remaining:
        spec = schema.slots[key]
        if spec.default is None or not gap_analyzer.is_empty(obj.slots.get(key)):
            continue
        obj.slots[key] = Slot(value=spec.default, provenance=Provenance.ASSUMED,
                              confidence=0.5, source="schema_default",
                              default_reason=spec.default_reason or "org default")
        if key not in obj.assumptions:
            obj.assumptions.append(key)
        obj.touch("default_applied", f"{key}={spec.default}")
    return obj


class Orchestrator:
    def __init__(self, llm, store, vector, schema: SlotSchema, cfg: Config,
                 schemas: dict[str, SlotSchema] | None = None):
        self.llm = llm
        self.store = store
        self.vector = vector
        self.schema = schema
        # E: schema forks per request type; unknown types fall back to default.
        self.schemas = schemas or {"default": schema}
        self.cfg = cfg
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def schema_for(self, request_type: str) -> SlotSchema:
        return self.schemas.get(request_type, self.schema)

    def lock_for(self, req_id: str) -> asyncio.Lock:
        """Per-requirement mutex shared by turns AND confirm, so a confirm can
        never interleave with an in-flight turn (or another confirm) and race
        the append-only version write."""
        return self._locks[req_id]

    async def handle_turn(self, session: dict, user_msg: str,
                          answers: list[dict] | None = None,
                          emit: Emit | None = None) -> TurnResult:
        # One in-flight mutation per requirement (SPEC-REVIEW finding #4).
        async with self.lock_for(session["req_id"]):
            return await self._turn(session, user_msg, answers or [], emit)

    async def _turn(self, session: dict, user_msg: str,
                    answers: list[dict], emit: Emit | None) -> TurnResult:
        async def send(event: str, data: dict) -> None:
            if emit:
                await emit(event, data)

        obj = await self.store.latest(session["req_id"])
        # E: the slot schema is a fork per request type (fallback: default).
        schema = self.schema_for(obj.request_type)
        obj.version += 1
        obj.touch("turn_started", user_msg[:200])
        before = {k: s.model_dump() for k, s in obj.slots.items()}
        degraded = False

        # 0. Apply chip/typed answers deterministically (provenance ANSWERED);
        #    log question outcomes to the question ledger.
        pending = {q["id"]: q for q in session.get("pending_questions", [])}
        answered_ids = set()
        for ans in answers:
            q = pending.get(ans.get("question_id"))
            if q is None:
                # Only answers to questions we actually asked are accepted;
                # anything else could write arbitrary (even askable:false)
                # slots with ANSWERED provenance and inflate question metrics.
                continue
            key = q.get("slot_key")
            if key not in schema.slots:
                continue
            answered_ids.add(ans.get("question_id"))
            value = ans.get("value")
            if isinstance(value, str) and value.strip().lower() in SKIP_VALUES:
                await self.store.log("question_ledger", {
                    "req_id": obj.req_id, "slot_key": key,
                    "question": (q or {}).get("text", ""), "outcome": "dont_know",
                    "changed_routing": False, "changed_slots": 0})
                apply_defaults(obj, [key], schema)
                continue
            obj.slots[key] = Slot(value=value, provenance=Provenance.ANSWERED,
                                  confidence=0.95,
                                  source=ans.get("question_id"))
            await send("slot", {"key": key, "slot": obj.slots[key].model_dump()})
            await self.store.log("question_ledger", {
                "req_id": obj.req_id, "slot_key": key,
                "question": (q or {}).get("text", ""), "outcome": "answered",
                "changed_routing": False, "changed_slots": 1})
        for qid, q in pending.items():
            if qid not in answered_ids:
                await self.store.log("question_ledger", {
                    "req_id": obj.req_id, "slot_key": q["slot_key"],
                    "question": q.get("text", ""), "outcome": "skipped",
                    "changed_routing": False, "changed_slots": 0})

        # 1. EXTRACT (LLM proposes; code validates) — with correction exemplars.
        if user_msg.strip():
            await send("status", {"stage": "extracting"})
            exemplar_text = await learning.select_exemplars(
                self.vector, agent="intake", context=obj.context_bucket,
                ask=user_msg, k=4)
            glossary_hits = await precedent.glossary_scan(self.store, user_msg + " " + obj.ask_verbatim)
            glossary_text = "".join(
                f"- \u201c{h['term']}\u201d maps to {h['maps_to']}\n" for h in glossary_hits)
            try:
                extraction = await intake.extract(
                    self.llm, obj, user_msg, exemplar_text, schema,
                    glossary_hits=glossary_text)
                obj = intake.merge_slots(obj, extraction)  # never overwrites ANSWERED/EDITED
            except ExtractionError as exc:
                # Graceful degradation: keep prior slots, flag the turn,
                # spend no budget on it.
                degraded = True
                obj.touch("extraction_failed", str(exc)[:300])

        # 2. GAP LADDER (deterministic order: infer, then retrieve)
        await send("status", {"stage": "resolving_gaps"})
        gaps = gap_analyzer.open_required_slots(obj, schema)
        gaps = await gap_analyzer.infer_pass(obj, gaps, self.store, schema)
        gaps, _ = await precedent.retrieve_pass(obj, gaps, self.store,
                                               self.vector, schema)
        for key, slot in obj.slots.items():
            if before.get(key) != slot.model_dump():
                await send("slot", {"key": key, "slot": slot.model_dump()})

        # 3. QUESTIONS (budget enforced in code, NOT in prompt)
        if self.cfg.budget_dynamic:
            obj.question_budget.max = dynamic_budget_max(obj, self.cfg)
        questions: list[Question] = []
        if gaps and obj.question_budget.spent < obj.question_budget.max and not degraded:
            await send("status", {"stage": "composing_questions"})
            asked_before = {e.detail.split(":", 1)[0] for e in obj.audit
                            if e.event == "question_asked"}
            ranked = await gap_analyzer.rank(obj, gaps, schema, asked_before,
                                             store=self.store)
            ranked = [g for g in ranked if schema.slots[g.key].askable]
            n = min(len(ranked), obj.question_budget.per_turn,
                    obj.question_budget.max - obj.question_budget.spent)
            questions = await question_composer.compose(
                self.llm, obj, ranked[:n], schema)
            questions = [q for q in questions
                         if schema.slots[q.slot_key].askable][:n]
            obj.question_budget.spent += len(questions)
            for q in questions:
                obj.touch("question_asked", f"{q.slot_key}: {q.text}")

        # 4. BUDGET EXHAUSTED -> assumptions with stated defaults
        if not questions:
            obj = apply_defaults(obj, remaining=gaps, schema=schema)
            for key in obj.assumptions:
                slot = obj.slots.get(key)
                if slot and before.get(key) != slot.model_dump():
                    await send("slot", {"key": key, "slot": slot.model_dump()})

        # 5. READINESS + RENDER + PERSIST (append version, stream deltas)
        await send("status", {"stage": "scoring"})
        obj.readiness_score = readiness(
            obj, schema,
            await calibrated_weights(self.store, obj.context_bucket))
        confirm_unlocked = obj.readiness_score >= self.cfg.confirm_threshold
        if questions:
            obj.status = Status.QUESTIONING
        elif confirm_unlocked and obj.status in (Status.DRAFT, Status.QUESTIONING):
            obj.status = Status.AWAITING_CONFIRMATION
        obj.touch("turn_completed",
                  f"readiness={obj.readiness_score} budget={obj.question_budget.spent}"
                  f"/{obj.question_budget.max}" + (" degraded" if degraded else ""))
        await self.store.put_version(obj)
        await precedent.index_requirement(self.vector, obj)
        await send("readiness", {"score": obj.readiness_score})
        await send("questions", {"questions": [q.model_dump() for q in questions]})

        # Session bookkeeping (pending questions, transcript)
        session["pending_questions"] = [q.model_dump() for q in questions]
        session["budget_spent"] = obj.question_budget.spent
        await self.store.put_session(session)

        return TurnResult(draft=obj, questions=questions,
                          confirm_unlocked=confirm_unlocked, degraded=degraded)
