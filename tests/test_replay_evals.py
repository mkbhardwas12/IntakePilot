"""Corrections-as-evals: the edit ledger replays as a self-writing eval set."""
from __future__ import annotations

import json

import httpx
import pytest

from core.api.context import AppContext
from core.api.main import create_app
from core.config import load_slot_schema
from core.models import Budget, RequirementObject, Requester
from core.learning import exemplars as learning
from core.learning.replay import matches, replay_corrections
from core.providers.llm.base import LLMResult
from core.providers.llm.mock import MockLLM
from core.providers.store.sqlite import SqliteStore
from core.providers.vector.local import LocalVectorIndex

from tests.conftest import memory_config


class CannedLLM:
    """Returns a fixed extraction — lets the test control replay outcomes."""
    name = "canned"

    def __init__(self, slots: dict):
        self._slots = slots

    async def complete(self, messages, *, json_schema=None,
                       temperature=0.1, max_tokens=2048):
        return LLMResult(text=json.dumps({"slots": self._slots}))

    async def embed(self, texts):
        return [[0.5] * 16 for _ in texts]


async def _seed(store, vector) -> RequirementObject:
    obj = RequirementObject(
        req_id="IPR-2026-000001", requester=Requester(dept="Finance Ops"),
        ask_verbatim="our monthly vendor report takes 3 days to compile by hand",
        question_budget=Budget(max=7, per_turn=3))
    await store.put_version(obj)
    await learning.capture_edit(store, vector, obj, "affected_systems",
                                ["ERP-VendorMaster"],
                                ["ERP-VendorMaster", "BW4"],
                                provenance="retrieved")
    return obj


async def test_replay_scores_match_when_model_produces_the_correction():
    store = SqliteStore({"path": ":memory:"})
    llm = MockLLM({"dim": 16})
    vector = LocalVectorIndex(llm, {"path": ":memory:"})
    await _seed(store, vector)

    good = CannedLLM({"affected_systems":
                      {"value": ["BW4", "ERP-VendorMaster"], "confidence": 0.9}})
    report = await replay_corrections(store, vector, good, load_slot_schema())
    assert report["total"] == 1 and report["accuracy"] == 1.0
    assert report["by_slot"]["affected_systems"]["accuracy"] == 1.0


async def test_replay_scores_miss_when_model_still_gets_it_wrong():
    store = SqliteStore({"path": ":memory:"})
    llm = MockLLM({"dim": 16})
    vector = LocalVectorIndex(llm, {"path": ":memory:"})
    await _seed(store, vector)

    bad = CannedLLM({"affected_systems":
                     {"value": ["ERP-VendorMaster"], "confidence": 0.9}})
    report = await replay_corrections(store, vector, bad, load_slot_schema())
    assert report["total"] == 1 and report["accuracy"] == 0.0


def test_match_normalization():
    assert matches(["b", "A "], ["a", "B"])
    assert matches(" This Week", "this week")
    assert not matches(["a"], ["a", "b"])


@pytest.fixture
async def client():
    ctx = AppContext(memory_config())
    app = create_app(ctx)
    await ctx.seed_glossary()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as c:
        yield c


async def test_replay_endpoint_shape(client):
    r = await client.get("/api/evals/replay?limit=10")
    assert r.status_code == 200
    body = r.json()
    assert {"model", "total", "matched", "accuracy", "by_slot"} <= set(body)