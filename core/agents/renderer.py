"""Renderer — plain-language business view of a Requirement Object."""
from __future__ import annotations

from core.config import SlotSchema
from core.models import Provenance, RequirementObject
from core.agents import value as value_agent

# Slots rendered as dedicated sections, not generic slot lines.
_SPECIAL_SLOTS = ("backend_context", "cost_of_delay")


def _fmt(value) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def business_render(obj: RequirementObject, schema: SlotSchema) -> str:
    lines = [f"## Requirement {obj.req_id}", "",
             f"**Original ask:** \u201c{obj.ask_verbatim}\u201d", ""]
    outcome = obj.slots.get("business_outcome")
    if outcome and outcome.value:
        lines += [f"**What should change:** {_fmt(outcome.value)}", ""]
    if obj.analyst and obj.analyst.interpretation:
        placed = (f" _(placed in {obj.analyst.process.label})_"
                  if obj.analyst.process else "")
        lines += [f"**Analyst's read:** {obj.analyst.interpretation}{placed}", ""]
        open_needs = [n for n in obj.analyst.unstated_needs if n.status == "open"]
        if open_needs:
            lines.append("_Worth deciding before build:_")
            lines += [f"- {n.need} — {n.why}" for n in open_needs]
            lines.append("")
    for key, spec in schema.slots.items():
        if key == "business_outcome" or key in _SPECIAL_SLOTS:
            continue  # special slots get their own structured sections
        slot = obj.slots.get(key)
        if slot is None or slot.value in (None, "", []):
            continue
        suffix = ""
        if slot.provenance == Provenance.ASSUMED:
            suffix = f" _(assumed — {slot.default_reason or 'default applied'})_"
        elif slot.provenance == Provenance.RETRIEVED and slot.source:
            suffix = f" _(from {slot.source})_"
        lines.append(f"- **{spec.label}:** {_fmt(slot.value)}{suffix}")
    cod = obj.slots.get("cost_of_delay")
    if cod and isinstance(cod.value, dict):
        lines += ["", f"**Estimated cost of doing nothing:** "
                      f"{value_agent.describe(cod.value)}"]
    if obj.assumptions:
        lines += ["", f"_{len(obj.assumptions)} assumption(s) applied — "
                      "review the assumption register before confirming._"]
    return "\n".join(lines)


def backend_context_section(obj: RequirementObject) -> list[str]:
    """ADDENDUM-01: auto-discovered backend entities + customizations, rendered
    so the assigned team can decide and build without re-interrogating the
    requester. Every line is provenance-tagged (connector discovery)."""
    slot = obj.slots.get("backend_context")
    if slot is None or not isinstance(slot.value, dict):
        return []
    ctx = slot.value
    entities = ctx.get("entities") or []
    if not entities:
        return []
    lines = ["", "## System context (auto-discovered)", "",
             f"_Discovered via {slot.source or 'system connectors'} after "
             "confirmation — the requester was never asked for any of this._", ""]
    for ent in entities:
        head = (f"### {ent.get('system_label') or ent.get('system')} — "
                f"{ent.get('label') or ent.get('entity')} "
                f"(`{ent.get('backend_name') or ent.get('entity')}`)")
        lines.append(head)
        if ent.get("description"):
            lines.append(f"{ent['description']}")
        if ent.get("matched_term"):
            lines.append(f"- Matched business term: \u201c{ent['matched_term']}\u201d")
        verified = "verified" if ent.get("verified") else "unverified (auto-discovered)"
        lines.append(f"- Knowledge-base status: {verified}")
        customizations = ent.get("customizations") or []
        if customizations:
            lines.append("- Customizations the requester was not asked about:")
            for c in customizations:
                owner = f" · owner: {c.get('owner_team')}" if c.get("owner_team") else ""
                lines.append(
                    f"  - `{c.get('name')}` ({c.get('type')}, {c.get('kind')}) — "
                    f"{c.get('description')}{owner}")
        lines.append("")
    return lines[:-1] if lines[-1] == "" else lines


def ticket_render(obj: RequirementObject, schema: SlotSchema) -> tuple[str, str]:
    """(title, markdown body) for target plugins."""
    outcome = obj.slots.get("business_outcome")
    title = _fmt(outcome.value) if outcome and outcome.value else obj.ask_verbatim
    title = title if len(title) <= 90 else title[:87] + "..."
    body = [f"# {title}", "",
            f"- Requirement: `{obj.req_id}` v{obj.version}",
            f"- Requester: {obj.requester.name} ({obj.requester.dept})",
            f"- Readiness at confirmation: {obj.readiness_score}", "",
            "## Slots", ""]
    for key, spec in schema.slots.items():
        if key in _SPECIAL_SLOTS:
            continue  # rendered as their own sections below
        slot = obj.slots.get(key)
        if slot is None or slot.value in (None, "", []):
            continue
        prov = slot.provenance.value if slot.provenance else "?"
        body.append(f"- **{spec.label}** ({prov}, {slot.confidence:.2f}): {_fmt(slot.value)}")
    cod = obj.slots.get("cost_of_delay")
    if cod and isinstance(cod.value, dict):
        body += ["", "## Value (auto)", "",
                 "_Priced deterministically from the requester's own words — "
                 "verify before using in a business case._", "",
                 f"- Estimated cost of doing nothing: **{value_agent.describe(cod.value)}**"]
    body += backend_context_section(obj)
    body += ["", "## Original ask (verbatim)", "", f"> {obj.ask_verbatim}"]
    if obj.assumptions:
        body += ["", "## Assumptions", ""]
        for key in obj.assumptions:
            slot = obj.slots.get(key)
            body.append(f"- {key} = {_fmt(slot.value) if slot else '?'} — "
                        f"{slot.default_reason if slot else ''}")
    return title, "\n".join(body)
