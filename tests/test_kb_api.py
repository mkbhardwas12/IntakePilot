"""The system_kb human-validation loop must be reachable over the API —
previously mark_validated/refresh_system_kb were called only by tests."""
from __future__ import annotations

import httpx
import pytest

from core.api.context import AppContext
from core.api.main import create_app

from tests.conftest import memory_config

ASK = "I need a report of goods details for product line X with the order info"


@pytest.fixture
async def client():
    ctx = AppContext(memory_config())
    app = create_app(ctx)
    await ctx.seed_glossary()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as c:
        yield c


async def _confirmed_intake(c) -> None:
    sid = (await c.post("/api/sessions", json={
        "requester": {"name": "T", "dept": "Ops", "role": "Analyst"}})).json()["session_id"]
    t = (await c.post(f"/api/sessions/{sid}/turns?stream=false",
                      json={"message": ASK})).json()
    answers = [{"question_id": q["id"], "slot_key": q["slot_key"],
                "value": (q.get("options") or ["this month"])[0]}
               for q in t["questions"]]
    await c.post(f"/api/sessions/{sid}/turns?stream=false",
                 json={"message": "done means the report arrives in 1 hour",
                       "answers": answers})
    req_id = t["draft"]["req_id"]
    r = await c.post(f"/api/requirements/{req_id}/confirm", json={"edits": {}},
                     headers={"X-Session-Id": sid})
    assert r.status_code == 200


async def test_validate_endpoint_verifies_and_bumps_evidence(client):
    await _confirmed_intake(client)
    kb = (await client.get("/api/kb")).json()["entities"]
    assert kb, "enrichment should have discovered entities"
    target = next(e for e in kb if not e["verified"])

    r = await client.post(f"/api/kb/{target['system']}/{target['entity']}/validate")
    assert r.status_code == 200
    body = r.json()
    assert body["verified"] is True
    assert body["evidence_count"] == (target["evidence_count"] or 1) + 1

    # visible in the ops view and in /api/metrics
    kb_after = (await client.get("/api/kb")).json()["entities"]
    assert any(e["verified"] for e in kb_after)
    metrics = (await client.get("/api/metrics")).json()
    assert metrics["system_kb"]["verified"] >= 1


async def test_validate_unknown_entity_404s(client):
    r = await client.post("/api/kb/nope/nothing/validate")
    assert r.status_code == 404


async def test_refresh_rescans_connectors(client):
    await _confirmed_intake(client)
    r = await client.post("/api/kb/refresh")
    assert r.status_code == 200
    assert r.json()["refreshed"] >= 1