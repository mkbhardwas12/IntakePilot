"""G: the generic channel adapter — deterministic sessions per conversation,
plain-text replies a bot can relay verbatim, 'confirm' completes the flow."""
from __future__ import annotations

import httpx
import pytest

from core.api.context import AppContext
from core.api.main import create_app

from tests.conftest import memory_config

ASK = "our monthly vendor report takes 3 days to compile by hand"
USER = {"name": "Pat", "dept": "Finance Ops", "role": "Analyst"}


@pytest.fixture
async def client():
    ctx = AppContext(memory_config())
    app = create_app(ctx)
    await ctx.seed_glossary()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as c:
        yield c


async def _send(c, text, external_id="U1:C1", channel="slack"):
    r = await c.post("/api/channels/inbound", json={
        "channel": channel, "external_id": external_id,
        "text": text, "user": USER})
    assert r.status_code == 200, r.text
    return r.json()


async def test_conversation_maps_to_one_stable_session(client):
    first = await _send(client, ASK)
    again = await _send(client, "it also feeds the quarterly pack")
    assert first["session_id"] == again["session_id"]
    assert first["req_id"] == again["req_id"]
    # a different conversation gets its own session/requirement
    other = await _send(client, ASK, external_id="U9:C9")
    assert other["req_id"] != first["req_id"]


async def test_reply_carries_questions_and_confirm_completes(client):
    first = await _send(client, ASK, external_id="U2:C2")
    assert f"Draft {first['req_id']}" in first["reply"]
    assert first["questions"], "expected budgeted questions in the reply"
    assert "1." in first["reply"]

    # answer the numbered questions chat-style, then confirm
    replies = "\n".join(f"{i}: {(q.get('options') or ['this month'])[0]}"
                        for i, q in enumerate(first["questions"], 1))
    answered = await _send(client, replies, external_id="U2:C2")
    assert answered["confirm_unlocked"] is True
    done = await _send(client, "confirm", external_id="U2:C2")
    assert done["status"] == "routed"
    assert "Routed to" in done["reply"] and "Ticket" in done["reply"]

    # confirming twice is a friendly no-op message, not an error
    again = await _send(client, "confirm", external_id="U2:C2")
    assert "already routed" in again["reply"]


async def test_empty_text_422(client):
    r = await client.post("/api/channels/inbound", json={
        "channel": "slack", "external_id": "U3:C3", "text": "   "})
    assert r.status_code == 422


async def test_admin_token_guards_the_channel(client, monkeypatch):
    monkeypatch.setenv("INTAKEPILOT_ADMIN_TOKEN", "bot-secret")
    r = await client.post("/api/channels/inbound", json={
        "channel": "slack", "external_id": "U4:C4", "text": ASK})
    assert r.status_code == 401
    r = await client.post("/api/channels/inbound", json={
        "channel": "slack", "external_id": "U4:C4", "text": ASK},
        headers={"Authorization": "Bearer bot-secret"})
    assert r.status_code == 200