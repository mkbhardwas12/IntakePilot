"""System-KB router — closes the ADDENDUM-01 human-validation loop.

Before this router existed, `mark_validated` and `refresh_system_kb` were
reachable only from tests: `verified` stayed false and `evidence_count`
stayed 1 forever. Now the assigned team (or a ticket-tool webhook) can
confirm a discovery was correct, and an operator (or scheduler) can trigger
the recurring connector re-scan.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from core.agents import enrichment

router = APIRouter(prefix="/api/kb", tags=["system-kb"])


def _ctx(request: Request):
    return request.app.state.ctx


@router.get("")
async def list_kb(request: Request):
    """The knowledge base as the ops/admin view sees it."""
    rows = await _ctx(request).store.query_ledger("system_kb")
    return {"entities": [
        {"system": r["system"], "entity": r["entity"], "label": r.get("label"),
         "verified": bool(r.get("verified")), "evidence_count": r.get("evidence_count"),
         "last_refreshed": r.get("last_refreshed"),
         "customizations": len((r.get("schema") or {}).get("customizations", []))}
        for r in rows]}


@router.post("/{system}/{entity}/validate")
async def validate_entity(system: str, entity: str, request: Request):
    """Human signal: the routed ticket's team used this discovery without
    correction. Bumps evidence_count and marks the row verified."""
    ctx = _ctx(request)
    rows = await ctx.store.query_ledger("system_kb", system=system, entity=entity)
    if not rows:
        raise HTTPException(404, "unknown system/entity")
    await enrichment.mark_validated(ctx.store, system, entity)
    updated = (await ctx.store.query_ledger("system_kb", system=system, entity=entity))[0]
    return {"system": system, "entity": entity, "verified": bool(updated["verified"]),
            "evidence_count": updated["evidence_count"]}


@router.post("/refresh")
async def refresh(request: Request):
    """Recurring connector re-scan (spec 7.3 nightly slot). Call from cron/
    scheduler in production; returns how many rows were re-described."""
    ctx = _ctx(request)
    refreshed = await enrichment.refresh_system_kb(ctx.store, ctx.vector, ctx.connectors)
    return {"refreshed": refreshed}
