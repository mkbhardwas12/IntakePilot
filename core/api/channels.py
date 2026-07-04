"""Channel adapter — intake where people already are (G).

One generic inbound endpoint that any Slack bot, Teams flow, or mail handler
can call server-to-server: it maps an external conversation id to a session
deterministically, runs the normal turn loop, and returns a plain-text
`reply` the bot posts verbatim. Typing `confirm` completes the flow. The SSE
web UI remains the analyst view; this is the requester's doorway.

Guarded by INTAKEPILOT_ADMIN_TOKEN (a bot credential, not an end-user one).
Note: chat has no answer chips — replies flow through extraction, so pending
questions may be logged as skipped even when the text answers them.
"""
from __future__ import annotations

import hashlib
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from core.models import Requester, Status
from core.api.requirements import ConfirmBody, _confirm_locked
from core.api.security import require_admin
from core.api.sessions import TurnBody, _run_turn

router = APIRouter(prefix="/api/channels", tags=["channels"],
                   dependencies=[Depends(require_admin)])


class InboundBody(BaseModel):
    channel: str = "chat"        # slack | teams | mail | ...
    external_id: str             # stable conversation key, e.g. "U123:C456"
    text: str
    user: dict = {}              # optional {name, dept, role}


def _session_id(channel: str, external_id: str) -> str:
    return "ch" + hashlib.sha1(f"{channel}:{external_id}".encode()).hexdigest()[:10]


def _format_turn_reply(result) -> str:
    lines = [f"Draft {result.draft.req_id} — readiness "
             f"{result.draft.readiness_score}/100."]
    if result.degraded:
        lines.insert(0, "I couldn't fully process that, so I kept the draft as it was.")
    for i, q in enumerate(result.questions, 1):
        opts = f" (options: {', '.join(q.options)})" if q.options else ""
        lines.append(f"{i}. {q.text}{opts}")
    if result.questions:
        lines.append("Answer by number, e.g. \"1: this week\".")
    if result.confirm_unlocked:
        lines.append("Looks ready — reply 'confirm' to submit, "
                     "or keep adding detail.")
    elif not result.questions:
        lines.append("Keep describing the need — I'll draft as you type.")
    return "\n".join(lines)


def _format_confirm_reply(confirm: dict) -> str:
    draft = confirm["draft"]
    if draft["status"] == "routed":
        ticket = confirm.get("ticket") or {}
        return (f"Routed to “{confirm['routing']['queue']}” — "
                f"{confirm['routing']['explanation']} "
                f"Ticket: {ticket.get('ref', 'created')}.")
    failed = [g for g in confirm["gates"] if not g["passed"]]
    lines = ["Not routed yet — quality gates flagged:"]
    lines += [f"- Gate {g['gate']} ({g['name']}): {g['reason']}" for g in failed]
    dup = next((g["meta"].get("duplicate_of") for g in failed
                if g.get("meta", {}).get("duplicate_of")), None)
    if dup:
        lines.append(f"This looks like a duplicate of {dup} — an analyst can "
                     "attach it in the review UI.")
    return "\n".join(lines)


@router.post("/inbound")
async def inbound(body: InboundBody, request: Request):
    ctx = request.app.state.ctx
    if not body.text.strip():
        raise HTTPException(422, "text must not be empty")

    session_id = _session_id(body.channel, body.external_id)
    session = await ctx.store.get_session(session_id)
    if session is None:
        requester = Requester(**{k: v for k, v in body.user.items()
                                 if k in ("id", "name", "dept", "role")})
        session, _ = await ctx.start_session(requester, session_id=session_id)

    req_id = session["req_id"]

    if body.text.strip().lower() == "confirm":
        obj = await ctx.store.latest(req_id)
        if obj.status in (Status.ROUTED, Status.DONE):
            return {"session_id": session_id, "req_id": req_id,
                    "reply": f"{req_id} is already {obj.status.value}.",
                    "status": obj.status.value}
        async with ctx.orchestrator.lock_for(req_id):
            confirm = await _confirm_locked(ctx, req_id, ConfirmBody())
        return {"session_id": session_id, "req_id": req_id,
                "reply": _format_confirm_reply(confirm),
                "status": confirm["draft"]["status"]}

    # Chat has no answer chips: lines like "1: this week" map to the pending
    # question with that number; everything else flows through extraction.
    answers, free_lines = [], []
    pending = session.get("pending_questions", [])
    for line in body.text.splitlines():
        m = re.match(r"\s*(\d+)\s*[:.)\-]\s*(.+)", line)
        if m and 1 <= int(m.group(1)) <= len(pending):
            q = pending[int(m.group(1)) - 1]
            answers.append({"question_id": q["id"], "slot_key": q["slot_key"],
                            "value": m.group(2).strip()})
        else:
            free_lines.append(line)

    result = await _run_turn(ctx, session, TurnBody(
        message="\n".join(free_lines).strip(), answers=answers))
    return {
        "session_id": session_id,
        "req_id": req_id,
        "reply": _format_turn_reply(result),
        "readiness": result.draft.readiness_score,
        "confirm_unlocked": result.confirm_unlocked,
        "questions": [q.model_dump() for q in result.questions],
        "status": result.draft.status.value,
    }
