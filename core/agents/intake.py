"""Intake agent — slot extraction (LLM proposes; code validates) and merge_slots.

The merge rule is the invariant: ANSWERED and EDITED slots are never
overwritten by extraction, and ask_verbatim is untouchable by construction
(extraction output has no path to it).
"""
from __future__ import annotations

from core.config import SlotSchema
from core.models import Provenance, RequirementObject, Slot
from core.providers.llm.base import LLMProvider, Msg, complete_validated
from core.agents import prompts

SLOT_EXTRACTION_SCHEMA = {
    "type": "object",
    "required": ["slots"],
    "properties": {
        "slots": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "required": ["value", "confidence"],
                "properties": {
                    "value": {},
                    "confidence": {"type": "number"},
                },
            },
        }
    },
}

PROTECTED = {Provenance.ANSWERED, Provenance.EDITED}


def build_extract_messages(obj: RequirementObject, user_msg: str,
                           exemplars: str, schema: SlotSchema,
                           glossary_hits: str = "", precedent_snippets: str = "") -> list[Msg]:
    slot_desc = "\n".join(
        f"- {k}: {s.label}" + (f" ({s.ask_hint})" if s.ask_hint else "")
        for k, s in schema.slots.items())
    system = prompts.load(
        "extract",
        slot_descriptions=slot_desc,
        glossary_hits=glossary_hits or "(none)\n",
        precedent_snippets=precedent_snippets or "",
        exemplars=exemplars or "(no past corrections yet)")
    convo = f"Original ask (verbatim): {obj.ask_verbatim}\n\n## User message\n{user_msg}"
    return [Msg(role="system", content=system), Msg(role="user", content=convo)]


async def extract(llm: LLMProvider, obj: RequirementObject, user_msg: str,
                  exemplars: str, schema: SlotSchema,
                  glossary_hits: str = "", precedent_snippets: str = "") -> dict:
    """Returns validated {slot_key: {value, confidence}}. Raises ExtractionError."""
    messages = build_extract_messages(obj, user_msg, exemplars, schema,
                                      glossary_hits, precedent_snippets)
    data = await complete_validated(llm, messages, SLOT_EXTRACTION_SCHEMA)
    # Only keys in the active slot schema survive; the model cannot invent slots
    # and has no path to ask_verbatim, budget, or status.
    return {k: v for k, v in data.get("slots", {}).items()
            if k in schema.slots and v.get("value") not in (None, "", [])}


def merge_slots(obj: RequirementObject, extraction: dict) -> RequirementObject:
    """Never overwrite ANSWERED/EDITED. Higher-confidence extraction may refresh
    other machine-filled slots; equal-or-lower confidence never downgrades."""
    for key, proposal in extraction.items():
        current = obj.slots.get(key)
        if current and current.provenance in PROTECTED:
            continue
        confidence = max(0.0, min(1.0, float(proposal.get("confidence", 0.5))))
        if current and current.value is not None and confidence <= current.confidence:
            continue
        obj.slots[key] = Slot(value=proposal["value"],
                              provenance=Provenance.EXTRACTED,
                              confidence=confidence,
                              source="user_text")
    return obj
