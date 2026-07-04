from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from core.config import Config, SlotSchema, SlotSpec, load_config, load_slot_schema
from core.models import Budget, RequirementObject, Requester
from core.providers.llm.mock import MockLLM
from core.providers.store.sqlite import SqliteStore
from core.providers.vector.local import LocalVectorIndex
from core.agents.orchestrator import Orchestrator


def memory_config() -> Config:
    cfg = load_config()
    cfg.llm_provider = "mock"
    cfg.store_provider = "sqlite"
    cfg.vector_provider = "local"
    cfg.store = {"sqlite": {"path": ":memory:"}}
    cfg.vector = {"local": {"path": ":memory:"}}
    cfg.demo_repo = str(Path(tempfile.mkdtemp(prefix="intakepilot-demo-"))
                        / "demo-repo")
    return cfg


@pytest.fixture
def cfg() -> Config:
    return memory_config()


@pytest.fixture
def schema() -> SlotSchema:
    return load_slot_schema()


@pytest.fixture
def store() -> SqliteStore:
    return SqliteStore({"path": ":memory:"})


@pytest.fixture
def llm() -> MockLLM:
    return MockLLM()


@pytest.fixture
def vector(llm) -> LocalVectorIndex:
    return LocalVectorIndex(llm, {"path": ":memory:"})


@pytest.fixture
def orchestrator(llm, store, vector, schema, cfg) -> Orchestrator:
    return Orchestrator(llm, store, vector, schema, cfg)


def make_obj(req_id: str = "IPR-2026-000001", ask: str = "test ask",
             budget: Budget | None = None) -> RequirementObject:
    return RequirementObject(
        req_id=req_id, requester=Requester(name="Test", dept="Finance Ops"),
        ask_verbatim=ask, question_budget=budget or Budget())


def many_askable_schema(n: int = 10) -> SlotSchema:
    slots = {f"slot_{i}": SlotSpec(key=f"slot_{i}", required=True, askable=True,
                                   label=f"Slot {i}", ask_hint=f"what about slot {i}?")
             for i in range(n)}
    return SlotSchema(slots=slots)


async def seed(store, obj: RequirementObject) -> dict:
    await store.put_version(obj)
    session = {"session_id": "s-test", "req_id": obj.req_id, "turns": [],
               "pending_questions": [], "budget_spent": 0,
               "requester": obj.requester.model_dump()}
    await store.put_session(session)
    return session
