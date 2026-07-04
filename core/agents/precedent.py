"""Precedent engine — the RETRIEVE step of the Gap Resolution Ladder.

Three sources, in order: the glossary (org term -> systems/team ontology),
the system_kb knowledge base (ADDENDUM-01: discovered backend entities and
customizations), and similarity search over past requirements.
"""
from __future__ import annotations

from core.config import SlotSchema
from core.models import Provenance, RequirementObject, Slot
from core.agents.gap_analyzer import is_empty

PRECEDENT_MIN_SCORE = 0.55


async def glossary_scan(store, text: str) -> list[dict]:
    """Glossary terms appearing verbatim in the text (case-insensitive)."""
    rows = await store.query_ledger("glossary")
    low = text.lower()
    return [r for r in rows
            if not r["term"].startswith("dept:") and r["term"].lower() in low]


async def system_kb_scan(store, text: str) -> list[dict]:
    """system_kb entities whose vocabulary (label, synonyms, backend name)
    appears in the text — discoveries from past intakes serving new ones."""
    rows = await store.query_ledger("system_kb")
    low = text.lower()
    hits = []
    for row in rows:
        schema = row.get("schema") or {}
        vocab = {str(schema.get("label", "")).lower(),
                 str(schema.get("entity", "")).lower(),
                 *(str(s).lower() for s in schema.get("synonyms", []))}
        if any(v and v in low for v in vocab):
            hits.append(row)
    return hits


async def retrieve_pass(obj: RequirementObject, gaps: list[str], store, vector,
                        schema: SlotSchema) -> tuple[list[str], list[dict]]:
    """Precedent + glossary retrieval. Returns (remaining gaps, glossary hits)."""
    hits = await glossary_scan(store, obj.ask_verbatim)
    if "affected_systems" in gaps:
        systems: list[str] = []
        sources: list[str] = []
        for hit in hits:
            systems += (hit.get("maps_to") or {}).get("systems", [])
            sources.append(f"glossary:{hit['term']}")
        if systems:
            obj.slots["affected_systems"] = Slot(
                value=sorted(set(systems)), provenance=Provenance.RETRIEVED,
                confidence=0.75, source=", ".join(sources))

    # ADDENDUM-01: past discoveries fill backend_context (and affected_systems)
    # at intake time — the system never re-learns the same fact.
    if is_empty(obj.slots.get("backend_context")) and "backend_context" in schema.slots:
        kb_hits = await system_kb_scan(store, obj.ask_verbatim)
        if kb_hits:
            entities = []
            kb_systems: list[str] = []
            for row in kb_hits:
                s = row.get("schema") or {}
                entities.append({
                    "system": row["system"], "system_label": s.get("system_label", row["system"]),
                    "entity": row["entity"], "label": s.get("label", row["entity"]),
                    "backend_name": s.get("backend_name", ""),
                    "description": s.get("description", ""),
                    "matched_term": "", "verified": bool(row.get("verified")),
                    "customizations": s.get("customizations", []),
                })
                label = s.get("system_label", row["system"])
                if label not in kb_systems:
                    kb_systems.append(label)
            obj.slots["backend_context"] = Slot(
                value={"systems": kb_systems, "entities": entities},
                provenance=Provenance.RETRIEVED, confidence=0.7,
                source="system_kb:" + ",".join(sorted({r["system"] for r in kb_hits})))
            if is_empty(obj.slots.get("affected_systems")):
                obj.slots["affected_systems"] = Slot(
                    value=sorted(kb_systems), provenance=Provenance.RETRIEVED,
                    confidence=0.7, source="system_kb")

    gaps = [k for k in gaps if is_empty(obj.slots.get(k))]
    if gaps:
        similar = await vector.search(obj.ask_verbatim, k=3,
                                      filter={"table": "requirements"})
        for hit in similar:
            if hit.score < PRECEDENT_MIN_SCORE or hit.meta.get("req_id") == obj.req_id:
                continue
            for key in list(gaps):
                value = (hit.meta.get("slots") or {}).get(key)
                if value not in (None, "", []):
                    obj.slots[key] = Slot(
                        value=value, provenance=Provenance.RETRIEVED,
                        confidence=round(0.6 * hit.score + 0.2, 2),
                        source=f"precedent:{hit.meta.get('req_id')}")
            gaps = [k for k in gaps if is_empty(obj.slots.get(k))]
    return gaps, hits


async def index_requirement(vector, obj: RequirementObject,
                            queue: str | None = None) -> None:
    """Index the requirement for precedent retrieval, gate-4 duplicate
    candidates, and — once routed (queue set) — the routing precedent signal."""
    outcome = obj.slots.get("business_outcome")
    text = obj.ask_verbatim + " " + str(outcome.value if outcome else "")
    slot_values = {k: s.value for k, s in obj.slots.items() if s.value not in (None, "", [])}
    meta = {"table": "requirements", "req_id": obj.req_id,
            "status": obj.status.value, "slots": slot_values}
    if queue:
        meta["queue"] = queue
    await vector.upsert(f"req:{obj.req_id}", text, meta)
