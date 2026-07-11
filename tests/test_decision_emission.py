"""Decisions persist on the session even when stream=false (no SSE client)."""
from __future__ import annotations

import httpx
import pytest

from core.api.context import AppContext
from core.api.main import create_app

from tests.conftest import memory_config

ASK = "our monthly vendor report takes 3 days to compile by hand"


@pytest.fixture
async def client(tmp_path):
    cfg = memory_config()
    cfg.demo_repo = str(tmp_path / "demo-repo")
    ctx = AppContext(cfg)
    app = create_app(ctx)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as c:
        await ctx.seed_glossary()
        yield c, ctx


async def test_decisions_persisted_on_session_without_stream(client):
    client, ctx = client
    resp = await client.post("/api/sessions", json={
        "requester": {"name": "Demo", "dept": "Finance Ops"}})
    sid = resp.json()["session_id"]

    resp = await client.post(f"/api/sessions/{sid}/turns?stream=false",
                             json={"message": ASK})
    assert resp.status_code == 200

    session = await ctx.store.get_session(sid)
    assert session is not None
    decisions = session.get("decisions") or []
    assert decisions, "expected at least one decision appended during the turn"
    assert all("slot" in d and "action" in d for d in decisions)

    # Also exposed on GET /api/sessions/{id} for share/replay.
    got = await client.get(f"/api/sessions/{sid}")
    assert got.status_code == 200
    assert len(got.json().get("decisions") or []) >= 1
