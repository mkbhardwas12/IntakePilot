"""Sessions router — create session, POST turn (SSE streaming or plain JSON)."""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core.models import Budget, RequirementObject, Requester, TurnResult
from core.agents.request_type import classify_request_type

router = APIRouter(prefix="/api/sessions", tags=["sessions"])

# Keep strong references to in-flight turn workers whose SSE client went away
# (asyncio only holds weak references to tasks).
_bg_turns: set[asyncio.Task] = set()


class CreateSessionBody(BaseModel):
    requester: dict | None = None


class TurnBody(BaseModel):
    message: str = ""
    answers: list[dict] = []


def _ctx(request: Request):
    return request.app.state.ctx


@router.post("")
async def create_session(body: CreateSessionBody, request: Request):
    ctx = _ctx(request)
    req = Requester(**(body.requester or {})) if body.requester else Requester()
    if body.requester and "id" not in body.requester:
        req.id = uuid.uuid4().hex[:8]
    session, obj = await ctx.start_session(req)
    return {"session_id": session["session_id"], "req_id": session["req_id"],
            "draft": obj.model_dump(mode="json")}


async def _run_turn(ctx, session: dict, body: TurnBody, emit=None) -> TurnResult:
    # First real message becomes ask_verbatim (immutable thereafter).
    # Under the shared per-requirement lock: two concurrent first turns would
    # otherwise race to the same version number (append-only violation -> 500).
    async with ctx.orchestrator.lock_for(session["req_id"]):
        obj = await ctx.store.latest(session["req_id"])
        if not obj.ask_verbatim and body.message.strip():
            obj.ask_verbatim = body.message.strip()
            # E: the request type selects the slot-schema fork and the
            # learning bucket. Deterministic keyword classifier, in code.
            obj.request_type = classify_request_type(obj.ask_verbatim)
            obj.version += 1
            obj.touch("ask_recorded", "ask_verbatim set from first message")
            obj.touch("request_type_classified", obj.request_type)
            await ctx.store.put_version(obj)

    now = datetime.now(timezone.utc).isoformat()
    if body.message.strip():
        session["turns"].append({"role": "user", "text": body.message, "at": now})

    result = await ctx.orchestrator.handle_turn(session, body.message,
                                                body.answers, emit=emit)
    summary = _assistant_summary(result)
    session["turns"].append({"role": "assistant", "text": summary,
                             "at": datetime.now(timezone.utc).isoformat()})
    await ctx.store.put_session(session)
    return result


def _assistant_summary(result: TurnResult) -> str:
    parts = []
    if result.degraded:
        parts.append("I couldn't fully process that message, so I kept the draft as it was.")
    filled = sum(1 for s in result.draft.slots.values() if s.value not in (None, "", []))
    parts.append(f"Draft updated — {filled} slot(s) filled, "
                 f"readiness {result.draft.readiness_score}.")
    if result.questions:
        parts.append(f"I have {len(result.questions)} question(s) to tighten this up.")
    elif result.confirm_unlocked:
        parts.append("This looks ready — review and confirm when you're happy.")
    return " ".join(parts)


@router.post("/{session_id}/turns")
async def post_turn(session_id: str, body: TurnBody, request: Request,
                    stream: bool = True):
    ctx = _ctx(request)
    session = await ctx.store.get_session(session_id)
    if session is None:
        raise HTTPException(404, "session not found")

    if not stream:
        result = await _run_turn(ctx, session, body)
        return result.model_dump(mode="json")

    queue: asyncio.Queue = asyncio.Queue()

    async def emit(event: str, data: dict) -> None:
        await queue.put((event, data))

    async def worker() -> None:
        try:
            result = await _run_turn(ctx, session, body, emit=emit)
            await queue.put(("done", result.model_dump(mode="json")))
        except Exception as exc:  # surface as SSE error, never a hung stream
            await queue.put(("error", {"detail": str(exc)}))
        await queue.put(None)

    async def sse():
        # The worker is deliberately NOT cancelled if the client disconnects:
        # a turn mutates ledgers, budget, and versions, and killing it halfway
        # leaves inconsistent state. The stream stops; the turn completes.
        task = asyncio.create_task(worker())
        _bg_turns.add(task)
        task.add_done_callback(_bg_turns.discard)
        while True:
            item = await queue.get()
            if item is None:
                break
            event, data = item
            yield f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@router.get("/{session_id}")
async def get_session(session_id: str, request: Request):
    ctx = _ctx(request)
    session = await ctx.store.get_session(session_id)
    if session is None:
        raise HTTPException(404, "session not found")
    obj = await ctx.store.latest(session["req_id"])
    return {"session_id": session_id, "req_id": session["req_id"],
            "draft": obj.model_dump(mode="json"),
            "pending_questions": session.get("pending_questions", []),
            "turns": session.get("turns", [])}
