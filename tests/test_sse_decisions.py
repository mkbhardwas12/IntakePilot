"""SSE turn stream must emit decision events for the gap ladder."""
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


async def test_sse_turn_emits_decision_events(client):
    client, _ctx = client
    resp = await client.post("/api/sessions", json={})
    sid = resp.json()["session_id"]
    async with client.stream("POST", f"/api/sessions/{sid}/turns",
                             json={"message": ASK}) as resp:
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = ""
        async for chunk in resp.aiter_text():
            body += chunk
    events = [line.split(": ", 1)[1] for line in body.splitlines()
              if line.startswith("event: ")]
    assert "decision" in events, f"expected decision events, got {events}"
    assert events[-1] == "done"
