"""Requirement IDs are sequential (IPR-{year}-{seq:06d}) — without ownership
binding anyone could enumerate every requirement or confirm someone else's
draft. All /api/requirements/* endpoints require the owning X-Session-Id."""
from __future__ import annotations

import httpx
import pytest

from core.api.context import AppContext
from core.api.main import create_app

from tests.conftest import memory_config


@pytest.fixture
async def client():
    ctx = AppContext(memory_config())
    app = create_app(ctx)
    await ctx.seed_glossary()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as c:
        yield c


async def _intake(c, ask: str) -> tuple[str, str]:
    sid = (await c.post("/api/sessions", json={
        "requester": {"name": "A", "dept": "Finance Ops", "role": "Analyst"}}
    )).json()["session_id"]
    t = (await c.post(f"/api/sessions/{sid}/turns?stream=false",
                      json={"message": ask})).json()
    return sid, t["draft"]["req_id"]


async def test_missing_header_is_401(client):
    _, req_id = await _intake(client, "automate the weekly export")
    for path in (f"/api/requirements/{req_id}",
                 f"/api/requirements/{req_id}/history",
                 f"/api/requirements/{req_id}/render"):
        assert (await client.get(path)).status_code == 401
    r = await client.post(f"/api/requirements/{req_id}/confirm", json={"edits": {}})
    assert r.status_code == 401


async def test_foreign_session_cannot_read_or_confirm(client):
    _, req_a = await _intake(client, "automate the weekly export")
    sid_b, _ = await _intake(client, "sync invoices nightly")
    # B tries to walk A's requirement: 404, indistinguishable from absent.
    r = await client.get(f"/api/requirements/{req_a}",
                         headers={"X-Session-Id": sid_b})
    assert r.status_code == 404
    r = await client.post(f"/api/requirements/{req_a}/confirm", json={"edits": {}},
                          headers={"X-Session-Id": sid_b})
    assert r.status_code == 404


async def test_owner_still_has_full_access(client):
    sid, req_id = await _intake(client, "automate the weekly export")
    r = await client.get(f"/api/requirements/{req_id}",
                         headers={"X-Session-Id": sid})
    assert r.status_code == 200 and r.json()["req_id"] == req_id


async def test_unknown_session_id_is_404(client):
    _, req_id = await _intake(client, "automate the weekly export")
    r = await client.get(f"/api/requirements/{req_id}",
                         headers={"X-Session-Id": "deadbeef"})
    assert r.status_code == 404