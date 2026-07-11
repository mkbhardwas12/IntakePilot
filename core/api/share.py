"""Public share links — read-only cinematic snapshots of a confirmed intake."""
from __future__ import annotations

import html
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from core.api.requirements import _authorize, _latest
from core.models import Budget, Provenance, Requester, RequirementObject, Slot, Status

router = APIRouter(tags=["share"])

_SHARE_TTL = timedelta(days=30)
_MAX_SHARES_PER_REQ = 20
_BACKEND_SLOTS = frozenset({"backend_context"})


class ShareBody(BaseModel):
    decisions: list | None = None
    gates: list | None = None
    routing: dict | None = None
    ticket: dict | None = None
    collisions: list | None = None
    acceptance: list | None = None


def _ctx(request: Request):
    return request.app.state.ctx


def _parse_ts(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


async def _load_share(ctx, token: str) -> dict:
    rows = await ctx.store.query_ledger("shares", token=token)
    if not rows:
        raise HTTPException(404, "share not found")
    row = rows[0]
    expires = _parse_ts(row.get("expires_at"))
    if expires is not None and expires < datetime.now(timezone.utc):
        raise HTTPException(404, "share expired")
    payload = row.get("payload") or {}
    if isinstance(payload, str):
        import json
        payload = json.loads(payload)
    return {"row": row, "payload": payload}


def _title_hint(obj: RequirementObject) -> str:
    outcome = obj.slots.get("business_outcome")
    if outcome and isinstance(outcome.value, str) and outcome.value.strip():
        return outcome.value.strip()[:120]
    return (obj.ask_verbatim or "")[:120]


def _truncate(text: str, n: int = 160) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


@router.post("/api/requirements/{req_id}/share")
async def create_share(req_id: str, request: Request, body: ShareBody | None = None):
    ctx = _ctx(request)
    await _authorize(ctx, request, req_id)
    obj = await _latest(ctx, req_id)
    body = body or ShareBody()

    existing = await ctx.store.query_ledger("shares", req_id=req_id)
    if len(existing) >= _MAX_SHARES_PER_REQ:
        raise HTTPException(429, f"share limit ({_MAX_SHARES_PER_REQ}) reached for this requirement")

    session_id = request.headers.get("X-Session-Id")
    session = await ctx.store.get_session(session_id) if session_id else None
    decisions = body.decisions
    if decisions is None and session is not None:
        decisions = session.get("decisions") or []

    now = datetime.now(timezone.utc)
    expires_at = now + _SHARE_TTL
    token = secrets.token_urlsafe(16)
    payload = {
        "req_id": req_id,
        "draft": obj.model_dump(mode="json"),
        "decisions": decisions or [],
        "gates": body.gates,
        "routing": body.routing or (obj.routing.model_dump() if obj.routing else None),
        "ticket": body.ticket,
        "collisions": body.collisions,
        "acceptance": body.acceptance,
        "title_hint": _title_hint(obj),
        "ask_verbatim": _truncate(obj.ask_verbatim, 240),
        "queue": obj.routing.queue if obj.routing else None,
        "readiness_score": obj.readiness_score,
        "status": obj.status.value,
    }
    # Strip requester PII from the public draft snapshot.
    if isinstance(payload["draft"], dict) and "requester" in payload["draft"]:
        payload["draft"]["requester"] = {"id": "", "name": "", "dept": "", "role": ""}

    await ctx.store.log("shares", {
        "token": token, "req_id": req_id,
        "created_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "payload": payload,
    })
    return {"token": token, "url": f"/r/{token}",
            "expires_at": expires_at.isoformat()}


@router.get("/api/share/{token}")
async def get_share(token: str, request: Request):
    ctx = _ctx(request)
    loaded = await _load_share(ctx, token)
    return loaded["payload"]


@router.get("/api/share/{token}/og", response_class=HTMLResponse)
async def share_og(token: str, request: Request):
    ctx = _ctx(request)
    try:
        loaded = await _load_share(ctx, token)
    except HTTPException:
        return HTMLResponse("<!doctype html><title>Share not found</title>"
                            "<p>This share link is missing or expired.</p>",
                            status_code=404)
    payload = loaded["payload"]
    title = html.escape(payload.get("title_hint") or payload.get("req_id") or "IntakePilot")
    desc = html.escape(_truncate(payload.get("ask_verbatim") or "", 200))
    req_id = html.escape(payload.get("req_id") or "")
    spa = f"/r/{html.escape(token)}"
    card = f"/api/share/{html.escape(token)}/card.svg"
    return HTMLResponse(f"""<!doctype html>
<html><head>
<meta charset="utf-8"/>
<title>{title} · IntakePilot</title>
<meta name="description" content="{desc}"/>
<meta property="og:title" content="{title}"/>
<meta property="og:description" content="{desc}"/>
<meta property="og:image" content="{card}"/>
<meta property="og:type" content="website"/>
<meta name="twitter:card" content="summary_large_image"/>
<meta http-equiv="refresh" content="0;url={spa}"/>
</head>
<body>
<p>Open in IntakePilot: <a href="{spa}">{req_id}</a></p>
</body></html>""")


@router.get("/api/share/{token}/card.svg")
async def share_card(token: str, request: Request):
    ctx = _ctx(request)
    try:
        loaded = await _load_share(ctx, token)
    except HTTPException:
        raise HTTPException(404, "share not found")
    payload = loaded["payload"]
    req_id = html.escape(str(payload.get("req_id") or ""))
    queue = html.escape(str(payload.get("queue") or "—"))
    readiness = payload.get("readiness_score")
    readiness_s = html.escape(str(readiness if readiness is not None else "—"))
    ask = html.escape(_truncate(payload.get("ask_verbatim") or "", 90))
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#0d3d4a"/>
      <stop offset="100%" stop-color="#0a6b6b"/>
    </linearGradient>
  </defs>
  <rect width="1200" height="630" fill="url(#bg)"/>
  <rect x="48" y="48" width="1104" height="534" rx="24" fill="#062a32" opacity="0.55"/>
  <text x="80" y="130" fill="#7ee0d6" font-family="Georgia, serif" font-size="36">IntakePilot</text>
  <text x="80" y="210" fill="#e8fffb" font-family="ui-sans-serif, system-ui, sans-serif"
        font-size="42" font-weight="700">{req_id}</text>
  <text x="80" y="280" fill="#a8d9d3" font-family="ui-sans-serif, system-ui, sans-serif"
        font-size="28">queue · {queue}    readiness · {readiness_s}</text>
  <text x="80" y="380" fill="#d7f5f1" font-family="ui-sans-serif, system-ui, sans-serif"
        font-size="32">{ask}</text>
</svg>"""
    return Response(content=svg, media_type="image/svg+xml")


async def clone_from_obj(ctx, source: RequirementObject,
                         requester: Requester | None = None) -> dict:
    """Start a new session+requirement from ask_verbatim + non-backend slots."""
    req = requester or Requester()
    session, obj = await ctx.start_session(req)
    obj.ask_verbatim = source.ask_verbatim
    obj.request_type = source.request_type
    for key, slot in source.slots.items():
        if key in _BACKEND_SLOTS:
            continue
        if slot.value in (None, "", []):
            continue
        # Starting draft: carry values as extracted so enrichment/questions
        # can still refine; human provenance stays human.
        prov = slot.provenance
        if prov in (Provenance.ANSWERED, Provenance.EDITED):
            new_prov = prov
        else:
            new_prov = Provenance.EXTRACTED
        obj.slots[key] = Slot(
            value=slot.value, provenance=new_prov,
            confidence=slot.confidence, source="cloned")
    obj.status = Status.DRAFT
    obj.version = 1  # still the first version we already wrote; mutate then rewrite?
    # start_session already put v1 empty — bump and append.
    obj.version = 2
    obj.touch("cloned", f"from {source.req_id}")
    await ctx.store.put_version(obj)
    return {"session_id": session["session_id"], "req_id": session["req_id"],
            "draft": obj.model_dump(mode="json")}


@router.post("/api/requirements/{req_id}/clone")
async def clone_requirement(req_id: str, request: Request):
    ctx = _ctx(request)
    await _authorize(ctx, request, req_id)
    obj = await _latest(ctx, req_id)
    session_id = request.headers.get("X-Session-Id")
    session = await ctx.store.get_session(session_id) if session_id else None
    requester = None
    if session and session.get("requester"):
        try:
            requester = Requester(**session["requester"])
        except Exception:
            requester = None
    return await clone_from_obj(ctx, obj, requester)


@router.post("/api/share/{token}/clone")
async def clone_share(token: str, request: Request):
    ctx = _ctx(request)
    loaded = await _load_share(ctx, token)
    payload = loaded["payload"]
    draft = payload.get("draft") or {}
    try:
        source = RequirementObject.model_validate(draft)
    except Exception:
        # Minimal fallback when draft was stripped.
        source = RequirementObject(
            req_id=payload.get("req_id") or "share",
            requester=Requester(),
            ask_verbatim=payload.get("ask_verbatim") or "",
            question_budget=Budget())
        source.ask_verbatim = payload.get("ask_verbatim") or source.ask_verbatim
    return await clone_from_obj(ctx, source)
