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

SKIP_VALUES = {"skip", "don't know", "dont know", "not sure", "unknown"}


def readiness(obj: RequirementObject, schema: SlotSchema) -> int:
    def coverage(keys: list[str]) -> float:
        if not keys:
            return 1.0
        total = 0.0
        for key in keys:
            slot = obj.slots.get(key)
            if slot is None or slot.value in (None, "", []):
                continue
            weight = PROVENANCE_WEIGHTS.get(slot.provenance, 0.6)
            total += 0.7 + 0.3 * weight * max(0.0, min(1.0, slot.confidence))
        return total / len(keys)

    required = schema.required_keys()
    optional = [k for k in schema.slots if k not in required]
    return round(100 * (0.85 * coverage(required) + 0.15 * coverage(optional)))


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
    def __init__(self, llm, store, vector, schema: SlotSchema, cfg: Config):
        self.llm = llm
        self.store = store
        self.vector = vector
        self.schema = schema
        self.cfg = cfg
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

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
            if key not in self.schema.slots:
                continue
            answered_ids.add(ans.get("question_id"))
            value = ans.get("value")
            if isinstance(value, str) and value.strip().lower() in SKIP_VALUES:
                await self.store.log("question_ledger", {
                    "req_id": obj.req_id, "slot_key": key,
                    "question": (q or {}).get("text", ""), "outcome": "dont_know",
                    "changed_routing": False, "changed_slots": 0})
                apply_defaults(obj, [key], self.schema)
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
                    self.llm, obj, user_msg, exemplar_text, self.schema,
                    glossary_hits=glossary_text)
                obj = intake.merge_slots(obj, extraction)  # never overwrites ANSWERED/EDITED
            except ExtractionError as exc:
                # Graceful degradation: keep prior slots, flag the turn,
                # spend no budget on it.
                degraded = True
                obj.touch("extraction_failed", str(exc)[:300])

        # 2. GAP LADDER (deterministic order: infer, then retrieve)
        await send("status", {"stage": "resolving_gaps"})
        gaps = gap_analyzer.open_required_slots(obj, self.schema)
        gaps = await gap_analyzer.infer_pass(obj, gaps, self.store, self.schema)
        gaps, _ = await precedent.retrieve_pass(obj, gaps, self.store,
                                               self.vector, self.schema)
        for key, slot in obj.slots.items():
            if before.get(key) != slot.model_dump():
                await send("slot", {"key": key, "slot": slot.model_dump()})

        # 3. QUESTIONS (budget enforced in code, NOT in prompt)
        questions: list[Question] = []
        if gaps and obj.question_budget.spent < obj.question_budget.max and not degraded:
            await send("status", {"stage": "composing_questions"})
            asked_before = {e.detail.split(":", 1)[0] for e in obj.audit
                            if e.event == "question_asked"}
            ranked = await gap_analyzer.rank(obj, gaps, self.schema, asked_before)
            ranked = [g for g in ranked if self.schema.slots[g.key].askable]
            n = min(len(ranked), obj.question_budget.per_turn,
                    obj.question_budget.max - obj.question_budget.spent)
            questions = await question_composer.compose(
                self.llm, obj, ranked[:n], self.schema)
            questions = [q for q in questions
                         if self.schema.slots[q.slot_key].askable][:n]
            obj.question_budget.spent += len(questions)
            for q in questions:
                obj.touch("question_asked", f"{q.slot_key}: {q.text}")

        # 4. BUDGET EXHAUSTED -> assumptions with stated defaults
        if not questions:
            obj = apply_defaults(obj, remaining=gaps, schema=self.schema)
            for key in obj.assumptions:
                slot = obj.slots.get(key)
                if slot and before.get(key) != slot.model_dump():
                    await send("slot", {"key": key, "slot": slot.model_dump()})

        # 5. READINESS + RENDER + PERSIST (append version, stream deltas)
        await send("status", {"stage": "scoring"})
        obj.readiness_score = readiness(obj, self.schema)
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
