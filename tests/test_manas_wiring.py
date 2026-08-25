"""The MANAS outbox, wired: confirm emits requirement.versioned.v2 into the
transactional outbox, human adjudication emits outcome.adjudicated.v1, the
relay reads and acknowledges — and none of it can cost a user transaction.
"""
from __future__ import annotations

import json

import httpx
import pytest

from core.api.context import AppContext
from core.api.main import create_app
from core.export.manas_outbox import service

from tests.conftest import memory_config

ASK = "our monthly vendor report takes 3 days to compile by hand"

ENV = {
    "MANAS_OUTBOX_ENABLED": "true",
    "MANAS_TENANT_ID": "t-intake",
    "MANAS_SOURCE_INSTANCE_ID": "intake-test-1",
    "MANAS_SOURCE_BINDING": "sha256:" + "a" * 64,
    "MANAS_TENANT_PEPPER": "0123456789abcdef-pepper",
}

DEPLOYMENT_REF = "deployment:basis-prod:EUW:001:rollout-42"
DEPLOYMENT_BINDING = "sha256:" + "b" * 64


@pytest.fixture
async def client(tmp_path):
    cfg = memory_config()
    cfg.demo_repo = str(tmp_path / "demo-repo")
    ctx = AppContext(cfg)
    app = create_app(ctx)
    async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test") as client:
        await ctx.seed_glossary()
        yield client, ctx


def set_env(monkeypatch, enabled: bool = True):
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)
    if not enabled:
        monkeypatch.setenv("MANAS_OUTBOX_ENABLED", "false")


async def drive_to_routed(client) -> tuple[str, str]:
    """Session -> ask -> answer everything -> confirm. Returns (sid, req_id)."""
    resp = await client.post("/api/sessions", json={
        "requester": {"name": "T", "dept": "Finance Ops", "role": "Analyst"}})
    sid, req_id = resp.json()["session_id"], resp.json()["req_id"]
    turn = (await client.post(f"/api/sessions/{sid}/turns?stream=false",
                              json={"message": ASK})).json()
    for _ in range(4):
        if turn["confirm_unlocked"] and not turn["questions"]:
            break
        answers = [{"question_id": q["id"], "slot_key": q["slot_key"],
                    "value": (q["options"] or ["report compiles in under 1 hour"])[0]}
                   for q in turn["questions"]]
        turn = (await client.post(f"/api/sessions/{sid}/turns?stream=false",
                                  json={"message": "", "answers": answers})).json()
    resp = await client.post(f"/api/requirements/{req_id}/confirm",
                             json={"edits": {}},
                             headers={"X-Session-Id": sid})
    assert resp.status_code == 200
    assert resp.json()["draft"]["status"] == "routed", resp.json()["gates"]
    return sid, req_id


async def test_confirm_commits_a_pending_requirement_versioned_row(client, monkeypatch):
    client, ctx = client
    set_env(monkeypatch)
    _, req_id = await drive_to_routed(client)

    rows = await ctx.store.query_ledger("manas_outbox", req_id=req_id)
    assert len(rows) == 1
    row = rows[0]
    assert row["state"] == "pending", row["reason"]
    assert row["event_type"] == "io.manas.demand.requirement.versioned.v2"
    envelope = json.loads(row["envelope_json"])
    data = envelope["data"]
    assert data["requirement_id"] == req_id
    assert data["status"] == "ready_for_build"
    assert data["intent_commitment"].startswith("hmac-sha256:")
    # The business narrative never crosses: the ask is not in the envelope.
    assert ASK not in row["envelope_json"]


async def test_outbox_off_means_no_rows_and_no_interference(client, monkeypatch):
    client, ctx = client
    set_env(monkeypatch, enabled=False)
    _, req_id = await drive_to_routed(client)
    assert await ctx.store.query_ledger("manas_outbox", req_id=req_id) == []


