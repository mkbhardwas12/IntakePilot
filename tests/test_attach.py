"""Duplicate-merge: a gate-4-caught duplicate can be attached to the existing
requirement instead of dying as GATED — with ownership enforced."""
from __future__ import annotations

import httpx
import pytest

from core.api.context import AppContext
from core.api.main import create_app

from tests.conftest import memory_config

ASK = "our monthly vendor report takes 3 days to compile by hand"


@pytest.fixture
async def client():
    ctx = AppContext(memory_config())
    app = create_app(ctx)
    await ctx.seed_glossary()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as c:
        yield c


async def _confirmed(c, ask=ASK) -> tuple[str, str, dict]:
    sid = (await c.post("/api/sessions", json={
        "requester": {"name": "A", "dept": "Finance Ops", "role": "Analyst"}}
    )).json()["session_id"]
    t = (await c.post(f"/api/sessions/{sid}/turns?stream=false",
                      json={"message": ask})).json()
    answers = [{"question_id": q["id"], "slot_key": q["slot_key"],
                "value": (q.get("options") or ["this month"])[0]}
               for q in t["questions"]]
    await c.post(f"/api/sessions/{sid}/turns?stream=false",
                 json={"message": "done means ready in 1 hour", "answers": answers})
    req_id = t["draft"]["req_id"]
    confirm = (await c.post(f"/api/requirements/{req_id}/confirm",
                            json={"edits": {}},
                            headers={"X-Session-Id": sid})).json()
    return sid, req_id, confirm


async def test_gated_duplicate_attaches_and_closes(client):
    _, original, first = await _confirmed(client)
    assert first["draft"]["status"] == "routed"

    sid2, dup_id, second = await _confirmed(client)
    assert second["draft"]["status"] == "gated"
    g4 = next(g for g in second["gates"] if g["gate"] == 4)
    assert g4["meta"]["duplicate_of"] == original  # structured, not string-parsed

    r = await client.post(f"/api/requirements/{dup_id}/attach",
                          json={"target_req_id": original},
                          headers={"X-Session-Id": sid2})
    assert r.status_code == 200
    body = r.json()
    assert body["attached_to"] == original
    assert body["draft"]["status"] == "done"
    assert any(e["event"] == "attached" for e in body["draft"]["audit"])


async def test_attach_guards(client):
    sid1, original, _ = await _confirmed(client)
    sid2, dup_id, _ = await _confirmed(client)

    # routed (non-gated) requirements cannot be attached
    r = await client.post(f"/api/requirements/{original}/attach",
                          json={"target_req_id": dup_id},
                          headers={"X-Session-Id": sid1})
    assert r.status_code == 409
    # self-attach is rejected
    r = await client.post(f"/api/requirements/{dup_id}/attach",
                          json={"target_req_id": dup_id},
                          headers={"X-Session-Id": sid2})
    assert r.status_code == 422
    # unknown target 404s
    r = await client.post(f"/api/requirements/{dup_id}/attach",
                          json={"target_req_id": "IPR-2099-999999"},
                          headers={"X-Session-Id": sid2})
    assert r.status_code == 404
    # foreign session cannot attach someone else's requirement
    r = await client.post(f"/api/requirements/{dup_id}/attach",
                          json={"target_req_id": original},
                          headers={"X-Session-Id": sid1})
    assert r.status_code == 404