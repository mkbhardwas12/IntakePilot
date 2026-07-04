"""Impact-graph router — the portfolio view over open requirements."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from core.agents import impact
from core.api.security import require_admin

router = APIRouter(prefix="/api/graph", tags=["impact"],
                   dependencies=[Depends(require_admin)])


@router.get("")
async def impact_graph(request: Request):
    """Requirements, the backend entities they touch, and the hotspots
    (entities with more than one open requirement on them)."""
    return await impact.graph(request.app.state.ctx.store)
