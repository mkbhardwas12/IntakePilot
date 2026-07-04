"""Five-gate Jidoka pipeline (spec 6.3) — pure functions over a confirmed object.

Gates 1 and 3 are deterministic (schema validation; weak-word lint with a
context check). Gates 2, 4, 5 use the LLM as a scored rubric behind the same
validate-and-retry wrapper (the mock provider returns pass, so the offline
demo exercises the full pipeline). Failures never mutate the object; they are
returned as structured {gate, reason, suggestion} and logged to outcome_ledger.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from core.config import SlotSchema
from core.models import ExtractionError, GateResult, RequirementObject
from core.providers.llm.base import Msg, complete_validated

GATE_NAMES = {1: "Schema", 2: "INVEST", 3: "Ambiguity", 4: "Conflict", 5: "Routing"}

RUBRIC_SCHEMA = {
    "type": "object",
    "required": ["passed"],
    "properties": {
        "passed": {"type": "boolean"},
        "reason": {"type": "string"},
        "suggestion": {"type": "string"},
    },
}

_WEAK_WORDS_PATH = Path(__file__).resolve().parent / "weak_words.txt"


def load_weak_words() -> list[str]:
    words = []
    for line in _WEAK_WORDS_PATH.read_text().splitlines():
        line = line.strip().lower()
        if line and not line.startswith("#"):
            words.append(line)
    return words


def gate1_schema(obj: RequirementObject, schema: SlotSchema) -> GateResult:
    """Deterministic: every required slot filled, confirmation present."""
    missing = [k for k in schema.required_keys()
               if obj.slots.get(k) is None or obj.slots[k].value in (None, "", [])]
    if missing:
        return GateResult(gate=1, name=GATE_NAMES[1], passed=False,
                          reason=f"required slots empty: {', '.join(missing)}",
                          suggestion="fill the missing slots or apply defaults, then reconfirm")
    if obj.confirmation is None:
        return GateResult(gate=1, name=GATE_NAMES[1], passed=False,
                          reason="no confirmation record",
                          suggestion="nothing routes without a confirmation (spec Section 11)")
    return GateResult(gate=1, name=GATE_NAMES[1], passed=True)


_HAS_CONCRETE = re.compile(r"\d|\b(?:january|february|march|april|may|june|july|"
                           r"august|september|october|november|december)\b", re.I)


def gate3_ambiguity(obj: RequirementObject, schema: SlotSchema,
                    weak_words: list[str] | None = None) -> GateResult:
    """Deterministic lint: weak words in outcome/criteria slots, flagged only
    when the slot value carries no concrete number/date (the context check)."""
    weak_words = weak_words if weak_words is not None else load_weak_words()
    findings = []
    for key in ("business_outcome", "success_criteria", "scope_boundaries"):
        slot = obj.slots.get(key)
        if slot is None or not isinstance(slot.value, str):
            continue
        text = slot.value.lower()
        if _HAS_CONCRETE.search(text):
            continue  # concrete anchor present; weak wording tolerated
        hits = [w for w in weak_words if re.search(rf"\b{re.escape(w)}\b", text)]
        if hits:
            findings.append(f"{key}: \u201c{', '.join(hits)}\u201d")
    if findings:
        return GateResult(gate=3, name=GATE_NAMES[3], passed=False,
                          reason="ambiguous wording without measurable anchors — "
                                 + "; ".join(findings),
                          suggestion="replace weak words with a number, date, or named system")
    return GateResult(gate=3, name=GATE_NAMES[3], passed=True)


async def _rubric_gate(llm, gate: int, obj: RequirementObject, criteria: str,
                       context: str = "") -> GateResult:
    slots = {k: s.value for k, s in obj.slots.items() if s.value not in (None, "", [])}
    system = (f"TASK: gate{gate}\nYou are a requirement quality gate "
              f"({GATE_NAMES[gate]}). Criteria: {criteria}\n"
              "Output JSON: {\"passed\": bool, \"reason\": str, \"suggestion\": str}.")
    user = f"Requirement slots:\n{json.dumps(slots, default=str)}\nAsk: {obj.ask_verbatim}"
    if context:
        user += f"\n{context}"
    try:
        data = await complete_validated(
            llm, [Msg(role="system", content=system), Msg(role="user", content=user)],
            RUBRIC_SCHEMA)
    except ExtractionError as exc:
        return GateResult(gate=gate, name=GATE_NAMES[gate], passed=False,
                          reason=f"rubric evaluation failed: {exc}",
                          suggestion="route to human triage")
    return GateResult(gate=gate, name=GATE_NAMES[gate], passed=bool(data["passed"]),
                      reason=data.get("reason"), suggestion=data.get("suggestion"))


# Cosine similarity at or above this fails gate 4 deterministically — no
# LLM judgement needed when the org index already contains a near-identical ask.
DUPLICATE_FAIL_SCORE = 0.92


async def _duplicate_candidates(vector, obj: RequirementObject) -> list:
    """Top similar past requirements from the org index (self excluded).
    These are the 'known work' gate 4 compares against — without them the
    conflict/duplicate rubric has nothing to detect duplicates WITH."""
    if vector is None:
        return []
    hits = await vector.search(obj.ask_verbatim, k=6,
                               filter={"table": "requirements"})
    return [h for h in hits if h.meta.get("req_id") != obj.req_id][:4]


async def gate4_conflict(llm, obj: RequirementObject, vector=None) -> GateResult:
    candidates = await _duplicate_candidates(vector, obj)
    if candidates and candidates[0].score >= DUPLICATE_FAIL_SCORE:
        top = candidates[0]
        dup_id = top.meta.get("req_id", top.id)
        return GateResult(
            gate=4, name=GATE_NAMES[4], passed=False,
            reason=(f"near-duplicate of {dup_id} "
                    f"(similarity {top.score:.2f}): “{top.text[:100]}”"),
            suggestion=f"review {dup_id} and attach to it, or reword to distinguish",
            meta={"duplicate_of": dup_id, "similarity": round(top.score, 3)})
    if candidates:
        lines = "\n".join(
            f"- {h.meta.get('req_id', h.id)} (similarity {h.score:.2f}): {h.text[:140]}"
            for h in candidates)
        context = ("Known existing requirements from the org index "
                   "(compare against these):\n" + lines)
    else:
        context = "Known existing requirements from the org index: none found."
    return await _rubric_gate(
        llm, 4, obj,
        "Conflict/duplicate: does this contradict or duplicate the known "
        "existing requirements listed below?", context=context)


async def run_gates(llm, obj: RequirementObject, schema: SlotSchema,
                    vector=None) -> list[GateResult]:
    results = [gate1_schema(obj, schema)]
    results.append(await _rubric_gate(
        llm, 2, obj, "INVEST: independent, negotiable, valuable, estimable, small, testable."))
    results.append(gate3_ambiguity(obj, schema))
    results.append(await gate4_conflict(llm, obj, vector))
    results.append(await _rubric_gate(
        llm, 5, obj, "Routing sanity: is there enough signal to route to one team queue?"))
    return results