async def test_misconfigured_outbox_is_an_audit_row_not_a_failed_confirm(client, monkeypatch):
    client, ctx = client
    set_env(monkeypatch)
    monkeypatch.setenv("MANAS_SOURCE_BINDING", "not-a-hash")
    _, req_id = await drive_to_routed(client)          # confirm still succeeds
    rows = await ctx.store.query_ledger("manas_outbox", req_id=req_id)
    assert len(rows) == 1 and rows[0]["state"] == "rejected"
    assert "MANAS_SOURCE_BINDING" in rows[0]["reason"]


async def test_adjudication_with_attestation_emits_outcome(client, monkeypatch):
    client, ctx = client
    set_env(monkeypatch)
    _, req_id = await drive_to_routed(client)

    resp = await client.post(f"/api/requirements/{req_id}/adjudicate", json={
        "verdict": "achieved", "adjudicated_by_role": "business_owner",
        "receipt": "Report runs in 40 minutes; finance signed off.",
        "evidence": "run log 2026-08-25",
        "deployment_ref": DEPLOYMENT_REF,
        "deployment_source_binding": DEPLOYMENT_BINDING})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "done"
    assert body["outbox"]["state"] == "pending", body["outbox"]

    rows = await ctx.store.query_ledger("manas_outbox", req_id=req_id)
    outcome_rows = [r for r in rows
                    if r["event_type"] == "io.manas.demand.outcome.adjudicated.v1"]
    assert len(outcome_rows) == 1
    data = json.loads(outcome_rows[0]["envelope_json"])["data"]
    assert data["verdict"] == "achieved"
    assert data["adjudication_method"] == "human"

    ledger = await ctx.store.query_ledger("outcome_ledger", req_id=req_id,
                                          stage="adjudicated")
    assert ledger and ledger[0]["verdict"] == "achieved"


async def test_adjudication_without_attestation_stays_local(client, monkeypatch):
    client, ctx = client
    set_env(monkeypatch)
    _, req_id = await drive_to_routed(client)
    resp = await client.post(f"/api/requirements/{req_id}/adjudicate", json={
        "verdict": "not_achieved", "adjudicated_by_role": "product_owner",
        "receipt": "Numbers do not reconcile with the ledger."})
    assert resp.status_code == 200
    assert resp.json()["status"] == "routed"    # not_achieved is not DONE
    assert "attestation" in resp.json()["outbox"]["reason"]


async def test_adjudication_rejects_out_of_contract_values(client, monkeypatch):
    client, _ = client
    set_env(monkeypatch)
    _, req_id = await drive_to_routed(client)
    resp = await client.post(f"/api/requirements/{req_id}/adjudicate", json={
        "verdict": "great", "adjudicated_by_role": "business_owner",
        "receipt": "x"})
    assert resp.status_code == 422


async def test_relay_reads_pending_and_acknowledges(client, monkeypatch):
    client, ctx = client
    set_env(monkeypatch)
    _, req_id = await drive_to_routed(client)

    resp = await client.get("/api/export/outbox?state=pending")
    items = resp.json()["items"]
    assert [i["req_id"] for i in items] == [req_id]
    outbox_id = items[0]["outbox_id"]

    resp = await client.post("/api/export/outbox/ack",
                             json={"outbox_id": outbox_id, "state": "shipped"})
    assert resp.status_code == 200
    states = [r["state"] for r in await ctx.store.query_ledger(
        "manas_outbox", outbox_id=outbox_id)]
    assert sorted(states) == ["pending", "shipped"]

    resp = await client.post("/api/export/outbox/ack",
                             json={"outbox_id": "nope", "state": "shipped"})
    assert resp.status_code == 404


def test_wire_timestamp_matches_the_pack_regex():
    import re
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z",
                        service.wire_ts())


def test_change_id_sanitises_to_the_pack_pattern():
    assert service.change_id_from("PROJ-123", "IPR-1") == "PROJ-123"
    assert service.change_id_from("a/b c#d", "IPR-1") == "a-b-c-d"
    assert service.change_id_from(None, "IPR-2026-000001") == "IPR-2026-000001"


# ------------------------------------------------------------------ atomicity

