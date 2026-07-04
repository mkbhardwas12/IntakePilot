"""Evals router — corrections-as-evals over the live ledgers."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from core.api.security import require_admin
from core.learning import replay

# Admin-guarded: replay runs real LLM completions — an expensive-compute
# endpoint nobody anonymous should be able to hammer.
router = APIRouter(prefix="/api/evals", tags=["evals"],
                   dependencies=[Depends(require_admin)])


@router.get("/replay")
async def replay_endpoint(request: Request,
                          limit: int = Query(default=100, ge=1, le=1000)):
    """Replay recent human corrections through the current extraction stack.
    `accuracy` trending up over time is the learning loop, measured."""
    ctx = request.app.state.ctx
    return await replay.replay_corrections(ctx.store, ctx.vector, ctx.llm,
                                           ctx.schema_for, limit=limit)
