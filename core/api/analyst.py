"""Analyst router — the taxonomy's learning surface.

Proposals are mined on demand from the confirm-time analyst ledger and are
NEVER auto-applied: POST is the explicit human signal that a term becomes a
recognition signal. Mirrors the glossary loop.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from core.agents import analyst as analyst_agent
from core.api.security import require_admin
from core.learning import analyst_signals

router = APIRouter(prefix="/api/analyst", tags=["analyst"],
                   dependencies=[Depends(require_admin)])


def _ctx(request: Request):
    return request.app.state.ctx


@router.get("/proposals")
async def list_proposals(request: Request):
    """Vocabulary the taxonomy is missing, mined from confirmed asks."""
    return {"proposals": await analyst_signals.signal_proposals(_ctx(request).store)}


@router.get("/signals")
async def list_signals(request: Request):
    return {"signals": await analyst_signals.learned_signals(_ctx(request).store)}


class SignalBody(BaseModel):
    process: str
    signal: str
    accepted_by: str | None = None


@router.post("/signals")
async def accept_signal(body: SignalBody, request: Request):
    """Human accept: the term becomes a recognition signal for the process."""
    process = body.process.strip()
    signal = body.signal.strip().lower()
    if not signal:
        raise HTTPException(422, "signal must not be empty")
    know = analyst_agent.load_knowledge()["processes"]
    if process not in know:
        raise HTTPException(422, f"unknown process '{process}' — one of "
                                 f"{sorted(know)}")
    if signal in {s.lower() for s in know[process].get("signals", [])}:
        raise HTTPException(409, f"'{signal}' is already a curated signal "
                                 f"for {process}")
    ctx = _ctx(request)
    existing = await ctx.store.query_ledger("analyst_signals",
                                            process=process, signal=signal)
    if existing:
        raise HTTPException(409, f"'{signal}' is already accepted for {process}")
    await ctx.store.log("analyst_signals", {
        "process": process, "signal": signal,
        "accepted_by": body.accepted_by or "admin"})
    return {"process": process, "signal": signal}
