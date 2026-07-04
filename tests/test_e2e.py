"""Golden scenario #1 end-to-end through the HTTP API (Milestone 3 'done when'),
plus learning-loop capture. Runs entirely on the mock provider — no model."""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from core.api.context import AppContext
from core.api.main import create_app
from core.learning import exemplars as learning

from tests.conftest import memory_config

ASK = "our monthly vendor report takes 3 days to compile by hand"


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


async def test_golden_scenario_vendor_report(client):
    client, ctx = client

    resp = await client.post("/api/sessions", json={
        "requester": {"name": "Demo User", "dept": "Finance Ops", "role": "Analyst"}})
    assert resp.status_code == 200
    sid, req_id = resp.json()["session_id"], resp.json()["req_id"]
    assert req_id.startswith("IPR-")

    # Turn 1 — the ask. Slots extracted, glossary retrieval fires, <= 3 questions.
    resp = await client.post(f"/api/sessions/{sid}/turns?stream=false",
                             json={"message": ASK})
    turn = resp.json()
    slots = turn["draft"]["slots"]
    assert "vendor report" in slots["business_outcome"]["value"].lower()
    assert slots["business_outcome"]["provenance"] == "extracted"
    assert slots["affected_systems"]["provenance"] == "retrieved"  # glossary hit
    assert "ERP-VendorMaster" in slots["affected_systems"]["value"]
    assert 1 <= len(turn["questions"]) <= 3
    asked_keys = {q["slot_key"] for q in turn["questions"]}
    assert "affected_systems" not in asked_keys  # askable:false
    assert "data_sensitivity" not in asked_keys

    # Turn 2 — answer the questions via chips.
    answers = [{"question_id": q["id"], "slot_key": q["slot_key"],
                "value": ("this month" if q["slot_key"] == "urgency"
                          else "report compiles in under 1 hour")}
               for q in turn["questions"]]
    resp = await client.post(f"/api/sessions/{sid}/turns?stream=false",
                             json={"message": "", "answers": answers})
    turn2 = resp.json()
    draft = turn2["draft"]
    for a in answers:
        assert draft["slots"][a["slot_key"]]["provenance"] == "answered"
    # Budget-exhausted/no-askable-gaps path applied the schema default:
    assert draft["slots"]["data_sensitivity"]["provenance"] == "assumed"
    assert "data_sensitivity" in draft["assumptions"]
    assert draft["readiness_score"] >= 70
    assert turn2["confirm_unlocked"] is True

    # Confirm with one human edit — the learning asset.
    resp = await client.post(f"/api/requirements/{req_id}/confirm", json={
        "edits": {"affected_systems": ["ERP-VendorMaster", "BI-Reporting", "BW4"]},
        "confirmed_by": "Demo User"}, headers={"X-Session-Id": sid})
    confirm = resp.json()
    assert all(g["passed"] for g in confirm["gates"])
    assert len(confirm["gates"]) == 5
    assert confirm["routing"]["queue"] == "data-platform"
    assert confirm["routing"]["explanation"]
    assert confirm["draft"]["status"] == "routed"

    # The ticket file appears in the demo repo.
    ticket = confirm["ticket"]
    assert ticket is not None
    path = Path(ticket["path"])
    assert path.exists()
    content = path.read_text()
    assert req_id in content and "vendor report" in content.lower()

    # Edit was captured to the edit_diffs ledger with proposed vs corrected.
    diffs = await ctx.store.query_ledger("edit_diffs", req_id=req_id)
    assert len(diffs) == 1
    assert diffs[0]["slot_key"] == "affected_systems"
    assert "BW4" in diffs[0]["corrected"]

    # And the correction is now selectable as an exemplar for similar asks.
    exemplar_text = await learning.select_exemplars(
        ctx.vector, agent="intake", context="Finance Ops:data_request",
        ask="our quarterly supplier report is compiled by hand")
    assert "BW4" in exemplar_text and "affected_systems" in exemplar_text

    # History is append-only and complete.
    resp = await client.get(f"/api/requirements/{req_id}/history",
                            headers={"X-Session-Id": sid})
    versions = [o["version"] for o in resp.json()]
    assert versions == sorted(versions) and len(versions) >= 4

    # Metrics reflect the run.
    metrics = (await client.get("/api/metrics")).json()
    assert metrics["totals"]["confirmed"] == 1
    assert metrics["totals"]["routed"] == 1
    assert metrics["totals"]["edits"] == 1
    assert metrics["edit_rate_per_field"].get("affected_systems") == 1.0


async def test_sse_stream_emits_contract_events(client):
    client, ctx = client
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
    assert "status" in events and "slot" in events
    assert "readiness" in events and "questions" in events
    assert events[-1] == "done"
