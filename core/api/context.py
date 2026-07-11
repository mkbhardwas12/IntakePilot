"""Application context — providers built once from config, shared by routers."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from core.models import Budget, RequirementObject, Requester

from core.config import (Config, SlotSchema, load_all_slot_schemas,
                         load_config)
from core.providers import make_connectors, make_llm, make_store, make_vector
from core.agents.orchestrator import Orchestrator
from core.targets import make_target

# Cold-start glossary seed (spec 7.5): a one-time importer CLI is the real
# mechanism; these rows make the offline demo's RETRIEVE/INFER passes work.
GLOSSARY_SEED = [
    {"term": "vendor report", "maps_to": {
        "systems": ["ERP-VendorMaster", "BI-Reporting"], "team": "data-platform",
        "synonyms": ["supplier report"]}, "evidence_count": 3},
    {"term": "invoice", "maps_to": {
        "systems": ["ERP-Finance", "AP-Workflow"], "team": "finance-systems",
        "synonyms": ["billing"]}, "evidence_count": 3},
    {"term": "onboarding", "maps_to": {
        "systems": ["HRIS", "IdP-SSO"], "team": "people-tech",
        "synonyms": ["new hire"]}, "evidence_count": 3},
    {"term": "dashboard", "maps_to": {
        "systems": ["BI-Reporting"], "team": "data-platform", "synonyms": []},
        "evidence_count": 3},
    {"term": "dept:Finance Ops", "maps_to": {
        "systems": ["ERP-Finance"], "team": "finance-systems", "synonyms": []},
        "evidence_count": 3},
    # ADDENDUM-01: business vocabulary for the demo backend systems, so the
    # RETRIEVE pass can claim affected_systems without asking anyone.
    {"term": "order", "maps_to": {
        "systems": ["SAP S/4HANA (demo)", "Fulfillment DB (Postgres)"],
        "team": "order-management", "synonyms": ["orders", "order info"]},
        "evidence_count": 3},
    {"term": "goods", "maps_to": {
        "systems": ["SAP S/4HANA (demo)"], "team": "master-data",
        "synonyms": ["goods details", "materials", "products"]},
        "evidence_count": 3},
    {"term": "product line", "maps_to": {
        "systems": ["SAP S/4HANA (demo)"], "team": "master-data",
        "synonyms": ["product lines"]}, "evidence_count": 3},
]


class AppContext:
    def __init__(self, cfg: Config | None = None):
        self.cfg = cfg or load_config()
        self.schemas: dict[str, SlotSchema] = load_all_slot_schemas()
        self.schema: SlotSchema = self.schemas["default"]
        self.llm = make_llm(self.cfg)
        self.store = make_store(self.cfg)
        self.vector = make_vector(self.cfg, self.llm)
        self.orchestrator = Orchestrator(self.llm, self.store, self.vector,
                                         self.schema, self.cfg,
                                         schemas=self.schemas)
        self.target = make_target(self.cfg)
        self.connectors = make_connectors(self.cfg)  # ADDENDUM-01
        # Durable escalation observability: every fall-through to the strong
        # model leaves an outcome_ledger row (in-memory stats reset on restart).
        if hasattr(self.llm, "escalation"):
            async def _log_escalation(detail: str) -> None:
                await self.store.log("outcome_ledger", {
                    "req_id": "", "stage": "escalation", "verdict": "invoked",
                    "detail": {"failure": detail[:300]}})
            self.llm.on_escalation = _log_escalation

    async def seed_glossary(self) -> None:
        """Insert seed terms that are not present yet; never touch rows the
        learning loop has since updated (evidence_count and all)."""
        existing = {r["term"] for r in await self.store.query_ledger("glossary")}
        for row in GLOSSARY_SEED:
            if row["term"] in existing:
                continue
            await self.store.log("glossary", {
                **row, "last_confirmed": datetime.now(timezone.utc).isoformat()})

    def schema_for(self, request_type: str) -> SlotSchema:
        """The slot-schema fork for a request type; unknown types use default."""
        return self.schemas.get(request_type, self.schema)

    async def start_session(self, requester: Requester,
                            session_id: str | None = None) -> tuple[dict, RequirementObject]:
        """Create requirement + session — shared by the web sessions router
        and channel adapters (which supply deterministic session ids)."""
        req_id = await self.new_req_id()
        obj = RequirementObject(
            req_id=req_id, requester=requester, ask_verbatim="",
            question_budget=Budget(max=self.cfg.budget_max,
                                   per_turn=self.cfg.budget_per_turn))
        obj.touch("session_created", f"requester={requester.name} dept={requester.dept}")
        await self.store.put_version(obj)
        session = {
            "session_id": session_id or uuid.uuid4().hex[:12],
            "req_id": req_id,
            "turns": [],
            "pending_questions": [],
            "budget_spent": 0,
            "requester": requester.model_dump(),
            "decisions": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await self.store.put_session(session)
        return session, obj

    async def new_req_id(self) -> str:
        year = datetime.now(timezone.utc).year
        seq = await self.store.next_seq(year)
        return f"IPR-{year}-{seq:06d}"
