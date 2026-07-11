"""Share token create / get / expiry."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

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


async def _session_with_ask(client):
    resp = await client.post("/api/sessions", json={
        "requester": {"name": "Demo", "dept": "Finance Ops"}})
    assert resp.status_code == 200
    sid, req_id = resp.json()["session_id"], resp.json()["req_id"]
    resp = await client.post(f"/api/sessions/{sid}/turns?stream=false",
                             json={"message": ASK})
    assert resp.status_code == 200
    return sid, req_id


async def test_share_create_and_get(client):
    client, ctx = client
    sid, req_id = await _session_with_ask(client)

    resp = await client.post(
        f"/api/requirements/{req_id}/share",
        json={"decisions": [{"slot": "business_outcome", "action": "extracted",
                             "reason": "from ask", "source": None}]},
        headers={"X-Session-Id": sid})
    assert resp.status_code == 200
    body = resp.json()
    assert body["token"]
    assert body["url"] == f"/r/{body['token']}"
    assert body["expires_at"]

    got = await client.get(f"/api/share/{body['token']}")
    assert got.status_code == 200
    payload = got.json()
    assert payload["req_id"] == req_id
    assert payload["draft"]["ask_verbatim"] == ASK
    assert payload["decisions"][0]["action"] == "extracted"
    # Public payload must not leak requester PII.
    assert payload["draft"]["requester"]["name"] == ""


async def test_share_expired_returns_404(client):
    client, ctx = client
    sid, req_id = await _session_with_ask(client)
    resp = await client.post(
        f"/api/requirements/{req_id}/share", json={},
        headers={"X-Session-Id": sid})
    token = resp.json()["token"]

    # Backdate the ledger row past expiry.
    rows = await ctx.store.query_ledger("shares", token=token)
    assert len(rows) == 1
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    # Re-insert isn't unique-keyed on token for sqlite autoincrement; update
    # via direct SQL on the test store.
    with ctx.store._lock:
        ctx.store._conn.execute(
            "UPDATE shares SET expires_at=? WHERE token=?", (past, token))
        ctx.store._conn.commit()

    got = await client.get(f"/api/share/{token}")
    assert got.status_code == 404
