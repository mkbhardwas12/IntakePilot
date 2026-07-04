"""Acceptance-criteria generation (I3) — Given/When/Then from the confirmed
requirement, attached to the routed ticket.

This is the third artifact of the handoff: the structured requirement, these
acceptance scenarios, and (v0.2) the Builder Agent's scaffold. A coding
agent can verify its own pull request against them; a developer reviews a
checklist instead of re-deriving intent. Gate 3 already refuses success
criteria without measurable anchors, so what reaches this step is testable
by construction — this turns it into checkable scenarios.

Generation uses the same validate-and-retry (and escalation) wrapper as
every other LLM call; on failure the ticket simply ships without the
section — graceful degradation, never a blocked route.
"""
from __future__ import annotations

import json

from core.config import SlotSchema
from core.models import ExtractionError, RequirementObject
from core.providers.llm.base import Msg, complete_validated

ACCEPTANCE_SCHEMA = {
    "type": "object",
    "required": ["scenarios"],
    "properties": {
        "scenarios": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["given", "when", "then"],
                "properties": {
                    "given": {"type": "string"},
                    "when": {"type": "string"},
                    "then": {"type": "string"},
                },
            },
        }
    },
}

MAX_SCENARIOS = 4


async def generate(llm, obj: RequirementObject,
                   schema: SlotSchema) -> list[dict]:
    slots = {k: s.value for k, s in obj.slots.items()
             if s.value not in (None, "", []) and k != "backend_context"}
    system = (
        "TASK: acceptance\n"
        "You write acceptance criteria for a confirmed business requirement. "
        "Produce 2–4 Given/When/Then scenarios. Every 'then' must be "
        "verifiable (a number, a state, an artifact — never 'works well'). "
        "Output JSON: {\"scenarios\": [{\"given\": str, \"when\": str, "
        "\"then\": str}]}.")
    user = (f"Requirement slots:\n{json.dumps(slots, default=str)}\n"
            f"Ask: {obj.ask_verbatim}")
    try:
        data = await complete_validated(
            llm, [Msg(role="system", content=system),
                  Msg(role="user", content=user)], ACCEPTANCE_SCHEMA)
    except ExtractionError:
        return []  # never block routing over a missing nicety
    scenarios = [s for s in data.get("scenarios", [])
                 if all(str(s.get(k, "")).strip() for k in ("given", "when", "then"))]
    return scenarios[:MAX_SCENARIOS]


def section(scenarios: list[dict]) -> str:
    """Markdown block for the routed ticket."""
    if not scenarios:
        return ""
    lines = ["", "## Acceptance criteria (generated)", "",
             "_Generated from the confirmed requirement — review before "
             "treating as a contract. A coding agent can verify its pull "
             "request against these._", ""]
    for i, s in enumerate(scenarios, 1):
        lines += [f"{i}. **Given** {s['given']}",
                  f"   **When** {s['when']}",
                  f"   **Then** {s['then']}"]
    return "\n".join(lines)
