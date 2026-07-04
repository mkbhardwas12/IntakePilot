"""I2: cost-of-delay — the ask prices its own pain, deterministically."""
from __future__ import annotations

import pathlib

import httpx
import pytest

from core.api.context import AppContext
from core.api.main import create_app
from core.agents.value import describe, extract_cost_of_delay

from tests.conftest import memory_config


def test_duration_times_cadence():
    cod = extract_cost_of_delay(
        "our monthly vendor report takes 3 days to compile by hand")
    assert cod["hours_per_occurrence"] == 24.0   # 3 days × 8h
    assert cod["frequency"] == "monthly" and cod["occurrences_per_year"] == 12
    assert cod["annual_hours"] == 288.0
    assert "hours/year" in describe(cod)

    weekly = extract_cost_of_delay("cleaning the export takes 2 hours every week")
    assert weekly["annual_hours"] == 104.0

    daily = extract_cost_of_delay("we spend 30 minutes daily reconciling this")
    assert daily["annual_hours"] == 125.0


def test_no_number_or_no_cadence_means_no_price():
    assert extract_cost_of_delay("the report is slow and painful") is None
    assert extract_cost_of_delay("takes 3 days to compile") is None  # no cadence
    assert extract_cost_of_delay("we do this monthly") is None       # no duration


@pytest.fixture
async def client():
    ctx = AppContext(memory_config())
    app = create_app(ctx)
    await ctx.seed_glossary()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as c:
        yield c


async def test_price_lands_on_draft_ticket_and_metrics(client):
    sid = (await client.post("/api/sessions", json={
        "requester": {"name": "A", "dept": "Finance Ops", "role": "Analyst"}}
    )).json()["session_id"]
    t = (await client.post(f"/api/sessions/{sid}/turns?stream=false",
                           json={"message": "our monthly vendor report takes "
                                            "3 days to compile by hand"})).json()
    slot = t["draft"]["slots"].get("cost_of_delay")
    assert slot and slot["value"]["annual_hours"] == 288.0
    assert slot["provenance"] == "extracted"

    answers = [{"question_id": q["id"], "slot_key": q["slot_key"],
                "value": (q.get("options") or ["this month"])[0]}
               for q in t["questions"]]
    await client.post(f"/api/sessions/{sid}/turns?stream=false",
                      json={"message": "success means ready in 1 hour",
                            "answers": answers})
    req_id = t["draft"]["req_id"]
    confirm = (await client.post(f"/api/requirements/{req_id}/confirm",
                                 json={"edits": {}},
                                 headers={"X-Session-Id": sid})).json()
    assert confirm["draft"]["status"] == "routed"
    body = pathlib.Path(confirm["ticket"]["path"]).read_text()
    assert "## Value (auto)" in body and "288" in body

    metrics = (await client.get("/api/metrics")).json()
    assert metrics["cost_of_delay"]["routed_annual_hours"] == 288.0
    assert metrics["cost_of_delay"]["top_backlog"][0]["req_id"] == req_id