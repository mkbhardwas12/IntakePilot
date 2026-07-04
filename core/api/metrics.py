"""Metrics router — Section 9 metrics computed from the ledgers, no extra
instrumentation. This endpoint is both the ROI report and the public proof."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api", tags=["metrics"])


def _routing_accuracy(routed_ids: set, outcome_rows: list[dict]) -> float | None:
    if not routed_ids:
        return None
    rerouted = {r["req_id"] for r in outcome_rows if r["stage"] == "reroute"}
    return round((len(routed_ids) - len(rerouted & routed_ids))
                 / len(routed_ids), 3)


def _escalation_metrics(ctx, outcome_rows: list[dict]) -> dict:
    events = sum(1 for r in outcome_rows if r["stage"] == "escalation")
    stats = getattr(ctx.llm, "stats", None)
    rate = (round(stats["escalations"] / stats["validated_calls"], 3)
            if stats and stats["validated_calls"] else None)
    return {
        "enabled": stats is not None,
        "events": events,                      # durable (outcome_ledger)
        "rate_since_start": rate,              # escalations / validated calls
        "rescues_since_start": stats["rescues"] if stats else None,
    }


def _parse(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


@router.get("/metrics")
async def metrics(request: Request):
    ctx = request.app.state.ctx
    store = ctx.store

    sessions = await store.list_sessions()
    edit_rows = await store.query_ledger("edit_diffs")
    question_rows = await store.query_ledger("question_ledger")
    outcome_rows = await store.query_ledger("outcome_ledger")
    kb_rows = await store.query_ledger("system_kb")

    routed_rows = [r for r in outcome_rows if r["stage"] == "routed"]
    routed_ids = {r["req_id"] for r in routed_rows}

    confirmed_ids = set()
    latencies: list[float] = []
    assumed, filled = 0, 0
    for session in sessions:
        req_id = session["req_id"]
        try:
            obj = await store.latest(req_id)
        except KeyError:
            continue
        if obj.confirmation is not None:
            confirmed_ids.add(req_id)
            assumed += len(obj.assumptions)
            filled += sum(1 for s in obj.slots.values()
                          if s.value not in (None, "", []))
        if req_id in routed_ids:
            stamps = await store.version_timestamps(req_id)
            if stamps:
                first = _parse(stamps[0][1])
                last = _parse(stamps[-1][1])
                if first and last:
                    latencies.append((last - first).total_seconds())

    intakes = len(sessions)
    confirmed = len(confirmed_ids)
    questions_asked = sum(1 for r in question_rows
                          if r["outcome"] in ("answered", "skipped", "dont_know"))

    per_field: dict[str, int] = {}
    for r in edit_rows:
        per_field[r["slot_key"]] = per_field.get(r["slot_key"], 0) + 1
    edit_rate_per_field = ({k: round(v / confirmed, 3) for k, v in per_field.items()}
                           if confirmed else {})

    gate4 = [r for r in outcome_rows if r["stage"] == "gate4"]
    duplicate_catch_rate = (round(sum(1 for r in gate4 if r["verdict"] == "fail")
                                  / len(gate4), 3) if gate4 else None)

    return {
        "totals": {
            "intakes": intakes,
            "confirmed": confirmed,
            "routed": len(routed_ids),
            "edits": len(edit_rows),
            "questions_asked": questions_asked,
        },
        "intake_latency_seconds_avg": (round(sum(latencies) / len(latencies), 1)
                                       if latencies else None),
        "questions_per_intake_avg": (round(questions_asked / confirmed, 2)
                                     if confirmed else None),
        "edit_rate_per_field": edit_rate_per_field,
        # Ground truth from the ticket tool: reroutes (manual endpoint or
        # GitHub webhook) mean the classifier picked the wrong queue.
        "routing_accuracy": _routing_accuracy(routed_ids, outcome_rows),
        "duplicate_catch_rate": duplicate_catch_rate,
        "analyst_hours_displaced": round(
            confirmed * ctx.cfg.analyst_baseline_hours, 1),
        "assumption_rate": round(assumed / filled, 3) if filled else None,
        # Hybrid model strategy: how often the primary model needed the
        # stronger tier. The pitch says this tapers as exemplars accumulate —
        # this is where that claim becomes measurable.
        "escalation": _escalation_metrics(ctx, outcome_rows),
        # ADDENDUM-01: the backend knowledge base grows with every discovery.
        "system_kb": {
            "entities": len(kb_rows),
            "customizations": sum(
                len((r.get("schema") or {}).get("customizations", []))
                for r in kb_rows),
            "verified": sum(1 for r in kb_rows if r.get("verified")),
        },
    }
