"""ADDENDUM-01 — backend-aware enrichment & knowledge base.

Covers: the SystemConnector fixture provider, the post-confirmation discovery
step, the system_kb knowledge base (persistence + evidence policy + refresh),
the RETRIEVE-ladder feed for future intakes, the extended invariants (backend
detail never asked; discoveries carry provenance and are auditable), and the
demo acceptance scenario from the addendum.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from core.api.context import AppContext
from core.api.main import create_app
from core.models import Provenance
from core.providers.connector.fixture import (FixtureConnector,
                                              load_fixture_connectors)
from core.providers.llm.base import LLMResult, Msg
from core.providers.llm.mock import MockLLM
from core.agents import enrichment

from tests.conftest import make_obj, memory_config

ACCEPTANCE_ASK = ("I need a report of goods details for product line X "
                  "with the order info")

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "core" / "schemas" / "systems"


# ---------- connector protocol (fixture implementation) ----------

async def test_fixture_connector_resolves_business_terms():
    connectors = load_fixture_connectors(FIXTURES_DIR)
    names = {c.name for c in connectors}
    assert {"sap_s4_demo", "fulfillment_db"} <= names

    sap = next(c for c in connectors if c.name == "sap_s4_demo")
    matches = await sap.resolve_entity("order info")
    assert [m.entity for m in matches] == ["sales_order"]
    assert (await sap.resolve_entity("goods"))[0].entity == "material"
    assert await sap.resolve_entity("unicorn") == []


async def test_fixture_connector_describes_entity_with_customizations():
    sap = FixtureConnector(FIXTURES_DIR / "sap_s4_demo.yaml")
    schema = await sap.describe_entity("sales_order")
    assert schema.backend_name == "VBAK/VBAP"
    custom_names = {c.name for c in schema.customizations}
    assert "ZZ_PRIORITY_CODE" in custom_names
    z = next(c for c in schema.customizations if c.name == "ZZ_PRIORITY_CODE")
    assert z.kind == "z_field" and z.owner_team == "order-management"

    non_sap = FixtureConnector(FIXTURES_DIR / "fulfillment_db.yaml")
    orders = await non_sap.describe_entity("orders")
    assert any(c.name == "priority_override" and c.kind == "custom_column"
               for c in orders.customizations)


async def test_list_customizations_filters_by_area():
    sap = FixtureConnector(FIXTURES_DIR / "sap_s4_demo.yaml")
    all_c = await sap.list_customizations()
    sales_c = await sap.list_customizations(area="sales")
    assert len(all_c) >= 4
    assert {c.entity for c in sales_c} == {"sales_order"}


# ---------- enrichment step ----------

@pytest.fixture
def connectors():
    return load_fixture_connectors(FIXTURES_DIR)


async def test_enrich_attaches_backend_context_with_provenance(store, vector, connectors):
    obj = make_obj(ask=ACCEPTANCE_ASK)
    value = await enrichment.enrich(obj, store, vector, connectors)
    assert value is not None

    slot = obj.slots["backend_context"]
    assert slot.provenance == Provenance.RETRIEVED          # addendum s.5
    assert slot.source and slot.source.startswith("connector:")
    entity_keys = {(e["system"], e["entity"]) for e in slot.value["entities"]}
    assert ("sap_s4_demo", "sales_order") in entity_keys     # via "order info"
    assert ("sap_s4_demo", "material") in entity_keys        # via "goods"
    assert ("fulfillment_db", "orders") in entity_keys       # non-SAP path
    all_customs = {c["name"] for e in slot.value["entities"]
                   for c in e["customizations"]}
    assert {"ZZ_PRIORITY_CODE", "ZZ_PRODUCT_LINE", "priority_override"} <= all_customs
    # Auditable (addendum s.5): the discovery left an audit event.
    assert any(e.event == "enriched" for e in obj.audit)


async def test_enrich_fills_affected_systems_without_asking(store, vector, connectors):
    obj = make_obj(ask="show me the order info for last week")
    assert "affected_systems" not in obj.slots
    await enrichment.enrich(obj, store, vector, connectors)
    slot = obj.slots["affected_systems"]
    assert slot.provenance == Provenance.RETRIEVED
    assert "SAP S/4HANA (demo)" in slot.value


async def test_enrich_no_match_is_a_clean_noop(store, vector, connectors):
    obj = make_obj(ask="paint the bikeshed cerulean")
    assert await enrichment.enrich(obj, store, vector, connectors) is None
    assert "backend_context" not in obj.slots
    assert any(e.event == "enrichment_skipped" for e in obj.audit)


# ---------- system_kb knowledge base ----------

async def test_discoveries_persist_to_system_kb_unverified(store, vector, connectors):
    obj = make_obj(ask=ACCEPTANCE_ASK)
    await enrichment.enrich(obj, store, vector, connectors)
    rows = await store.query_ledger("system_kb")
    assert len(rows) >= 3
    row = next(r for r in rows
               if r["system"] == "sap_s4_demo" and r["entity"] == "sales_order")
    assert row["evidence_count"] == 1
    assert not row["verified"]                              # raw discovery
    assert row["last_refreshed"]
    assert any(c["name"] == "ZZ_PRIORITY_CODE"
               for c in row["schema"]["customizations"])


async def test_rediscovery_never_raises_evidence_count(store, vector, connectors):
    """Only human-originated validation raises evidence (addendum s.5)."""
    obj = make_obj(ask=ACCEPTANCE_ASK)
    await enrichment.enrich(obj, store, vector, connectors)
    obj2 = make_obj(req_id="IPR-2026-000002", ask=ACCEPTANCE_ASK)
    await enrichment.enrich(obj2, store, vector, connectors)
    rows = await store.query_ledger("system_kb", system="sap_s4_demo",
                                    entity="sales_order")
    assert rows[0]["evidence_count"] == 1 and not rows[0]["verified"]

    await enrichment.mark_validated(store, "sap_s4_demo", "sales_order")
    rows = await store.query_ledger("system_kb", system="sap_s4_demo",
                                    entity="sales_order")
    assert rows[0]["evidence_count"] == 2 and rows[0]["verified"]


async def test_system_kb_feeds_retrieve_ladder_for_future_intakes(
        orchestrator, connectors):
    """A discovery made for one requirement serves the next intake at turn
    time — backend_context arrives with provenance=retrieved, source system_kb,
    before any confirmation and without a single question."""
    store, vector = orchestrator.store, orchestrator.vector
    first = make_obj(ask=ACCEPTANCE_ASK)
    await enrichment.enrich(first, store, vector, connectors)

    from tests.conftest import seed
    obj = make_obj(req_id="IPR-2026-000099",
                   ask="weekly summary of sales orders by region")
    session = await seed(store, obj)
    result = await orchestrator.handle_turn(
        session, "weekly summary of sales orders by region", [])
    slot = result.draft.slots.get("backend_context")
    assert slot is not None
    assert slot.provenance == Provenance.RETRIEVED
    assert slot.source.startswith("system_kb:")
    assert any(e["entity"] == "sales_order" for e in slot.value["entities"])


async def test_refresh_system_kb_picks_up_changed_customizations(
        store, vector, tmp_path):
    fixture = tmp_path / "sys.yaml"
    fixture.write_text(FIXTURES_DIR.joinpath("sap_s4_demo.yaml").read_text())
    conn = FixtureConnector(fixture)
    obj = make_obj(ask="order info please")
    await enrichment.enrich(obj, store, vector, [conn])

    # A new Z-field appears in the backend; nightly refresh must pick it up.
    fixture.write_text(fixture.read_text().replace(
        "customizations:\n      - name: ZZ_PRIORITY_CODE",
        "customizations:\n      - name: ZZ_NEW_FIELD\n        type: CHAR(1)\n"
        "        kind: z_field\n        owner_team: order-management\n"
        "        description: Added overnight.\n      - name: ZZ_PRIORITY_CODE"))
    conn.reload()
    refreshed = await enrichment.refresh_system_kb(store, vector, [conn])
    assert refreshed >= 1
    rows = await store.query_ledger("system_kb", system="sap_s4_demo",
                                    entity="sales_order")
    assert any(c["name"] == "ZZ_NEW_FIELD"
               for c in rows[0]["schema"]["customizations"])


# ---------- extended invariants ----------

class BackendCuriousLLM(MockLLM):
    """Model that tries to ask the requester about backend detail."""

    async def complete(self, messages: list[Msg], **kw) -> LLMResult:
        system = next((m.content for m in messages if m.role == "system"), "")
        if "TASK: question" in system:
            return LLMResult(text=json.dumps({"questions": [
                {"slot_key": "backend_context",
                 "text": "Which SAP Z-fields does your order table use?",
                 "because": "rogue"},
                {"slot_key": "urgency", "text": "How soon?", "because": "ok"},
            ]}))
        return await super().complete(messages, **kw)


async def test_backend_context_is_unaskable(schema):
    assert schema.slots["backend_context"].askable is False
    assert "backend_context" in schema.unaskable_keys()


async def test_backend_detail_never_reaches_requester(cfg, schema):
    """Extended invariant: even a model that tries to ask about Z-fields is
    filtered by the composer/orchestrator — in code, not in the prompt."""
    from tests.conftest import seed
    from tests.test_invariants import make_orch
    orch, store = make_orch(BackendCuriousLLM(), schema, cfg)
    obj = make_obj(ask="qzx unmappable thing")
    session = await seed(store, obj)
    result = await orch.handle_turn(session, "qzx unmappable thing", [])
    assert all(q.slot_key != "backend_context" for q in result.questions)
    assert all("z-field" not in q.text.lower() for q in result.questions)


# ---------- demo acceptance (addendum) ----------

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


async def test_acceptance_goods_report_ticket_shows_undisclosed_z_field(client):
    """The ask routes with backend_context listing order/material entities
    including ZZ_PRIORITY_CODE — which the requester was never asked about —
    under a 'System context (auto-discovered)' ticket section."""
    client, ctx = client
    resp = await client.post("/api/sessions", json={
        "requester": {"name": "Pat", "dept": "Sales Ops", "role": "Analyst"}})
    sid, req_id = resp.json()["session_id"], resp.json()["req_id"]

    turn = (await client.post(f"/api/sessions/{sid}/turns?stream=false",
                              json={"message": ACCEPTANCE_ASK})).json()
    # Zero backend knowledge required: no question mentions systems, tables,
    # fields, or SAP anything.
    for q in turn["questions"]:
        assert q["slot_key"] in ("business_outcome", "urgency",
                                 "success_criteria", "scope_boundaries")
        assert "sap" not in q["text"].lower()
        assert "z_" not in q["text"].lower() and "zz_" not in q["text"].lower()

    answers = [{"question_id": q["id"], "slot_key": q["slot_key"],
                "value": ("this month" if q["slot_key"] == "urgency"
                          else "report available in under 1 hour")}
               for q in turn["questions"]]
    await client.post(f"/api/sessions/{sid}/turns?stream=false",
                      json={"message": "", "answers": answers})

    confirm = (await client.post(f"/api/requirements/{req_id}/confirm",
                                 json={"confirmed_by": "Pat"},
                                 headers={"X-Session-Id": sid})).json()
    assert confirm["draft"]["status"] == "routed"
    assert all(g["passed"] for g in confirm["gates"])

    slot = confirm["draft"]["slots"]["backend_context"]
    assert slot["provenance"] == "retrieved"
    customs = {c["name"] for e in slot["value"]["entities"]
               for c in e["customizations"]}
    assert "ZZ_PRIORITY_CODE" in customs

    ticket_text = Path(confirm["ticket"]["path"]).read_text()
    assert "## System context (auto-discovered)" in ticket_text
    assert "ZZ_PRIORITY_CODE" in ticket_text
    assert "never asked" in ticket_text

    # Discoveries landed in the knowledge base, unverified, evidence 1.
    kb = await ctx.store.query_ledger("system_kb")
    assert any(r["entity"] == "sales_order" for r in kb)
    assert all(r["evidence_count"] == 1 and not r["verified"] for r in kb)

    # And the metrics endpoint reports the KB growth.
    metrics = (await client.get("/api/metrics")).json()
    assert metrics["system_kb"]["entities"] >= 3
    assert metrics["system_kb"]["customizations"] >= 4
