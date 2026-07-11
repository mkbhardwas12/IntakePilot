"""One switch closes every ops surface: INTAKEPILOT_ADMIN_TOKEN guards
kb/evals/glossary/reroute; INTAKEPILOT_WEBHOOK_SECRET enforces GitHub's
X-Hub-Signature-256. Unset, both stay open (documented demo posture)."""
from __future__ import annotations

import hashlib
import hmac
import json

import httpx
import pytest

from core.api.context import AppContext
from core.api.main import create_app

from tests.conftest import memory_config

ADMIN_PATHS = [
    ("GET", "/api/kb"),
    ("POST", "/api/kb/refresh"),
    ("GET", "/api/metrics"),
    ("GET", "/api/evals/replay?limit=1"),
    ("GET", "/api/glossary/proposals"),
    ("POST", "/api/glossary"),
    ("POST", "/api/requirements/IPR-2099-000001/reroute"),
    ("GET", "/api/triage"),
]


@pytest.fixture
async def client():
    ctx = AppContext(memory_config())
    app = create_app(ctx)
    await ctx.seed_glossary()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as c:
        yield c


async def test_token_unset_keeps_surfaces_open(client, monkeypatch):
    monkeypatch.delenv("INTAKEPILOT_ADMIN_TOKEN", raising=False)
    r = await client.get("/api/kb")
    assert r.status_code == 200


async def test_token_set_guards_every_ops_surface(client, monkeypatch):
    monkeypatch.setenv("INTAKEPILOT_ADMIN_TOKEN", "s3cret")
    for method, path in ADMIN_PATHS:
        r = await client.request(method, path, json={} if method == "POST" else None)
        assert r.status_code == 401, f"{method} {path} was not guarded"
    # correct bearer gets through (to the endpoint's own validation)
    r = await client.get("/api/kb", headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200
    r = await client.get("/api/kb", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


async def test_webhook_signature_enforced_when_secret_set(client, monkeypatch):
    monkeypatch.setenv("INTAKEPILOT_WEBHOOK_SECRET", "hooksecret")
    payload = json.dumps({"action": "labeled",
                          "label": {"name": "intake/integrations"},
                          "issue": {"title": "IPR-2026-000001", "body": ""}}).encode()

    r = await client.post("/api/webhooks/github", content=payload,
                          headers={"Content-Type": "application/json"})
    assert r.status_code == 401  # unsigned

    bad = "sha256=" + hmac.new(b"wrong", payload, hashlib.sha256).hexdigest()
    r = await client.post("/api/webhooks/github", content=payload,
                          headers={"Content-Type": "application/json",
                                   "X-Hub-Signature-256": bad})
    assert r.status_code == 401

    good = "sha256=" + hmac.new(b"hooksecret", payload, hashlib.sha256).hexdigest()
    r = await client.post("/api/webhooks/github", content=payload,
                          headers={"Content-Type": "application/json",
                                   "X-Hub-Signature-256": good})
    # Signature accepted; unknown requirement is benign for a webhook — 200
    # with processed=false, never a 4xx that could get the hook disabled.
    assert r.status_code == 200
    assert r.json() == {"processed": False, "reason": "requirement not found"}


async def test_webhook_open_when_secret_unset(client, monkeypatch):
    monkeypatch.delenv("INTAKEPILOT_WEBHOOK_SECRET", raising=False)
    r = await client.post("/api/webhooks/github",
                          json={"action": "labeled", "label": {"name": "bug"},
                                "issue": {}})
    assert r.status_code == 200 and r.json()["processed"] is False
