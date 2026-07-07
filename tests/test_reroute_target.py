"""D: the routing feedback loop — target factory, reroute signal (manual +
GitHub webhook), routing_accuracy metric, and precedent correction."""
from __future__ import annotations

import httpx
import pytest

from core.api.context import AppContext
from core.api.main import create_app
from core.config import Config
from core.targets import make_target
from core.targets.github import GitHubTarget
from core.targets.local import LocalTarget

from tests.conftest import memory_config

ASK = "our monthly vendor report takes 3 days to compile by hand"


def test_target_factory_wires_github_from_config():
    assert isinstance(make_target(Config()), LocalTarget)
    cfg = Config(target_provider="github",
                 targets={"github": {"repo": "org/repo"}})
    target = make_target(cfg)
    assert isinstance(target, GitHubTarget) and target.repo == "org/repo"
    with pytest.raises(ValueError):
        make_target(Config(target_provider="not-a-target"))


@pytest.fixture
async def client():
    ctx = AppContext(memory_config())
    app = create_app(ctx)
    await ctx.seed_glossary()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as c:
        yield c


async def _routed(c, ask=ASK) -> tuple[str, str]:
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
    assert confirm["draft"]["status"] == "routed"
    return sid, req_id


async def test_manual_reroute_updates_queue_and_accuracy(client):
    sid, req_id = await _routed(client)
    r = await client.post(f"/api/requirements/{req_id}/reroute",
                          json={"queue": "integrations"})
    assert r.status_code == 200
    assert r.json() == {"req_id": req_id, "changed": True,
                        "queue": "integrations", "previous": "data-platform"}

    draft = (await client.get(f"/api/requirements/{req_id}",
                              headers={"X-Session-Id": sid})).json()
    assert draft["routing"]["queue"] == "integrations"
    assert any(e["event"] == "rerouted" for e in draft["audit"])

    metrics = (await client.get("/api/metrics")).json()
    assert metrics["routing_accuracy"] == 0.0  # 1 routed, 1 rerouted

    # same-queue reroute is a no-op
    again = await client.post(f"/api/requirements/{req_id}/reroute",
                              json={"queue": "integrations"})
    assert again.json()["changed"] is False


async def test_reroute_guards(client):
    r = await client.post("/api/requirements/IPR-2099-999999/reroute",
                          json={"queue": "integrations"})
    assert r.status_code == 404


async def test_github_webhook_relabel_triggers_reroute(client):
    _, req_id = await _routed(client)
    payload = {
        "action": "labeled",
        "label": {"name": "intake/integrations"},
        "issue": {"title": f"[{req_id}] Automate the vendor report",
                  "body": f"Requirement: {req_id}\n..."},
    }
    r = await client.post("/api/webhooks/github", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["processed"] is True and body["queue"] == "integrations"

    # non-queue labels and other actions are ignored
    ignored = await client.post("/api/webhooks/github", json={
        "action": "labeled", "label": {"name": "bug"}, "issue": {}})
    assert ignored.json()["processed"] is False