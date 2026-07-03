"""Question Composer — composes ONE budgeted batch. The budget and askable
filters are enforced HERE in code (spec Section 11: the model never controls
the loop); the prompt is only for phrasing.
"""
from __future__ import annotations

import json

from core.config import SlotSchema
from core.models import ExtractionError, Question, RequirementObject
from core.providers.llm.base import LLMProvider, Msg, complete_validated
from core.agents import prompts
from core.agents.gap_analyzer import RankedGap

QUESTION_SCHEMA = {
    "type": "object",
    "required": ["questions"],
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["slot_key", "text"],
                "properties": {
                    "slot_key": {"type": "string"},
                    "text": {"type": "string"},
                    "because": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "string"}},
                },
            },
        }
    },
}


async def compose(llm: LLMProvider, obj: RequirementObject,
                  ranked: list[RankedGap], schema: SlotSchema) -> list[Question]:
    """`ranked` is already askable-filtered and budget-truncated by the
    orchestrator. Whatever the model returns is re-filtered and re-truncated
    here — a model cannot exceed the batch, ask unaskable slots, or re-ask."""
    if not ranked:
        return []
    allowed = [g.key for g in ranked]
    gaps_payload = [{
        "key": g.key,
        "ask_hint": schema.slots[g.key].ask_hint,
        "because": g.because,
        "options": schema.slots[g.key].options,
    } for g in ranked]
    answered = [k for k, s in obj.slots.items() if s.value not in (None, "", [])]
    system = prompts.load(
        "question",
        unaskable_slots=", ".join(schema.unaskable_keys()),
        answered=", ".join(answered) or "(none)")
    user = (f"Original ask: {obj.ask_verbatim}\n\n"
            f"## Gaps\n```json\n{json.dumps(gaps_payload)}\n```")
    try:
        data = await complete_validated(
            llm, [Msg(role="system", content=system), Msg(role="user", content=user)],
            QUESTION_SCHEMA)
        raw = data["questions"]
    except ExtractionError:
        raw = []  # degrade to deterministic phrasing from ask_hints
    by_key = {q["slot_key"]: q for q in raw if q.get("slot_key") in allowed}

    questions: list[Question] = []
    for i, gap in enumerate(ranked):
        model_q = by_key.get(gap.key)
        spec = schema.slots[gap.key]
        text = (model_q or {}).get("text") or (
            (spec.ask_hint or f"tell me about {gap.key.replace('_', ' ')}").capitalize())
        options = (model_q or {}).get("options") or spec.options
        questions.append(Question(
            id=f"q{obj.question_budget.spent + i + 1}-{gap.key}",
            slot_key=gap.key,
            text=text[0].upper() + text[1:],
            because=(model_q or {}).get("because") or gap.because,
            options=options[:4] if options else None))
    return questions
