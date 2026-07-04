"""Corrections-as-evals: the edit ledger IS an eval dataset.

Every `edit_diffs` row is a labeled triple (ask, model proposed, human
corrected) accumulated in production. Replaying the ledger against the
CURRENT prompt + exemplars + glossary answers three questions with zero
hand-written fixtures: is extraction accuracy improving over time, did a
prompt change regress anything, and how do two models compare on YOUR
domain. Evals write themselves; the golden-set drift problem disappears.

Run over HTTP (GET /api/evals/replay) or from cron:
    python -m core.learning.replay
"""
from __future__ import annotations

import json

from core.config import SlotSchema
from core.models import Budget, ExtractionError, RequirementObject
from core.agents import intake, precedent
from core.learning import exemplars


def _norm(value):
    if isinstance(value, str):
        return value.strip().lower()
    if isinstance(value, list):
        return sorted(_norm(v) for v in value)
    return value


def matches(got, expected) -> bool:
    """Tolerant equality: case/whitespace-insensitive, order-insensitive lists."""
    return _norm(got) == _norm(expected)


async def replay_corrections(store, vector, llm, schema: SlotSchema,
                             limit: int = 100) -> dict:
    """Replay the most recent `limit` corrections through today's extraction
    stack and score how often it now produces the human-corrected value."""
    rows = (await store.query_ledger("edit_diffs"))[-limit:]
    results: list[dict] = []
    for row in rows:
        try:
            src = await store.latest(row["req_id"])
        except KeyError:
            continue
        ask = src.ask_verbatim
        if not ask:
            continue
        fresh = RequirementObject(
            req_id=f"EVAL-{row['req_id']}", requester=src.requester,
            ask_verbatim=ask, question_budget=Budget(max=7, per_turn=3))
        exemplar_text = await exemplars.select_exemplars(
            vector, agent="intake", context=src.context_bucket, ask=ask, k=4)
        hits = await precedent.glossary_scan(store, ask)
        glossary_text = "".join(
            f"- “{h['term']}” maps to {h['maps_to']}\n" for h in hits)
        try:
            extraction = await intake.extract(
                llm, fresh, ask, exemplar_text, schema,
                glossary_hits=glossary_text)
        except ExtractionError as exc:
            results.append({"req_id": row["req_id"], "slot_key": row["slot_key"],
                            "matched": False, "error": str(exc)[:120]})
            continue
        got = (extraction.get(row["slot_key"]) or {}).get("value")
        results.append({
            "req_id": row["req_id"],
            "slot_key": row["slot_key"],
            "expected": row.get("corrected"),
            "got": got,
            "matched": matches(got, row.get("corrected")),
        })

    total = len(results)
    matched = sum(1 for r in results if r["matched"])
    by_slot: dict[str, dict] = {}
    for r in results:
        d = by_slot.setdefault(r["slot_key"], {"total": 0, "matched": 0})
        d["total"] += 1
        d["matched"] += 1 if r["matched"] else 0
    for d in by_slot.values():
        d["accuracy"] = round(d["matched"] / d["total"], 3)
    return {
        "model": getattr(llm, "name", "?"),
        "total": total,
        "matched": matched,
        "accuracy": round(matched / total, 3) if total else None,
        "by_slot": by_slot,
        "results": results,
    }


def main() -> None:  # pragma: no cover — thin CLI wrapper
    import asyncio

    from core.api.context import AppContext

    async def run() -> None:
        ctx = AppContext()
        report = await replay_corrections(ctx.store, ctx.vector, ctx.llm,
                                          ctx.schema)
        print(json.dumps(report, indent=2, default=str))

    asyncio.run(run())


if __name__ == "__main__":  # pragma: no cover
    main()
