"""I1: portfolio collisions — two DIFFERENT open requirements touching the
same backend entities are connected at confirmation (gate 4 only catches
sameness; this catches interference)."""
from __future__ import annotations

import httpx
import pytest

from core.api.context import AppContext
from core.api.main import create_app
from core.models import Budget, Provenance, RequirementObject, Requester, Slot, Status
from core.agents.impact import collision_section, entity_keys

from tests.conftest import memory_config

SAP_ASK_1 = "I need a report of goods details for product line X with the order info"
SAP_ASK_2 = "please add priority handling for the order info feed in SAP"


def test_entity_keys_from_backend_context_and_systems():
    obj = RequirementObject(req_id="IPR-1", requester=Requester(),
                            ask_verbatim="x", question_budget=Budget(max=7, per_turn=3))
    obj.slots["backend_context"] = Slot(
        value={"systems": ["SAP"], "entities": [
            {"system": "sap_s4_demo", "entity": "sales_order"}]},
        provenance=Provenance.RETRIEVED, confidence=0.7, source="t")
    obj.slots["affected_systems"] = Slot(value=["SAP S/4HANA (demo)"],
                                         provenance=Provenance.RETRIEVED,
                                         confidence=0.7, source="t")
    keys = entity_keys(obj)
    assert "sap_s4_demo:sales_order" in keys
    assert "system:sap s/4hana (demo)" in keys


def test_collision_section_renders_markdown():
    md = collision_section([{"req_id": "IPR-9", "status": "routed",
                             "queue": "order-management",
                             "shared": ["sap_s4_demo:sales_order"]}])
    assert "IPR-9" in md and "sales_order" in md and "## Impact" in md
    assert collision_section([]) == ""


@pytest.fixture
async def client():
    ctx = AppContext(memory_config())
    app = create_app(ctx)
    await ctx.seed_glossary()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as c:
        yield c


async def _confirmed(c, ask):
    sid = (await c.post("/api/sessions", json={
        "requester": {"name": "A", "dept": "Ops", "role": "Analyst"}}
    )).json()["session_id"]
    t = (await c.post(f"/api/sessions/{sid}/turns?stream=false",
                      json={"message": ask})).json()
    answers = [{"question_id": q["id"], "slot_key": q["slot_key"],
                "value": (q.get("options") or ["this month"])[0]}
               for q in t["questions"]]
    await c.post(f"/api/sessions/{sid}/turns?stream=false",
                 json={"message": "success means it works in under 1 hour",
                       "answers": answers})
    req_id = t["draft"]["req_id"]
    confirm = (await c.post(f"/api/requirements/{req_id}/confirm",
                            json={"edits": {}},
                            headers={"X-Session-Id": sid})).json()
    return req_id, confirm


async def test_second_ask_on_same_entity_reports_collision(client):
    r1, c1 = await _confirmed(client, SAP_ASK_1)
    assert c1["draft"]["status"] == "routed"
    assert c1["collisions"] == []  # nothing open yet

    r2, c2 = await _confirmed(client, SAP_ASK_2)
    hit = next((h for h in c2["collisions"] if h["req_id"] == r1), None)
    assert hit is not None, f"expected collision with {r1}: {c2['collisions']}"
    assert any("sales_order" in k or "sap" in k for k in hit["shared"])
    # not a duplicate: different ask, gates untouched by the collision
    g4 = next(g for g in c2["gates"] if g["gate"] == 4)
    assert g4["passed"] is True
    # the routed ticket carries the impact section
    if c2["ticket"]:
        import pathlib
        body = pathlib.Path(c2["ticket"]["path"]).read_text()
        assert "## Impact" in body and r1 in body


async def test_unrelated_asks_do_not_collide(client):
    await _confirmed(client, SAP_ASK_1)
    _, c2 = await _confirmed(client,
                             "the onboarding portal needs a new approval workflow")
    assert all("sales_order" not in " ".join(h["shared"])
               for h in c2["collisions"])


async def test_graph_endpoint_shows_hotspots(client):
    await _confirmed(client, SAP_ASK_1)
    await _confirmed(client, SAP_ASK_2)
    g = (await client.get("/api/graph")).json()
    assert {"nodes", "edges", "hotspots"} <= set(g)
    kinds = {n["kind"] for n in g["nodes"]}
    assert {"requirement", "entity"} <= kinds
    assert g["hotspots"], "shared entity should be a hotspot"