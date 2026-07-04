"""I4: stakeholder countersign — named stakeholders get consent records at
confirmation; approvals/objections land on the ledger and audit trail
BEFORE the work starts."""
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


async def _confirmed(c):
    sid = (await c.post("/api/sessions", json={
        "requester": {"name": "A", "dept": "Finance Ops", "role": "Analyst"}}
    )).json()["session_id"]
    t = (await c.post(f"/api/sessions/{sid}/turns?stream=false",
                      json={"message": ASK})).json()
    answers = [{"question_id": q["id"], "slot_key": q["slot_key"],
                "value": (q.get("options") or ["this month"])[0]}
               for q in t["questions"]]
    await c.post(f"/api/sessions/{sid}/turns?stream=false",
                 json={"message": "success means ready in 1 hour",
                       "answers": answers})
    req_id = t["draft"]["req_id"]
    confirm = (await c.post(f"/api/requirements/{req_id}/confirm",
                            json={"edits": {}},
                            headers={"X-Session-Id": sid})).json()
    return req_id, confirm


async def test_confirm_creates_pending_consent_for_stakeholders(client):
    req_id, confirm = await _confirmed(client)
    # Finance Ops dept infers the finance-systems stakeholder team
    assert confirm["consent"]["pending"] == ["finance-systems"]

    status = (await client.get(f"/api/requirements/{req_id}/consent")).json()
    assert status["pending"] == 1 and status["objections"] == 0
    assert status["stakeholders"][0]["status"] == "pending"


async def test_approve_and_object_update_ledger_and_audit(client):
    req_id, _ = await _confirmed(client)

    r = await client.post(f"/api/requirements/{req_id}/consent", json={
        "stakeholder": "finance-systems", "decision": "approve"})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    status = (await client.get(f"/api/requirements/{req_id}/consent")).json()
    assert status["stakeholders"][0]["status"] == "approved"
    assert status["pending"] == 0

    r = await client.post(f"/api/requirements/{req_id}/consent", json={
        "stakeholder": "finance-systems", "decision": "object",
        "note": "conflicts with the AP redesign"})
    assert r.json()["status"] == "objected"
    status = (await client.get(f"/api/requirements/{req_id}/consent")).json()
    assert status["objections"] == 1
    assert status["stakeholders"][0]["note"] == "conflicts with the AP redesign"


async def test_consent_guards(client):
    req_id, _ = await _confirmed(client)
    r = await client.post(f"/api/requirements/{req_id}/consent", json={
        "stakeholder": "someone-else", "decision": "approve"})
    assert r.status_code == 404  # only NAMED stakeholders can countersign
    r = await client.post(f"/api/requirements/{req_id}/consent", json={
        "stakeholder": "finance-systems", "decision": "maybe"})
    assert r.status_code == 422
    r = await client.get("/api/requirements/IPR-2099-999999/consent")
    assert r.status_code == 404