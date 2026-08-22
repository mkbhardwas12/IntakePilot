"""Backend Metadata Discovery — ADDENDUM-01 enrichment agent.

Runs AFTER confirmation and BEFORE gates/routing. Resolves business terms in
the confirmed ask to backend entities (glossary terms first, then raw
tokens/bigrams) through every configured SystemConnector, reads each entity's
schema INCLUDING customizations (SAP Z-fields, appends, custom columns), and:

  1. attaches the findings to the Requirement Object as the `backend_context`
     slot (provenance=retrieved, source=connector names) so the routed ticket
     carries everything the assigned team needs — no second interrogation;
  2. persists every discovery to the `system_kb` knowledge base (keyed upsert,
     evidence_count preserved, verified=False until a human validates) and to
     the vector index so the RETRIEVE ladder step serves future intakes.

Invariants (ADDENDUM-01 s.5): backend detail is discovered, never asked — the
`backend_context` slot is askable:false and this module runs only after the
question loop has ended; discoveries are auditable (audit event + provenance);
raw discovery never raises evidence_count (only human validation does, via
mark_validated).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from core.models import Provenance, RequirementObject, Slot
from core.export import manas_demand

_STOPWORDS = {
    "a", "an", "and", "as", "at", "be", "by", "for", "from", "i", "in", "info",
    "is", "it", "my", "need", "of", "on", "or", "our", "so", "that", "the",
    "this", "to", "we", "with", "x", "you",
}


def candidate_terms(text: str, glossary_hits: list[dict] | None = None) -> list[str]:
    """Deterministic term candidates: glossary hits (term + synonyms) first,
    then unigrams/bigrams/trigrams from the text. Connectors do exact matching
    against their synonym lists, so over-generating candidates is harmless."""
    terms: list[str] = []
    seen: set[str] = set()

    def add(term: str) -> None:
        t = term.strip().lower()
        if t and t not in seen:
            seen.add(t)
            terms.append(t)

    for hit in glossary_hits or []:
        add(hit["term"])
        for syn in (hit.get("maps_to") or {}).get("synonyms", []):
            add(str(syn))

    tokens = [t for t in re.findall(r"[a-z][a-z_-]+", text.lower())]
    for n in (3, 2, 1):
        for i in range(len(tokens) - n + 1):
            gram = tokens[i:i + n]
            if gram[0] in _STOPWORDS or gram[-1] in _STOPWORDS:
                continue
            add(" ".join(gram))
    return terms


async def enrich(obj: RequirementObject, store, vector, connectors,
                 glossary_hits: list[dict] | None = None) -> dict | None:
    """Discover backend context for a confirmed requirement. Mutates obj
    (backend_context slot + audit) and persists discoveries; returns the
    backend_context value, or None when nothing matched."""
    outcome = obj.slots.get("business_outcome")
    text = f"{obj.ask_verbatim} {outcome.value if outcome and outcome.value else ''}"
    terms = candidate_terms(text, glossary_hits)

    entities: list[dict] = []
    systems: list[str] = []
    seen: set[tuple[str, str]] = set()
    for conn in connectors:
        for term in terms:
            for match in await conn.resolve_entity(term):
                key = (match.system, match.entity)
                if key in seen:
                    continue
                seen.add(key)
                schema = await conn.describe_entity(match.entity)
                kb_row = await _persist_discovery(store, vector, schema)
                entities.append({
                    "system": schema.system,
                    "system_label": schema.system_label,
                    "entity": schema.entity,
                    "label": schema.label,
                    "backend_name": schema.backend_name,
                    "description": schema.description,
                    "matched_term": match.matched_term,
                    "verified": bool(kb_row.get("verified")),
                    "customizations": [c.model_dump() for c in schema.customizations],
                })
                if schema.system_label not in systems:
                    systems.append(schema.system_label)

    if not entities:
        obj.touch("enrichment_skipped", "no backend entities resolved")
        return None

    n_custom = sum(len(e["customizations"]) for e in entities)
    value = {"systems": systems, "entities": entities,
             "discovered_at": datetime.now(timezone.utc).isoformat()}
    sources = sorted({e["system"] for e in entities})
    obj.slots["backend_context"] = Slot(
        value=value, provenance=Provenance.RETRIEVED, confidence=0.85,
        source="connector:" + ",".join(sources))

    # A requirement that reached confirmation with affected_systems still open
    # (or thinner than the discovery) gets it filled here — never asked.
    current = obj.slots.get("affected_systems")
    known = list(current.value) if current and isinstance(current.value, list) else []
    merged = sorted(set(known) | set(systems))
    if merged != sorted(known):
        obj.slots["affected_systems"] = Slot(
            value=merged, provenance=current.provenance if known else Provenance.RETRIEVED,
            confidence=max(current.confidence if current else 0.0, 0.8),
            source=((current.source + ", ") if known and current and current.source else "")
                   + "connector:" + ",".join(sources))

    obj.touch("enriched",
              f"{len(entities)} entities, {n_custom} customization(s) "
              f"discovered via {', '.join(sources)}")
    
    implicated_fields = manas_demand.extract_implicated_fields(value)
    if implicated_fields:
        await manas_demand.emit_observed(
            obj.req_id, implicated_fields, obj.context_bucket)
    
    return value


async def _persist_discovery(store, vector, schema) -> dict:
    """Keyed upsert into system_kb. Preserves evidence_count/verified from any
    existing row — raw discovery never counts as evidence (ADDENDUM-01 s.5)."""
    existing = await store.query_ledger("system_kb", system=schema.system,
                                        entity=schema.entity)
    prior = existing[0] if existing else {}
    row = {
        "system": schema.system,
        "entity": schema.entity,
        "label": schema.label,
        "schema": schema.model_dump(),
        "evidence_count": prior.get("evidence_count", 1),
        "verified": prior.get("verified", 0) or 0,
        "last_refreshed": datetime.now(timezone.utc).isoformat(),
    }
    await store.log("system_kb", row)
    # Feed the RETRIEVE ladder: future intakes match on entity vocabulary.
    vocab = " ".join([schema.label, schema.backend_name, schema.entity,
                      *schema.synonyms])
    await vector.upsert(
        f"kb:{schema.system}:{schema.entity}",
        f"{vocab} {schema.description}",
        {"table": "system_kb", "system": schema.system,
         "entity": schema.entity, "system_label": schema.system_label})
    return row


async def mark_validated(store, system: str, entity: str) -> None:
    """Human-originated signal only: called when a routed ticket's team uses
    the discovery without correction. Raises evidence_count and verifies."""
    rows = await store.query_ledger("system_kb", system=system, entity=entity)
    if not rows:
        return
    row = rows[0]
    await store.log("system_kb", {
        **{k: row[k] for k in ("system", "entity", "label", "schema")},
        "evidence_count": (row.get("evidence_count") or 1) + 1,
        "verified": 1,
        "last_refreshed": datetime.now(timezone.utc).isoformat()})


async def refresh_system_kb(store, vector, connectors) -> int:
    """Recurring refresh (Section 7.3 nightly slot): re-scan connectors for
    changed customizations and update system_kb. Returns rows refreshed."""
    count = 0
    for conn in connectors:
        rows = await store.query_ledger("system_kb", system=conn.name)
        for row in rows:
            try:
                schema = await conn.describe_entity(row["entity"])
            except KeyError:
                continue  # entity gone; staleness policy demotes it elsewhere
            await _persist_discovery(store, vector, schema)
            count += 1
    return count
