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


# Slots given a dedicated place in the document; anything else filled lands
# under "Further details" so nothing silently disappears.
_SECTIONED = {"business_outcome", "scope_boundaries", "data_fields",
              "success_criteria", "stakeholders", "data_sensitivity",
              "urgency"} | set(_SPECIAL_SLOTS)


def _slot_line(obj: RequirementObject, schema: SlotSchema, key: str,
               label: str | None = None) -> str | None:
    slot = obj.slots.get(key)
    if slot is None or slot.value in (None, "", []):
        return None
    spec = schema.slots.get(key)
    shown = label or (spec.label if spec else key.replace("_", " ").title())
    suffix = ""
    if slot.provenance == Provenance.ASSUMED:
        suffix = f" _(assumed \u2014 {slot.default_reason or 'default applied'})_"
    elif slot.provenance == Provenance.RETRIEVED and slot.source:
        suffix = f" _(from {slot.source})_"
    return f"- **{shown}:** {_fmt(slot.value)}{suffix}"


def business_render(obj: RequirementObject, schema: SlotSchema) -> str:
    """A document a sponsor could sign \u2014 problem, analyst's read, scope,
    measures, risks and open decisions \u2014 not a slot dump. Every line
    traces to a slot with provenance or to the analyst's curated knowledge."""
    read = obj.analyst
    lines = [f"## Requirement {obj.req_id}", ""]

    lines += ["### Problem & objective", "",
              f"**Original ask (verbatim):** \u201c{obj.ask_verbatim}\u201d", ""]
    outcome = obj.slots.get("business_outcome")
    if outcome and outcome.value:
        lines += [f"**Objective:** {_fmt(outcome.value)}", ""]
    if read and read.interpretation:
        placed = f" _(placed in {read.process.label})_" if read.process else ""
        lines += [f"**Analyst's read:** {read.interpretation}{placed}", ""]

    scope = [_slot_line(obj, schema, "data_fields", "In scope (fields)"),
             _slot_line(obj, schema, "scope_boundaries", "Out of scope")]
    scope = [s for s in scope if s]
    if scope:
        lines += ["### Scope", "", *scope, ""]

    measures = [m for m in
                [_slot_line(obj, schema, "success_criteria", "Done when")] if m]
    if read and read.kpis:
        measures.append("- **The business will measure it by:** "
                        + ", ".join(read.kpis))
    if measures:
        lines += ["### Success measures", "", *measures, ""]

    people = [_slot_line(obj, schema, "stakeholders", "Stakeholders"),
              _slot_line(obj, schema, "data_sensitivity", "Data sensitivity")]
    people = [p for p in people if p]
    if people:
        lines += ["### People & sensitivity", "", *people, ""]

    timeline = [t for t in [_slot_line(obj, schema, "urgency", "Needed by")] if t]
    cod = obj.slots.get("cost_of_delay")
    if cod and isinstance(cod.value, dict):
        timeline.append(f"- **Cost of delay:** "
                        f"{value_agent.describe(cod.value)}")
    if timeline:
        lines += ["### Timeline & value", "", *timeline, ""]

    if read and read.risks:
        lines += ["### Known risks in this kind of work", ""]
        lines += [f"- {r.risk} \u2014 {r.why}" for r in read.risks]
        lines.append("")

    open_needs = [n for n in (read.unstated_needs if read else [])
                  if n.status == "open"]
    if open_needs:
        lines += ["### Open decisions (settle before build)", ""]
        for n in open_needs:
            evidence = (f" _(left open in {n.evidence_count} delivered "
                        "requirement(s) that missed the mark)_"
                        if n.evidence_count else "")
            lines.append(f"- {n.need} \u2014 {n.why}{evidence}")
        lines.append("")

    rest = [line for line in
            (_slot_line(obj, schema, key) for key in schema.slots
             if key not in _SECTIONED) if line]
    if rest:
        lines += ["### Further details", "", *rest, ""]

    if obj.assumptions:
        lines += [f"_{len(obj.assumptions)} assumption(s) applied \u2014 "
                  "review the assumption register before confirming._"]
    return "\n".join(lines).rstrip() + "\n"


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
