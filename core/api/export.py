"""Export router — the MANAS relay's read/ack surface over the outbox.

The transactional outbox keeps every envelope (pending, shipped, rejected)
next to the domain data; this is where an authenticated relay reads pending
rows and acknowledges what MANAS accepted. Admin-token guarded like the other
ops surfaces.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from core.api.security import require_admin

router = APIRouter(prefix="/api/export/outbox", tags=["export"],
                   dependencies=[Depends(require_admin)])


def _ctx(request: Request):
    return request.app.state.ctx


@router.get("")
async def list_outbox(request: Request, state: str | None = None):
    filters = {"state": state} if state else {}
    rows = await _ctx(request).store.query_ledger("manas_outbox", **filters)
    return {"items": rows}


class AckBody(BaseModel):
    outbox_id: str
    state: str          # shipped | dead_letter
    reason: str | None = None


@router.post("/ack")
async def acknowledge(body: AckBody, request: Request):
    """The relay's acknowledgement. Ledger rows are append-only, so an ack is
    a new row for the same outbox_id with the terminal state; readers take
    the latest state per outbox_id."""
    if body.state not in ("shipped", "dead_letter"):
        raise HTTPException(422, "state must be 'shipped' or 'dead_letter'")
    ctx = _ctx(request)
    rows = await ctx.store.query_ledger("manas_outbox", outbox_id=body.outbox_id)
    if not rows:
        raise HTTPException(404, "unknown outbox_id")
    original = rows[0]
    await ctx.store.log("manas_outbox", {
        "outbox_id": body.outbox_id,
        "req_id": original.get("req_id"),
        "event_type": original.get("event_type"),
        "content_hash": original.get("content_hash"),
        "envelope_json": None,
        "state": body.state,
        "reason": body.reason})
    return {"outbox_id": body.outbox_id, "state": body.state}
