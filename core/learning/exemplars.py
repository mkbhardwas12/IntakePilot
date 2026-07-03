"""Learning v1 (spec 7.1/7.2): capture edit diffs at confirmation, select
relevance-ranked past corrections, and inject them into the extract prompt.

Only human-originated signals enter the ledgers (spec Section 11).
"""
from __future__ import annotations

from datetime import datetime, timezone

STALENESS_DAYS = 180


async def capture_edit(store, vector, obj, slot_key: str,
                       proposed, corrected) -> None:
    """One edit_diffs row + one vector entry per human correction — THE learning asset."""
    row = {
        "req_id": obj.req_id,
        "version": obj.version,
        "slot_key": slot_key,
        "proposed": proposed,
        "corrected": corrected,
        "context_bucket": obj.context_bucket,
    }
    await store.log("edit_diffs", row)
    await vector.upsert(
        f"edit:{obj.req_id}:{obj.version}:{slot_key}",
        obj.ask_verbatim,
        {"table": "edit_diffs", "context_bucket": obj.context_bucket,
         "slot_key": slot_key, "proposed": proposed, "corrected": corrected,
         "ask_snippet": obj.ask_verbatim[:120],
         "created_at": datetime.now(timezone.utc).isoformat()})


async def select_exemplars(vector, agent: str, context: str, ask: str, k: int = 4) -> str:
    """Relevance-ranked past corrections, injected into prompts (spec 7.2).
    Filtered to the same context_bucket (tenancy isolation — SPEC-REVIEW #2),
    deduped to max 2 per slot_key, stale corrections dropped."""
    hits = await vector.search(ask, k=k * 3, filter={
        "table": "edit_diffs", "context_bucket": context})

    per_slot: dict[str, int] = {}
    deduped = []
    for h in hits:
        key = h.meta.get("slot_key", "?")
        if per_slot.get(key, 0) >= 2:
            continue
        per_slot[key] = per_slot.get(key, 0) + 1
        deduped.append(h)

    now = datetime.now(timezone.utc)
    fresh = []
    for h in deduped:
        created = h.meta.get("created_at")
        if created:
            try:
                age = (now - datetime.fromisoformat(created)).days
                if age >= STALENESS_DAYS:
                    continue
            except ValueError:
                pass
        fresh.append(h)

    return format_as_examples(fresh[:k])


def format_as_examples(hits) -> str:
    if not hits:
        return ""
    lines = []
    for h in hits:
        m = h.meta
        lines.append(
            f"- For an ask like \u201c{m.get('ask_snippet', '')}\u201d, the draft "
            f"proposed {m.get('slot_key')}={m.get('proposed')!r}; the human "
            f"corrected it to {m.get('corrected')!r}.")
    return "\n".join(lines)