async def test_version_and_outbox_row_commit_or_fail_together(client, monkeypatch):
    _, ctx = client
    set_env(monkeypatch)
    from tests.conftest import make_obj
    obj = make_obj(req_id="IPR-2026-000777", ask="vendor spend x")
    row = service.build_requirement_versioned_row(obj, acceptance_text="done when fast")
    assert row is not None and row["state"] == "pending"
    await ctx.store.put_version_with_outbox(obj, row)
    assert (await ctx.store.latest(obj.req_id)).version == obj.version
    assert len(await ctx.store.query_ledger("manas_outbox", req_id=obj.req_id)) == 1

    # Same version again: the whole transaction rolls back — no orphan event.
    from core.providers.store.base import AppendOnlyViolation
    with pytest.raises(AppendOnlyViolation):
        await ctx.store.put_version_with_outbox(obj, dict(row))
    assert len(await ctx.store.query_ledger("manas_outbox", req_id=obj.req_id)) == 1


# ------------------------------------------------------------------ the relay

from core.export.manas_outbox import relay


def relay_transport(responses: list):
    """Each call pops the next (status, body). Also records requests."""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        status, body = responses.pop(0)
        return httpx.Response(status, text=body)

    return httpx.MockTransport(handler), seen


async def test_relay_ships_pending_and_stores_the_receipt(client, monkeypatch):
    client, ctx = client
    set_env(monkeypatch)
    _, req_id = await drive_to_routed(client)
    transport, seen = relay_transport([(202, '{"event_id":"e1","ingested_at":"t"}')])

    report = await relay.ship_pending(ctx.store, url="https://manas.example/ingest",
                                      token="tok", transport=transport)
    assert report["shipped"] == 1 and report["dead_lettered"] == 0
    assert seen[0].headers["authorization"] == "Bearer tok"
    assert seen[0].headers["content-type"] == "application/cloudevents+json"

    rows = await ctx.store.query_ledger("manas_outbox", req_id=req_id)
    states = {r["state"]: r for r in rows}
    assert "shipped" in states
    assert "event_id" in states["shipped"]["reason"]      # the MANAS receipt
    # Shipped rows do not ship twice.
    transport2, seen2 = relay_transport([])
    report = await relay.ship_pending(ctx.store, url="https://x", token="t",
                                      transport=transport2)
    assert report["shipped"] == 0 and not seen2


async def test_relay_dead_letters_contract_rejections_immediately(client, monkeypatch):
    client, ctx = client
    set_env(monkeypatch)
    _, req_id = await drive_to_routed(client)
    transport, _ = relay_transport([(422, "schema mismatch")])
    report = await relay.ship_pending(ctx.store, url="https://x", token="t",
                                      transport=transport)
    assert report["dead_lettered"] == 1
    rows = await ctx.store.query_ledger("manas_outbox", req_id=req_id)
    assert any(r["state"] == "dead_letter" and "schema mismatch" in r["reason"]
               for r in rows)


async def test_relay_retries_transient_failures_then_dead_letters(client, monkeypatch):
    client, ctx = client
    set_env(monkeypatch)
    _, req_id = await drive_to_routed(client)

    transport, _ = relay_transport([(503, "down")])
    report = await relay.ship_pending(ctx.store, url="https://x", token="t",
                                      transport=transport, max_attempts=2)
    assert report["failed"] == 1     # attempt_failed, still pending next pass

    transport, _ = relay_transport([(503, "still down")])
    report = await relay.ship_pending(ctx.store, url="https://x", token="t",
                                      transport=transport, max_attempts=2)
    assert report["dead_lettered"] == 1   # attempt budget spent

    states = [r["state"] for r in await ctx.store.query_ledger(
        "manas_outbox", req_id=req_id)]
    assert "attempt_failed" in states and "dead_letter" in states


async def test_relay_without_config_reports_not_ships(client):
    _, ctx = client
    report = await relay.ship_pending(ctx.store)
    assert "not configured" in report["error"]


async def test_ship_endpoint_triggers_a_pass(client, monkeypatch):
    client, ctx = client
    set_env(monkeypatch)
    resp = await client.post("/api/export/outbox/ship")
    assert resp.status_code == 200
    assert "not configured" in resp.json()["error"]
