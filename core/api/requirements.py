"""Requirements router — latest, history, plain-language render, confirm."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from core.api.security import require_admin

from core.models import Confirmation, Provenance, Slot, Status, coerce_edit
from core.agents import acceptance, enrichment, impact, precedent, renderer
from core.export.manas_outbox import service as manas_service
from core.gates import pipeline, routing
from core.learning import exemplars as learning

logger = logging.getLogger("intakepilot.requirements")

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
    return {"business": renderer.business_render(
        obj, ctx.schema_for(obj.request_type))}


class RerouteBody(BaseModel):
    queue: str


async def apply_reroute(ctx, req_id: str, new_queue: str) -> dict:
    """Shared by the reroute endpoint and the GitHub webhook. The downstream
    team moving a ticket to another queue is the routing classifier's ground
    truth: it is logged (feeding routing_accuracy) and the requirement is
    re-indexed under the corrected queue so future similar asks route there."""
    from core.agents import precedent
    async with ctx.orchestrator.lock_for(req_id):
        try:
            obj = await ctx.store.latest(req_id)
        except KeyError:
            raise HTTPException(404, "requirement not found")
        if obj.status != Status.ROUTED:
            raise HTTPException(409, f"only routed requirements can be rerouted "
                                     f"(status is {obj.status.value})")
        old_queue = obj.routing.queue if obj.routing else None
        if old_queue == new_queue:
            return {"req_id": req_id, "changed": False, "queue": new_queue}
        obj.version += 1
        if obj.routing:
            obj.routing.queue = new_queue
        obj.touch("rerouted", f"{old_queue} -> {new_queue} (human signal)")
        await ctx.store.log("outcome_ledger", {
            "req_id": req_id, "stage": "reroute", "verdict": "changed",
            "detail": {"from": old_queue, "to": new_queue}})
        await ctx.store.put_version(obj)
        # Correct the precedent signal: future similar asks learn from this.
        await precedent.index_requirement(ctx.vector, obj, queue=new_queue)
        return {"req_id": req_id, "changed": True,
                "queue": new_queue, "previous": old_queue}


@router.post("/{req_id}/reroute", dependencies=[Depends(require_admin)])
async def reroute(req_id: str, body: RerouteBody, request: Request):
    """Ops/ticket-tool feedback channel (not session-bound: the signal comes
    from the assigned team's side). Guarded by INTAKEPILOT_ADMIN_TOKEN when
    configured; the GitHub webhook path is guarded by its HMAC secret."""
    return await apply_reroute(_ctx(request), req_id, body.queue.strip())


class AdjudicateBody(BaseModel):
    # The pack's closed sets — validated here so a typo is a 422, not a
    # rejected envelope.
    verdict: str                      # achieved | partially_achieved | not_achieved
    adjudicated_by_role: str          # business_owner | product_owner
    receipt: str                      # the human judgement, in their words (stays local)
    evidence: str | None = None       # what was looked at; hashed for the wire
    # Deployment attestation, originated by the delivery system and presented
    # here — IntakePilot never fabricates it. Optional: without it the
    # adjudication is recorded locally and the outbox logs why it stayed local.
    deployment_ref: str | None = None
    deployment_source_binding: str | None = None


@router.post("/{req_id}/adjudicate", dependencies=[Depends(require_admin)])
async def adjudicate(req_id: str, body: AdjudicateBody, request: Request):
    """The human judgement that the delivered result met the need — delivery
    status is not success. Terminal learning signal locally, and (when the
    outbox is enabled) the outcome.adjudicated.v1 event MANAS consumes."""
    ctx = _ctx(request)
    if body.verdict not in manas_service.VERDICTS:
        raise HTTPException(422, f"verdict must be one of {manas_service.VERDICTS}")
    if body.adjudicated_by_role not in manas_service.ADJUDICATOR_ROLES:
        raise HTTPException(422, f"adjudicated_by_role must be one of "
                                 f"{manas_service.ADJUDICATOR_ROLES}")
    if not body.receipt.strip():
        raise HTTPException(422, "receipt must not be empty")

    async with ctx.orchestrator.lock_for(req_id):
        obj = await _latest(ctx, req_id)
        if obj.status not in (Status.ROUTED, Status.BUILDING,
                              Status.IN_REVIEW, Status.DONE):
            raise HTTPException(409, "only routed or delivered requirements can "
                                     f"be adjudicated (status is {obj.status.value})")
        obj.version += 1
        obj.touch("adjudicated",
                  f"{body.verdict} by {body.adjudicated_by_role}")
        if body.verdict == "achieved":
            obj.status = Status.DONE
        await ctx.store.put_version(obj)

    await ctx.store.log("outcome_ledger", {
        "req_id": req_id, "stage": "adjudicated", "verdict": body.verdict,
        "detail": {"role": body.adjudicated_by_role,
                   "receipt": body.receipt,
                   "bucket": obj.context_bucket}})

    # change_ref continuity: reuse the routed ticket handle, never reconstruct.
    ticket_ref = None
    for row in await ctx.store.query_ledger("outcome_ledger", req_id=req_id,
                                            stage="routed"):
        ticket = (row.get("detail") or {}).get("ticket") or {}
        ticket_ref = ticket.get("ref") or ticket_ref
    outbox = await manas_service.record_outcome_adjudicated(
        ctx.store, obj, verdict=body.verdict, role=body.adjudicated_by_role,
        receipt_text=body.receipt, evidence_text=body.evidence or "",
        deployment_ref=body.deployment_ref,
        deployment_source_binding=body.deployment_source_binding,
        change_id=manas_service.change_id_from(ticket_ref, req_id))

    return {"req_id": req_id, "verdict": body.verdict,
            "status": obj.status.value,
            "outbox": ({"state": outbox["state"], "reason": outbox.get("reason")}
                       if outbox else {"state": "disabled"})}


class AttachBody(BaseModel):
    target_req_id: str


@router.post("/{req_id}/attach")
async def attach(req_id: str, body: AttachBody, request: Request):
    """Duplicate-merge: instead of leaving a gate-4-caught requirement parked
    as GATED, fold it into the existing one. The requirement closes as DONE
    with an auditable linkage; dedup is where intake earns its keep."""
    ctx = _ctx(request)
    await _authorize(ctx, request, req_id)
    if body.target_req_id == req_id:
        raise HTTPException(422, "cannot attach a requirement to itself")
    async with ctx.orchestrator.lock_for(req_id):
        obj = await _latest(ctx, req_id)
        if obj.status != Status.GATED:
            raise HTTPException(409, f"only gated requirements can be attached "
                                     f"(status is {obj.status.value})")
        try:
            await ctx.store.latest(body.target_req_id)
        except KeyError:
            raise HTTPException(404, "target requirement not found")
        obj.version += 1
        obj.status = Status.DONE
        obj.touch("attached", f"marked duplicate of {body.target_req_id}")
        await ctx.store.log("outcome_ledger", {
            "req_id": req_id, "stage": "attached", "verdict": "duplicate",
            "detail": {"target_req_id": body.target_req_id}})
        await ctx.store.put_version(obj)
        return {"draft": obj.model_dump(mode="json"),
                "attached_to": body.target_req_id}


class ConsentBody(BaseModel):
    stakeholder: str
    decision: str  # approve | object
    note: str | None = None


def _consent_status(rows: list[dict]) -> list[dict]:
    """Latest verdict per stakeholder (rows are insertion-ordered)."""
    latest: dict[str, dict] = {}
    for row in rows:
        detail = row.get("detail") or {}
        name = detail.get("stakeholder")
        if name:
            latest[name] = {"stakeholder": name, "status": row.get("verdict"),
                            "note": detail.get("note")}
    return list(latest.values())


@router.get("/{req_id}/consent", dependencies=[Depends(require_admin)])
async def consent_status(req_id: str, request: Request):
    """The countersign ledger: who was named, who approved, who objected."""
    ctx = _ctx(request)
    await _latest(ctx, req_id)  # 404 for unknown requirements
    rows = await ctx.store.query_ledger("outcome_ledger", req_id=req_id,
                                        stage="consent")
    entries = _consent_status(rows)
    return {"req_id": req_id, "stakeholders": entries,
            "objections": sum(1 for e in entries if e["status"] == "objected"),
            "pending": sum(1 for e in entries if e["status"] == "pending")}


@router.post("/{req_id}/consent", dependencies=[Depends(require_admin)])
async def countersign(req_id: str, body: ConsentBody, request: Request):
    """A named stakeholder approves or objects. Objections don't roll back
    routing in v0.1 — they land on the audit trail and the ledger, where the
    assigned team sees them before building."""
    decision = body.decision.strip().lower()
    if decision not in ("approve", "object"):
        raise HTTPException(422, "decision must be 'approve' or 'object'")
    ctx = _ctx(request)
    async with ctx.orchestrator.lock_for(req_id):
        obj = await _latest(ctx, req_id)
        rows = await ctx.store.query_ledger("outcome_ledger", req_id=req_id,
                                            stage="consent")
        named = {(r.get("detail") or {}).get("stakeholder") for r in rows}
        if body.stakeholder not in named:
            raise HTTPException(404, "stakeholder was not named on this requirement")
        verdict = "approved" if decision == "approve" else "objected"
        await ctx.store.log("outcome_ledger", {
            "req_id": req_id, "stage": "consent", "verdict": verdict,
            "detail": {"stakeholder": body.stakeholder,
                       "note": (body.note or "")[:300]}})
        obj.version += 1
        obj.touch(f"consent_{verdict}",
                  f"{body.stakeholder}" + (f": {body.note[:120]}" if body.note else ""))
        await ctx.store.put_version(obj)
    return {"req_id": req_id, "stakeholder": body.stakeholder, "status": verdict}


class ConfirmBody(BaseModel):
    edits: dict = {}
    confirmed_by: str | None = None


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
    schema = ctx.schema_for(obj.request_type)  # E: per-type slot schema
    if obj.status in (Status.ROUTED, Status.DONE):
        raise HTTPException(409, f"requirement already {obj.status.value}")

    obj.version += 1

    # 1. Edits: every human correction becomes an edit_diffs row + exemplar.
    edit_count = 0
    for key, corrected in body.edits.items():
        if key not in schema.slots:
            continue
        current = obj.slots.get(key)
        proposed = current.value if current else None
        corrected = coerce_edit(proposed, corrected)
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

    # I4: nemawashi, digitized — every named stakeholder gets a countersign
    # record. Non-blocking in v0.1 (routing proceeds), but objections are on
    # the record BEFORE the work starts, not discovered at UAT.
    stakeholders_slot = obj.slots.get("stakeholders")
    consent_pending: list[str] = []
    if stakeholders_slot and isinstance(stakeholders_slot.value, list):
        for name in stakeholders_slot.value:
            name = str(name).strip()
            if not name:
                continue
            consent_pending.append(name)
            await ctx.store.log("outcome_ledger", {
                "req_id": req_id, "stage": "consent", "verdict": "pending",
                "detail": {"stakeholder": name}})
        if consent_pending:
            obj.touch("consent_requested", ", ".join(consent_pending))
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
        obj, schema, await calibrated_weights(ctx.store, obj.context_bucket))
    gates = await pipeline.run_gates(ctx.llm, obj, schema, vector=ctx.vector)
    for g in gates:
        await ctx.store.log("outcome_ledger", {
            "req_id": req_id, "stage": f"gate{g.gate}",
            "verdict": "pass" if g.passed else "fail",
            "detail": {"reason": g.reason, "suggestion": g.suggestion}})

    # 3b. Portfolio impact: open requirements touching the same backend
    # entities. Not a gate — collisions don't block work, they connect the
    # people who would otherwise meet at the merge conflict.
    collision_hits = await impact.collisions(ctx.store, obj)
    if collision_hits:
        obj.touch("collisions_detected",
                  ", ".join(h["req_id"] for h in collision_hits))
        await ctx.store.log("outcome_ledger", {
            "req_id": req_id, "stage": "collision", "verdict": "detected",
            "detail": {"with": collision_hits}})

    # 4. Routing decision (always computed, for explainability).
    decision = await routing.classify(obj, ctx.cfg.routing_queues, ctx.vector)
    obj.routing = decision

    ticket = None
    acceptance_scenarios: list = []
    ticket_title = ticket_body = None
    if all(g.passed for g in gates):
        # I3: the third handoff artifact — checkable Given/When/Then generated
        # from the confirmed (gate-passed, therefore measurable) requirement.
        acceptance_scenarios = await acceptance.generate(ctx.llm, obj, schema)
        if acceptance_scenarios:
            await ctx.store.log("outcome_ledger", {
                "req_id": req_id, "stage": "acceptance", "verdict": "generated",
                "detail": {"count": len(acceptance_scenarios)}})
        ticket_title, ticket_body = renderer.ticket_render(obj, schema)
        ticket_body += impact.collision_section(collision_hits)
        ticket_body += acceptance.section(acceptance_scenarios)
        obj.status = Status.ROUTED
        # Re-index with the final slots AND the queue: this is the routing
        # classifier's precedent signal for future intakes.
        await precedent.index_requirement(ctx.vector, obj, queue=decision.queue)
        obj.touch("routed", f"queue={decision.queue}")
    else:
        obj.status = Status.GATED
        obj.touch("gated", "; ".join(
            f"gate{g.gate}: {g.reason}" for g in gates if not g.passed))

    # Persist the routed/gated version BEFORE external ticket create so a
    # target failure cannot leave an orphan ticket with no store row.
    await ctx.store.put_version(obj)

    if obj.status == Status.ROUTED and ticket_title is not None:
        try:
            ticket = await ctx.target.create_item(
                obj, ticket_title, ticket_body, decision.queue)
            await ctx.store.log("outcome_ledger", {
                "req_id": req_id, "stage": "routed", "verdict": "created",
                "detail": {"queue": decision.queue,
                           "ticket": ticket.model_dump()}})
        except Exception as exc:
            logger.exception("ticket create failed for %s: %s", req_id, exc)
            await ctx.store.log("outcome_ledger", {
                "req_id": req_id, "stage": "routed", "verdict": "ticket_failed",
                "detail": {"queue": decision.queue, "error": str(exc)[:300]}})
            ticket = None

    # Analyst learning evidence: what the analyst believed at the moment a
    # human confirmed. Feeds the signal-proposal miner (never auto-applied).
    if obj.analyst is not None:
        await ctx.store.log("outcome_ledger", {
            "req_id": req_id, "stage": "analyst",
            "verdict": obj.analyst.process.key if obj.analyst.process else "unplaced",
            "detail": {
                "bucket": obj.context_bucket,
                "ask": obj.ask_verbatim,
                "confidence": obj.analyst.process.confidence if obj.analyst.process else 0,
                "open_needs": [n.need for n in obj.analyst.unstated_needs
                               if n.status == "open"]}})

    # MANAS demand-lobe outbox (default-off): the exact version that went to
    # build, committed alongside the domain write. An external relay ships
    # pending rows; a rejection is an auditable row, never a failed confirm.
    if obj.status == Status.ROUTED:
        acceptance_text = acceptance.section(acceptance_scenarios)
        if not acceptance_text:
            sc = obj.slots.get("success_criteria")
            acceptance_text = str(sc.value) if sc and sc.value else ""
        await manas_service.record_requirement_versioned(
            ctx.store, obj,
            ticket_ref=ticket.ref if ticket else None,
            acceptance_text=acceptance_text)

    return {"draft": obj.model_dump(mode="json"),
            "gates": [g.model_dump() for g in gates],
            "routing": decision.model_dump(),
            "collisions": collision_hits,
            "acceptance": acceptance_scenarios,
            "consent": {"pending": consent_pending},
            "ticket": ticket.model_dump() if ticket else None}
