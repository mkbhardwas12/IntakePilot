"""Structural learning: repeated identical corrections surface as glossary
proposals; a human accept (and only that) turns them into vocabulary."""
from __future__ import annotations

import httpx
import pytest

from core.api.context import AppContext
from core.api.main import create_app
from core.models import Budget, RequirementObject, Requester
from core.learning import exemplars as learning
from core.learning.proposals import glossary_proposals
from core.providers.llm.mock import MockLLM
from core.providers.store.sqlite import SqliteStore
from core.providers.vector.local import LocalVectorIndex

from tests.conftest import memory_config


async def _seed_edits(store, vector, n: int, ask_prefix: str = "the procurement cube for") -> None:
    for i in range(n):
        obj = RequirementObject(
            req_id=f"IPR-2026-0000{i + 10}", requester=Requester(dept="Finance Ops"),
            ask_verbatim=f"{ask_prefix} region {i} is assembled by hand",
            question_budget=Budget(max=7, per_turn=3))
        await store.put_version(obj)
        await learning.capture_edit(store, vector, obj, "affected_systems",
                                    ["BI-Reporting"], ["BI-Reporting", "SRM"],
                                    provenance="retrieved")


async def test_repeated_corrections_become_a_proposal():
    store = SqliteStore({"path": ":memory:"})
    vector = LocalVectorIndex(MockLLM({"dim": 16}), {"path": ":memory:"})
    await _seed_edits(store, vector, 3)

    props = await glossary_proposals(store)
    assert len(props) == 1
    p = props[0]
    assert p["slot_key"] == "affected_systems"
    assert p["occurrences"] == 3
    assert "srm" in [s.lower() for s in p["corrected"]]
    assert p["suggested_term"] == "procurement"
    assert len(p["sample_asks"]) == 3


async def test_below_threshold_is_not_proposed():
    store = SqliteStore({"path": ":memory:"})
    vector = LocalVectorIndex(MockLLM({"dim": 16}), {"path": ":memory:"})
    await _seed_edits(store, vector, 2)
    assert await glossary_proposals(store) == []


async def test_existing_glossary_term_suppresses_the_proposal():
    store = SqliteStore({"path": ":memory:"})
    vector = LocalVectorIndex(MockLLM({"dim": 16}), {"path": ":memory:"})
    await _seed_edits(store, vector, 3)
    await store.log("glossary", {"term": "procurement cube",
                                 "maps_to": {"systems": ["SRM"]},
                                 "evidence_count": 1})
    assert await glossary_proposals(store) == []


@pytest.fixture
async def client():
    ctx = AppContext(memory_config())
    app = create_app(ctx)
    await ctx.seed_glossary()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as c:
        yield c, ctx


async def test_accept_endpoint_writes_term_once(client):
    c, ctx = client
    r = await c.post("/api/glossary", json={
        "term": "Procurement Cube",
        "maps_to": {"systems": ["SRM"], "team": "data-platform"}})
    assert r.status_code == 200 and r.json()["term"] == "procurement cube"
    rows = await ctx.store.query_ledger("glossary", term="procurement cube")
    assert rows and rows[0]["maps_to"]["systems"] == ["SRM"]
    # accepting twice is a conflict — live terms belong to the learning loop
    assert (await c.post("/api/glossary", json={
        "term": "procurement cube", "maps_to": {}})).status_code == 409


async def test_proposals_endpoint_shape(client):
    c, _ = client
    r = await c.get("/api/glossary/proposals")
    assert r.status_code == 200 and "proposals" in r.json()