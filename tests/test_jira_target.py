"""Jira target + webhook outcome sync: issue creation payload (ADF, labels,
auth), the queue-relabel reroute loop, and the issue-done delivery terminal
state that grounds cycle-time metrics."""
from __future__ import annotations

import json

import httpx
import pytest

from core.api.context import AppContext
from core.api.main import create_app
from core.config import Config
from core.models import Budget, RequirementObject, Requester
from core.targets import make_target
from core.targets.jira import JiraTarget, markdown_to_adf, queue_label

from tests.conftest import memory_config

ASK = "our monthly vendor report takes 3 days to compile by hand"


def test_factory_wires_jira():
    cfg = Config(target_provider="jira",
                 targets={"jira": {"base_url": "https://x.atlassian.net",
                                   "project": "INTAKE"}})
    target = make_target(cfg)
    assert isinstance(target, JiraTarget)
    assert target.project == "INTAKE"


def test_markdown_to_adf_shapes():
    adf = markdown_to_adf("# Title\n\nA paragraph.\n\n- one\n- two\n\n"
                          "```\ncode here\n```")
    kinds = [n["type"] for n in adf["content"]]
    assert kinds == ["heading", "paragraph", "bulletList", "codeBlock"]
    assert adf["content"][0]["attrs"]["level"] == 1
    assert len(adf["content"][2]["content"]) == 2
    assert adf["type"] == "doc" and adf["version"] == 1


def test_queue_label_is_jira_safe():
    assert queue_label("data-platform") == "intake-data-platform"
    assert " " not in queue_label("Data Platform!")


async def test_create_item_posts_adf_and_labels(monkeypatch):
    monkeypatch.setenv("JIRA_EMAIL", "bot@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "tok")
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization", "")
        captured["payload"] = json.loads(request.content)
        return httpx.Response(201, json={"id": "1", "key": "INTAKE-7"})

    target = JiraTarget({"base_url": "https://x.atlassian.net/",
                         "project": "INTAKE"},
                        transport=httpx.MockTransport(handler))
    obj = RequirementObject(
        req_id="IPR-2026-000042", requester=Requester(dept="Finance Ops"),
        ask_verbatim=ASK, question_budget=Budget(max=7, per_turn=3))
    ticket = await target.create_item(obj, "Automate the vendor report",
                                      "# Requirement\n\n- point one",
                                      "data-platform")

    assert captured["url"] == "https://x.atlassian.net/rest/api/3/issue"
    assert captured["auth"].startswith("Basic ")
    fields = captured["payload"]["fields"]
    assert fields["project"]["key"] == "INTAKE"
    assert fields["description"]["type"] == "doc"
    assert set(fields["labels"]) == {"intakepilot", "intake-data-platform",
                                     "ipr-2026-000042"}
    assert ticket.target == "jira" and ticket.ref == "INTAKE-7"
    assert ticket.path == "https://x.atlassian.net/browse/INTAKE-7"


async def test_create_item_requires_credentials(monkeypatch):
    monkeypatch.delenv("JIRA_EMAIL", raising=False)
    monkeypatch.delenv("JIRA_API_TOKEN", raising=False)
    target = JiraTarget({"base_url": "https://x.atlassian.net", "project": "I"})
    obj = RequirementObject(
        req_id="IPR-2026-000001", requester=Requester(dept="Finance Ops"),
        ask_verbatim=ASK, question_budget=Budget(max=7, per_turn=3))
    with pytest.raises(RuntimeError):
        await target.create_item(obj, "t", "b", "q")


# ---------------------------------------------------------------- webhook --
@pytest.fixture
async def client():
    ctx = AppContext(memory_config())
    app = create_app(ctx)
    await ctx.seed_glossary()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as c:
        yield c, ctx


async def _routed(c) -> str:
    sid = (await c.post("/api/sessions", json={
        "requester": {"name": "A", "dept": "Finance Ops", "role": "Analyst"}}
    )).json()["session_id"]
    t = (await c.post(f"/api/sessions/{sid}/turns?stream=false",
                      json={"message": ASK})).json()
    answers = [{"question_id": q["id"], "slot_key": q["slot_key"],
                "value": (q.get("options") or ["this month"])[0]}
               for q in t["questions"]]
    await c.post(f"/api/sessions/{sid}/turns?stream=false",
                 json={"message": "done means ready in 1 hour",
                       "answers": answers})
    req_id = t["draft"]["req_id"]
    confirm = (await c.post(f"/api/requirements/{req_id}/confirm",
                            json={"edits": {}}, headers={"X-Session-Id": sid})
               ).json()
    assert confirm["draft"]["status"] == "routed"
    return req_id


def _jira_event(req_id: str, *, field: str, to: str,
                done: bool = False) -> dict:
    return {
        "webhookEvent": "jira:issue_updated",
        "issue": {"key": "INTAKE-9", "fields": {
            "labels": ["intakepilot", req_id.lower(), "intake-data-platform"],
            "status": {"name": to,
                       "statusCategory": {"key": "done" if done else "new"}}}},
        "changelog": {"items": [{"field": field,
                                 "fromString": "x", "toString": to}]},
    }


async def test_jira_relabel_becomes_reroute(client):
    c, ctx = client
    req_id = await _routed(c)
    event = _jira_event(req_id, field="labels", to="intake-internal-tools")
    r = await c.post("/api/webhooks/jira", json=event)
    body = r.json()
    assert body["processed"] is True and body["event"] == "reroute"
    obj = await ctx.store.latest(req_id)
    assert obj.routing.queue == "internal-tools"
    rows = await ctx.store.query_ledger("outcome_ledger")
    assert any(row["stage"] == "reroute" for row in rows)


async def test_jira_done_writes_delivered_outcome(client):
    c, ctx = client
    req_id = await _routed(c)
    event = _jira_event(req_id, field="status", to="Done", done=True)
    r = await c.post("/api/webhooks/jira", json=event)
    assert r.json() == {"processed": True, "event": "delivered",
                        "req_id": req_id}
    rows = await ctx.store.query_ledger("outcome_ledger")
    delivered = [row for row in rows if row["stage"] == "delivered"]
    assert len(delivered) == 1
    assert delivered[0]["req_id"] == req_id
    assert delivered[0]["detail"]["issue"] == "INTAKE-9"


async def test_jira_webhook_ignores_foreign_issues(client):
    c, _ = client
    event = {"issue": {"key": "OTHER-1", "fields": {"labels": ["bug"]}},
             "changelog": {"items": [{"field": "status", "toString": "Done"}]}}
    r = await c.post("/api/webhooks/jira", json=event)
    assert r.json()["processed"] is False


async def test_jira_webhook_token_enforced(client, monkeypatch):
    c, _ = client
    monkeypatch.setenv("INTAKEPILOT_JIRA_WEBHOOK_SECRET", "s3cret")
    r = await c.post("/api/webhooks/jira", json={})
    assert r.status_code == 401
    r = await c.post("/api/webhooks/jira?token=s3cret", json={"issue": {}})
    assert r.status_code == 200 and r.json()["processed"] is False
    r = await c.post("/api/webhooks/jira", json={"issue": {}},
                     headers={"X-IntakePilot-Token": "s3cret"})
    assert r.status_code == 200
