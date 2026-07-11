"""Admin triage queue — recent routed/gated/confirmed requirements."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from core.api.security import require_admin
from core.models import Status

router = APIRouter(prefix="/api/triage", tags=["triage"],
                   dependencies=[Depends(require_admin)])

_TRIAGE_STATUSES = {Status.ROUTED, Status.GATED, Status.CONFIRMED}


def _ctx(request: Request):
    return request.app.state.ctx


def _title_hint(obj) -> str:
    outcome = obj.slots.get("business_outcome")
    if outcome and isinstance(outcome.value, str) and outcome.value.strip():
        return outcome.value.strip()[:120]
    return (obj.ask_verbatim or "")[:120]


@router.get("")
async def list_triage(request: Request, limit: int = 50):
    ctx = _ctx(request)
    sessions = await ctx.store.list_sessions()
    items: list[dict] = []
    seen: set[str] = set()
    # Prefer most recently updated sessions first.
    sessions = sorted(
        sessions,
        key=lambda s: s.get("updated_at") or s.get("created_at") or "",
        reverse=True)
    for session in sessions:
        req_id = session.get("req_id")
        if not req_id or req_id in seen:
            continue
        seen.add(req_id)
        try:
            obj = await ctx.store.latest(req_id)
        except KeyError:
            continue
        if obj.status not in _TRIAGE_STATUSES:
            continue
        ask = (obj.ask_verbatim or "").strip()
        items.append({
            "req_id": req_id,
            "status": obj.status.value,
            "queue": obj.routing.queue if obj.routing else None,
            "title_hint": _title_hint(obj),
            "readiness_score": obj.readiness_score,
            "ask_verbatim": ask if len(ask) <= 160 else ask[:159] + "…",
        })
        if len(items) >= max(1, min(limit, 200)):
            break
    return {"items": items}


@router.post("/{req_id}/clone")
async def clone_from_triage(req_id: str, request: Request):
    """Admin clone — no session ownership required (triage is ops-side)."""
    from core.api.share import clone_from_obj
    ctx = _ctx(request)
    try:
        obj = await ctx.store.latest(req_id)
    except KeyError:
        from fastapi import HTTPException
        raise HTTPException(404, "requirement not found")
    return await clone_from_obj(ctx, obj)
