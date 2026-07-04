"""Requirements router — latest, history, plain-language render, confirm."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.models import Confirmation, Provenance, Slot, Status
from core.agents import enrichment, precedent, renderer
from core.gates import pipeline, routing
from core.learning import exemplars as learning

router = APIRouter(prefix="/api/requirements", tags=["requirements"])


def _ctx(request: Request):
    return request.app.state.ctx


async def _latest(ctx, req_id: str):
    try:
        return await ctx.store.latest(req_id)
    except KeyError:
        raise HTTPException(404, "requirement not found")


async def _authorize(ctx, request: Request, req_id: str) -> None:
    """Requirements are session-bound. IDs are sequential (IPR-{year}-{seq}),
    so without this check anyone could enumerate all requirements — or worse,
    confirm someone else's draft. The caller must present the X-Session-Id of
    the session that created the requirement. Wrong or unknown pairs return
    404 (not 403) so the endpoint leaks nothing about which IDs exist."""
    session_id = request.headers.get("X-Session-Id")
    if not session_id:
        raise HTTPException(401, "X-Session-Id header required")
    session = await ctx.store.get_session(session_id)
    if session is None or session.get("req_id") != req_id:
        raise HTTPException(404, "requirement not found")


@router.get("/{req_id}")
async def get_requirement(req_id: str, request: Request):
    ctx = _ctx(request)
    await _authorize(ctx, request, req_id)
    obj = await _latest(ctx, req_id)
    return obj.model_dump(mode="json")


@router.get("/{req_id}/history")
async def get_history(req_id: str, request: Request):
    ctx = _ctx(request)
    await _authorize(ctx, request, req_id)
    history = await ctx.store.history(req_id)
    if not history:
        raise HTTPException(404, "requirement not found")
    return [o.model_dump(mode="json") for o in history]


@router.get("/{req_id}/render")
async def get_render(req_id: str, request: Request):
    ctx = _ctx(request)
    await _authorize(ctx, request, req_id)
    obj = await _latest(ctx, req_id)
    return {"business": renderer.business_render(obj, ctx.schema)}


class ConfirmBody(BaseModel):
    edits: dict = {}
    confirmed_by: str | None = None


def _coerce_edit(proposed, corrected):
    """UI edit fields are strings; restore the slot's original type so a
    list-valued slot edited as "a, b" doesn't become one string, and numeric
    slots don't silently become text."""
    if not isinstance(corrected, str):
        return corrected
    if isinstance(proposed, list):
        return [part.strip() for part in corrected.split(",") if part.strip()]
    if isinstance(proposed, bool):
        return corrected.strip().lower() in ("true", "yes", "1")
    if isinstance(proposed, (int, float)):
        try:
            num = float(corrected)
            return int(num) if num.is_integer() and isinstance(proposed, int) else num
        except ValueError:
            return corrected
    return corrected


@router.post("/{req_id}/confirm")
async def confirm(req_id: str, body: ConfirmBody, request: Request):
    """Confirm -> capture edit diffs (the learning asset) -> gates -> routing
    -> ticket. Gate failures never mutate the object; they park it as GATED.
    Runs under the same per-requirement lock as turns, so a confirm can never
    race an in-flight turn or a second confirm (which previously created a
    ticket and then 500'd on the append-only version write)."""
    ctx = _ctx(request)
    await _authorize(ctx, request, req_id)
    async with ctx.orchestrator.lock_for(req_id):
        return await _confirm_locked(ctx, req_id, body)


async def _confirm_locked(ctx, req_id: str, body: ConfirmBody):
    obj = await _latest(ctx, req_id)
    if obj.status in (Status.ROUTED, Status.DONE):
        raise HTTPException(409, f"requirement already {obj.status.value}")

    obj.version += 1

    # 1. Edits: every human correction becomes an edit_diffs row + exemplar.
    edit_count = 0
    for key, corrected in body.edits.items():
        if key not in ctx.schema.slots:
            continue
        current = obj.slots.get(key)
        proposed = current.value if current else None
        corrected = _coerce_edit(proposed, corrected)
        if proposed == corrected:
            continue
        await learning.capture_edit(
            ctx.store, ctx.vector, obj, key, proposed, corrected,
            provenance=(current.provenance.value
                        if current and current.provenance else None))
        obj.slots[key] = Slot(value=corrected, provenance=Provenance.EDITED,
                              confidence=1.0, source="confirmation_edit")
        if key in obj.assumptions:
            obj.assumptions.remove(key)
        edit_count += 1
        obj.touch("slot_edited", f"{key}: {proposed!r} -> {corrected!r}")

    obj.confirmation = Confirmation(
        confirmed_by=body.confirmed_by or obj.requester.name, edits=edit_count)
    obj.status = Status.CONFIRMED
    obj.touch("confirmed", f"{edit_count} edit(s) at confirmation")
    # Denominator for readiness calibration (edit rate per provenance needs
    # to know how many confirmations happened in this bucket).
    await ctx.store.log("outcome_ledger", {
        "req_id": req_id, "stage": "confirmed", "verdict": "ok",
        "detail": {"bucket": obj.context_bucket, "edits": edit_count}})

    # 2. Backend Metadata Discovery (ADDENDUM-01): after confirmation, before
    # gates/routing. Discovers entities + customizations the requester was
    # never asked about; persists them to system_kb for future intakes.
    glossary_hits = await precedent.glossary_scan(ctx.store, obj.ask_verbatim)
    await enrichment.enrich(obj, ctx.store, ctx.vector, ctx.connectors,
                            glossary_hits=glossary_hits)

    # 3. Gates (pure functions; failures logged, object never mutated by them).
    from core.agents.orchestrator import calibrated_weights, readiness
    obj.readiness_score = readiness(
        obj, ctx.schema, await calibrated_weights(ctx.store, obj.context_bucket))
    gates = await pipeline.run_gates(ctx.llm, obj, ctx.schema, vector=ctx.vector)
    for g in gates:
        await ctx.store.log("outcome_ledger", {
            "req_id": req_id, "stage": f"gate{g.gate}",
            "verdict": "pass" if g.passed else "fail",
            "detail": {"reason": g.reason, "suggestion": g.suggestion}})

    # 4. Routing decision (always computed, for explainability).
    decision = await routing.classify(obj, ctx.cfg.routing_queues, ctx.vector)
    obj.routing = decision

    ticket = None
    if all(g.passed for g in gates):
        title, ticket_body = renderer.ticket_render(obj, ctx.schema)
        ticket = await ctx.target.create_item(obj, title, ticket_body, decision.queue)
        obj.status = Status.ROUTED
        # Re-index with the final slots AND the queue: this is the routing
        # classifier's precedent signal for future intakes.
        await precedent.index_requirement(ctx.vector, obj, queue=decision.queue)
        obj.touch("routed", f"queue={decision.queue} ticket={ticket.ref}")
        await ctx.store.log("outcome_ledger", {
            "req_id": req_id, "stage": "routed", "verdict": "created",
            "detail": {"queue": decision.queue, "ticket": ticket.model_dump()}})
    else:
        obj.status = Status.GATED
        obj.touch("gated", "; ".join(
            f"gate{g.gate}: {g.reason}" for g in gates if not g.passed))

    await ctx.store.put_version(obj)
    return {"draft": obj.model_dump(mode="json"),
            "gates": [g.model_dump() for g in gates],
            "routing": decision.model_dump(),
            "ticket": ticket.model_dump() if ticket else None}
