"""E: schema forks per request type — deterministic classification, per-type
slot schemas with default fallback, and real context buckets."""
from __future__ import annotations

import httpx
import pytest

from core.api.context import AppContext
from core.api.main import create_app
from core.config import load_all_slot_schemas, load_slot_schema
from core.models import Budget, RequirementObject, Requester
from core.agents.request_type import classify_request_type

from tests.conftest import memory_config


def test_classifier_is_deterministic_and_sane():
    assert classify_request_type(
        "the vendor export fails with an error every morning") == "bug_report"
    assert classify_request_type(
        "our monthly vendor report takes 3 days to compile by hand") == "data_request"
    assert classify_request_type(
        "automate the onboarding workflow for new hires") == "new_capability"
    assert classify_request_type("hello there") == "default"
    # ties break toward the higher-priority type: a broken report is a bug
    assert classify_request_type("the report is broken") == "bug_report"


def test_schema_forks_load_with_default_fallback():
    schemas = load_all_slot_schemas()
    assert {"default", "bug_report", "data_request"} <= set(schemas)
    assert "expected_behavior" in schemas["bug_report"].slots
    assert "refresh_frequency" in schemas["data_request"].slots
    # unknown type falls back to default at load time
    assert load_slot_schema(request_type="nope").slots.keys() \
        == schemas["default"].slots.keys()
    # every fork keeps the unaskable invariant slots
    for schema in schemas.values():
        assert schema.slots["affected_systems"].askable is False
        assert schema.slots["backend_context"].askable is False


def test_context_bucket_carries_the_type():
    obj = RequirementObject(req_id="IPR-1", requester=Requester(dept="Finance Ops"),
                            ask_verbatim="x", question_budget=Budget(max=7, per_turn=3))
    assert obj.context_bucket == "Finance Ops:default"
    obj.request_type = "bug_report"
    assert obj.context_bucket == "Finance Ops:bug_report"


@pytest.fixture
async def client():
    ctx = AppContext(memory_config())
    app = create_app(ctx)
    await ctx.seed_glossary()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as c:
        yield c


async def test_bug_ask_gets_the_bug_schema(client):
    sid = (await client.post("/api/sessions", json={
        "requester": {"name": "A", "dept": "Ops", "role": "Analyst"}}
    )).json()["session_id"]
    t = (await client.post(f"/api/sessions/{sid}/turns?stream=false",
                           json={"message": "the vendor export fails with an "
                                            "error every morning"})).json()
    draft = t["draft"]
    assert draft["request_type"] == "bug_report"
    assert any(e["event"] == "request_type_classified" for e in draft["audit"])
    # questions come from the fork's slots only
    for q in t["questions"]:
        assert q["slot_key"] in load_all_slot_schemas()["bug_report"].slots


async def test_schema_endpoint_serves_forks(client):
    r = (await client.get("/api/schema?type=bug_report")).json()
    assert r["request_type"] == "bug_report"
    assert "expected_behavior" in r["slots"]
    fallback = (await client.get("/api/schema?type=unknown")).json()
    assert fallback["request_type"] == "default"
    assert "bug_report" in fallback["available_types"]