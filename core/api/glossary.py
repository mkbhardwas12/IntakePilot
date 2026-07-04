"""Glossary router — admin view, correction-mined proposals, human accept.

Proposals are computed on demand from edit_diffs and NEVER auto-applied:
POST /api/glossary is the explicit human signal that turns a proposal (or
any term) into org vocabulary the retrieval ladder can use.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.learning import proposals as proposal_engine

router = APIRouter(prefix="/api/glossary", tags=["glossary"])


def _ctx(request: Request):
    return request.app.state.ctx


@router.get("")
async def list_glossary(request: Request):
    rows = await _ctx(request).store.query_ledger("glossary")
    return {"terms": rows}


@router.get("/proposals")
async def list_proposals(request: Request):
    """Recurring identical corrections that look like missing vocabulary."""
    return {"proposals": await proposal_engine.glossary_proposals(_ctx(request).store)}


class GlossaryBody(BaseModel):
    term: str
    maps_to: dict = {}


@router.post("")
async def accept_term(body: GlossaryBody, request: Request):
    """Human accept: write the term. 409 if it already exists — the learning
    loop owns updates to live terms (evidence_count etc.), not this endpoint."""
    term = body.term.strip().lower()
    if not term:
        raise HTTPException(422, "term must not be empty")
    ctx = _ctx(request)
    existing = await ctx.store.query_ledger("glossary", term=term)
    if existing:
        raise HTTPException(409, f"term '{term}' already exists")
    await ctx.store.log("glossary", {
        "term": term, "maps_to": body.maps_to, "evidence_count": 1,
        "last_confirmed": datetime.now(timezone.utc).isoformat()})
    return {"term": term, "maps_to": body.maps_to}
