"""MANAS Demand exporter tests — metadata-only CloudEvents emission.

Tests cover:
  - No free text leakage (values are hashed)
  - No PII patterns in emitted data
  - asked/corrected/observed fire on existing flows
  - Hashes are stable (deterministic)
  - Only askable slots emit asked events
  - Field token join identity for synthetic walk fixture
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from core.export import manas_demand
from core.export.manas_demand import (
    DemandEvent, ListSink, FileSink, NullSink,
    configure_sink, emit_asked, emit_corrected, emit_observed,
    hash_slot_value, extract_implicated_fields,
    ASKABLE_SLOTS, EVENT_SOURCE,
)


PII_PATTERNS = [
    re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{4}\d{7}[A-Z0-9]{0,18}\b"),  # IBAN
    re.compile(r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b"),  # PAN
    re.compile(r"\b[A-Z0-9]{11,17}\b"),  # VIN-like
    re.compile(r"\b[\w.-]+@[\w.-]+\.\w{2,}\b", re.I),  # email
    re.compile(r"\b(hostname|sid|landscape)\b", re.I),  # env identifiers
]


def has_pii(text: str) -> bool:
    """Check if text contains PII-like patterns."""
    for pattern in PII_PATTERNS:
        if pattern.search(text):
            return True
    return False


class TestHashSlotValue:
    def test_hash_is_deterministic(self):
        value = "monthly vendor report takes 3 days"
        h1 = hash_slot_value(value)
        h2 = hash_slot_value(value)
        assert h1 == h2
        assert len(h1) == 64  # sha256 hex

    def test_hash_differs_for_different_values(self):
        h1 = hash_slot_value("value one")
        h2 = hash_slot_value("value two")
        assert h1 != h2

    def test_hash_handles_list(self):
        h = hash_slot_value(["ERP-VendorMaster", "BI-Reporting"])
        assert len(h) == 64
        assert hash_slot_value(["ERP-VendorMaster", "BI-Reporting"]) == h

    def test_hash_handles_none(self):
        assert hash_slot_value(None) == ""

    def test_hash_handles_empty_string(self):
        assert hash_slot_value("") == ""


class TestSinks:
    async def test_null_sink_discards(self):
        sink = NullSink()
        event = DemandEvent(
            type="io.manas.demand.asked",
            id="test",
            time="2026-08-22T00:00:00Z",
            data={"test": True},
        )
        await sink.write(event)

    async def test_list_sink_collects(self):
        sink = ListSink()
        event = DemandEvent(
            type="io.manas.demand.asked",
            id="test",
            time="2026-08-22T00:00:00Z",
            data={"test": True},
        )
        await sink.write(event)
        assert len(sink.events) == 1
        assert sink.events[0].type == "io.manas.demand.asked"

    async def test_file_sink_appends(self, tmp_path):
        path = tmp_path / "manas_demand.jsonl"
        sink = FileSink(path)
        event = DemandEvent(
            type="io.manas.demand.observed",
            id="test",
            time="2026-08-22T00:00:00Z",
            data={"fields": []},
        )
        await sink.write(event)
        await sink.write(event)
        
        lines = path.read_text().strip().split("\n")
        assert len(lines) == 2
        for line in lines:
            parsed = json.loads(line)
            assert parsed["type"] == "io.manas.demand.observed"


class TestConfigureSink:
    def test_default_is_null_sink(self):
        configure_sink()
        assert isinstance(manas_demand.get_sink(), NullSink)

    def test_configure_list_sink(self):
        sink = ListSink()
        configure_sink(sink=sink)
        assert manas_demand.get_sink() is sink

    def test_configure_file_sink(self, tmp_path):
        path = str(tmp_path / "test.jsonl")
        result = configure_sink(file_path=path)
        assert isinstance(result, FileSink)


class TestEmitAsked:
    @pytest.fixture(autouse=True)
    def setup_sink(self):
        self.sink = ListSink()
        configure_sink(sink=self.sink)
        yield
        configure_sink()

    async def test_emits_for_askable_slot(self):
        event = await emit_asked(
            req_id="IPR-2026-000001",
            slot_key="business_outcome",
            value_hash=hash_slot_value("reduce report time from 3 days to 1 hour"),
            provenance="extracted",
            context_bucket="Finance Ops:data_request",
        )
        assert event is not None
        assert event.type == "io.manas.demand.asked"
        assert event.source == EVENT_SOURCE
        assert event.verified is True
        assert len(self.sink.events) == 1

    async def test_does_not_emit_for_non_askable_slot(self):
        event = await emit_asked(
            req_id="IPR-2026-000001",
            slot_key="affected_systems",  # askable: false
            value_hash=hash_slot_value("SAP"),
            provenance="retrieved",
            context_bucket="Finance Ops:data_request",
        )
        assert event is None
        assert len(self.sink.events) == 0

    async def test_does_not_emit_for_backend_context(self):
        event = await emit_asked(
            req_id="IPR-2026-000001",
            slot_key="backend_context",  # never emitted
            value_hash=hash_slot_value("some context"),
            provenance="retrieved",
            context_bucket="Finance Ops:data_request",
        )
        assert event is None

    async def test_emitted_data_contains_no_free_text(self):
        original_value = "monthly vendor report takes 3 days to compile"
        event = await emit_asked(
            req_id="IPR-2026-000001",
            slot_key="business_outcome",
            value_hash=hash_slot_value(original_value),
            provenance="extracted",
            context_bucket="Finance Ops:data_request",
        )
        event_json = event.model_dump_json()
        assert original_value not in event_json
        assert "vendor" not in event_json
        assert "report" not in event_json

    async def test_all_askable_slots_emit(self):
        for slot_key in ASKABLE_SLOTS:
            event = await emit_asked(
                req_id="IPR-2026-000001",
                slot_key=slot_key,
                value_hash=hash_slot_value("test value"),
                provenance="answered",
                context_bucket="Test:default",
            )
            assert event is not None, f"Failed for {slot_key}"


class TestEmitCorrected:
    @pytest.fixture(autouse=True)
    def setup_sink(self):
        self.sink = ListSink()
        configure_sink(sink=self.sink)
        yield
        configure_sink()

    async def test_emits_for_askable_slot_correction(self):
        event = await emit_corrected(
            req_id="IPR-2026-000001",
            slot_key="success_criteria",
            proposed_hash=hash_slot_value("report in under 1 hour"),
            corrected_hash=hash_slot_value("report in under 30 minutes"),
            provenance="extracted",
            context_bucket="Finance Ops:data_request",
        )
        assert event is not None
        assert event.type == "io.manas.demand.corrected"
        assert event.verified is True
        assert event.data["proposed_hash"] != event.data["corrected_hash"]

    async def test_does_not_emit_for_non_askable_slot(self):
        event = await emit_corrected(
            req_id="IPR-2026-000001",
            slot_key="affected_systems",
            proposed_hash=hash_slot_value("SAP"),
            corrected_hash=hash_slot_value("SAP, BW4"),
            provenance="retrieved",
            context_bucket="Finance Ops:data_request",
        )
        assert event is None

    async def test_emitted_data_contains_no_original_values(self):
        proposed = "report compiles in under 1 hour"
        corrected = "report compiles in under 30 minutes"
        event = await emit_corrected(
            req_id="IPR-2026-000001",
            slot_key="success_criteria",
            proposed_hash=hash_slot_value(proposed),
            corrected_hash=hash_slot_value(corrected),
            provenance="extracted",
            context_bucket="Finance Ops:data_request",
        )
        event_json = event.model_dump_json()
        assert proposed not in event_json
        assert corrected not in event_json
        assert "30 minutes" not in event_json


class TestEmitObserved:
    @pytest.fixture(autouse=True)
    def setup_sink(self):
        self.sink = ListSink()
        configure_sink(sink=self.sink)
        yield
        configure_sink()

    async def test_emits_implicated_fields(self):
        fields = [
            {"table": "VBAK", "field": "ZZ_PRIORITY_CODE", "kind": "z_field", "owner_team": "order-management"},
            {"table": "MARA", "field": "ZZ_PRODUCT_LINE", "kind": "append_field", "owner_team": "master-data"},
        ]
        event = await emit_observed(
            req_id="IPR-2026-000001",
            implicated_fields=fields,
            context_bucket="Sales Ops:data_request",
        )
        assert event is not None
        assert event.type == "io.manas.demand.observed"
        assert event.verified is True
        assert len(event.data["implicated_fields"]) == 2
        assert event.data["implicated_fields"][0]["provenance"] == "retrieved"

    async def test_does_not_emit_if_no_fields(self):
        event = await emit_observed(
            req_id="IPR-2026-000001",
            implicated_fields=[],
            context_bucket="Sales Ops:data_request",
        )
        assert event is None
        assert len(self.sink.events) == 0

    async def test_emitted_data_contains_metadata_only(self):
        fields = [
            {"table": "VBAK", "field": "ZZ_PRIORITY_CODE", "kind": "z_field",
             "owner_team": "order-management", "row_value": "SHOULD NOT APPEAR"},
        ]
        event = await emit_observed(
            req_id="IPR-2026-000001",
            implicated_fields=fields,
            context_bucket="Sales Ops:data_request",
        )
        event_json = event.model_dump_json()
        assert "SHOULD NOT APPEAR" not in event_json
        assert "row_value" not in event_json

    async def test_field_token_join_identity(self):
        """Test the synthetic walk join: priority at table VBAK (ZZ_PRIORITY_CODE)."""
        fields = [
            {"table": "VBAK/VBAP", "field": "ZZ_PRIORITY_CODE", "kind": "z_field",
             "owner_team": "order-management"},
        ]
        event = await emit_observed(
            req_id="IPR-2026-000001",
            implicated_fields=fields,
            context_bucket="Sales Ops:data_request",
        )
        implicated = event.data["implicated_fields"][0]
        assert implicated["field"] == "ZZ_PRIORITY_CODE"
        assert "VBAK" in implicated["table"]


class TestExtractImplicatedFields:
    def test_extracts_from_backend_context(self):
        backend_context = {
            "entities": [
                {
                    "backend_name": "VBAK/VBAP",
                    "customizations": [
                        {"name": "ZZ_PRIORITY_CODE", "kind": "z_field", "owner_team": "order-management"},
                        {"name": "ZZ_EXPEDITE_FLAG", "kind": "append_field", "owner_team": "order-management"},
                    ]
                },
                {
                    "backend_name": "MARA",
                    "customizations": [
                        {"name": "ZZ_PRODUCT_LINE", "kind": "append_field", "owner_team": "master-data"},
                    ]
                }
            ]
        }
        fields = extract_implicated_fields(backend_context)
        assert len(fields) == 3
        
        zz_priority = next(f for f in fields if f["field"] == "ZZ_PRIORITY_CODE")
        assert zz_priority["table"] == "VBAK/VBAP"
        assert zz_priority["kind"] == "z_field"
        assert zz_priority["owner_team"] == "order-management"

    def test_handles_empty_context(self):
        assert extract_implicated_fields({}) == []
        assert extract_implicated_fields({"entities": []}) == []


class TestNoPIILeakage:
    @pytest.fixture(autouse=True)
    def setup_sink(self):
        self.sink = ListSink()
        configure_sink(sink=self.sink)
        yield
        configure_sink()

    async def test_no_pii_in_asked_event(self):
        pii_value = "Contact john.doe@example.com for IBAN DE89370400440532013000"
        event = await emit_asked(
            req_id="IPR-2026-000001",
            slot_key="business_outcome",
            value_hash=hash_slot_value(pii_value),
            provenance="extracted",
            context_bucket="Finance Ops:data_request",
        )
        event_json = event.model_dump_json()
        assert not has_pii(event_json), f"PII detected in: {event_json}"
        assert "john.doe" not in event_json
        assert "example.com" not in event_json
        assert "DE89" not in event_json

    async def test_no_pii_in_corrected_event(self):
        pii_proposed = "VIN: WVWZZZ3CZWE123456"
        pii_corrected = "VIN: 1G1YY22G965109876"
        event = await emit_corrected(
            req_id="IPR-2026-000001",
            slot_key="data_fields",
            proposed_hash=hash_slot_value(pii_proposed),
            corrected_hash=hash_slot_value(pii_corrected),
            provenance="extracted",
            context_bucket="Finance Ops:data_request",
        )
        event_json = event.model_dump_json()
        assert "WVWZZZ" not in event_json
        assert "1G1YY" not in event_json


class TestNoEnvironmentIdentifiers:
    @pytest.fixture(autouse=True)
    def setup_sink(self):
        self.sink = ListSink()
        configure_sink(sink=self.sink)
        yield
        configure_sink()

    async def test_no_hostname_in_events(self):
        event = await emit_observed(
            req_id="IPR-2026-000001",
            implicated_fields=[
                {"table": "VBAK", "field": "ZZ_PRIORITY_CODE", "kind": "z_field", "owner_team": "order-management"}
            ],
            context_bucket="Sales Ops:data_request",
        )
        event_json = event.model_dump_json().lower()
        assert "hostname" not in event_json
        assert "sid" not in event_json.split(":")  # avoid false positive on req_id
        assert "landscape" not in event_json


class TestIntegrationWithExistingFlows:
    """Integration tests verifying MANAS demand hooks fire on actual flows."""

    @pytest.fixture
    def connectors(self):
        from pathlib import Path
        from core.providers.connector.fixture import load_fixture_connectors
        fixtures_dir = Path(__file__).resolve().parent.parent / "core" / "schemas" / "systems"
        return load_fixture_connectors(fixtures_dir)

    @pytest.fixture(autouse=True)
    def setup_sink(self):
        self.sink = ListSink()
        configure_sink(sink=self.sink)
        yield
        configure_sink()

    async def test_enrichment_emits_observed(self, store, vector, connectors):
        """Verify enrichment triggers emit_observed with fixture backend entities."""
        from core.agents import enrichment
        from tests.conftest import make_obj

        obj = make_obj(ask="I need a report of goods details for product line X with the order info")
        await enrichment.enrich(obj, store, vector, connectors)

        observed_events = [e for e in self.sink.events if e.type == "io.manas.demand.observed"]
        assert len(observed_events) == 1
        
        event = observed_events[0]
        fields = event.data["implicated_fields"]
        field_names = {f["field"] for f in fields}
        assert "ZZ_PRIORITY_CODE" in field_names
        assert "ZZ_PRODUCT_LINE" in field_names

    async def test_orchestrator_emits_asked_on_extraction(self, orchestrator, store):
        """Verify orchestrator triggers emit_asked when slots are extracted."""
        from tests.conftest import make_obj, seed

        ask = "our monthly vendor report takes 3 days to compile by hand"
        obj = make_obj(ask=ask)
        session = await seed(store, obj)
        
        await orchestrator.handle_turn(session, ask, [])
        
        asked_events = [e for e in self.sink.events if e.type == "io.manas.demand.asked"]
        assert len(asked_events) > 0
        
        slot_keys = {e.data["slot_key"] for e in asked_events}
        assert slot_keys <= ASKABLE_SLOTS
        assert "business_outcome" in slot_keys

    async def test_full_golden_flow_emits_all_event_types(self, tmp_path, connectors):
        """End-to-end test: session -> turns -> confirm emits asked, corrected, observed."""
        import httpx
        from core.api.context import AppContext
        from core.api.main import create_app
        from tests.conftest import memory_config

        cfg = memory_config()
        cfg.demo_repo = str(tmp_path / "demo-repo")
        ctx = AppContext(cfg)
        app = create_app(ctx)

        async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test") as client:
            await ctx.seed_glossary()

            resp = await client.post("/api/sessions", json={
                "requester": {"name": "Test", "dept": "Sales Ops", "role": "Analyst"}
            })
            sid, req_id = resp.json()["session_id"], resp.json()["req_id"]

            turn = (await client.post(
                f"/api/sessions/{sid}/turns?stream=false",
                json={"message": "I need a report of goods details with the order info"}
            )).json()

            answers = [
                {"question_id": q["id"], "slot_key": q["slot_key"],
                 "value": "this month" if q["slot_key"] == "urgency" else "report in under 1 hour"}
                for q in turn["questions"]
            ]
            await client.post(
                f"/api/sessions/{sid}/turns?stream=false",
                json={"message": "", "answers": answers}
            )

            await client.post(
                f"/api/requirements/{req_id}/confirm",
                json={"edits": {"success_criteria": "report in under 30 minutes"},
                      "confirmed_by": "Test"},
                headers={"X-Session-Id": sid}
            )

        event_types = {e.type for e in self.sink.events}
        assert "io.manas.demand.asked" in event_types
        assert "io.manas.demand.corrected" in event_types
        assert "io.manas.demand.observed" in event_types

        for event in self.sink.events:
            assert event.verified is True
            event_json = event.model_dump_json()
            assert not has_pii(event_json)
