"""I3: acceptance criteria — Given/When/Then generated at routing, attached
to the ticket; generation failure degrades gracefully (never blocks a route)."""
from __future__ import annotations

import json
import pathlib

import httpx
import pytest

from core.api.context import AppContext
from core.api.main import create_app
from core.config import load_slot_schema
from core.models import Budget, RequirementObject, Requester
from core.agents.acceptance import generate, section
from core.providers.llm.base import LLMResult

from tests.conftest import memory_config


class BrokenLLM:
    name = "broken"

    async def complete(self, messages, *, json_schema=None,
                       temperature=0.1, max_tokens=2048):
        return LLMResult(text="not json at all")

    async def embed(self, texts):
        return [[0.0] * 8 for _ in texts]


def _obj() -> RequirementObject:
    return RequirementObject(req_id="IPR-1", requester=Requester(),
                             ask_verbatim="automate the export",
                             question_budget=Budget(max=7, per_turn=3))


async def test_generation_failure_returns_empty_never_raises():
    assert await generate(BrokenLLM(), _obj(), load_slot_schema()) == []


def test_section_renders_gwt():
    md = section([{"given": "a monthly report", "when": "month-end runs",
                   "then": "the report exists within 1 hour"}])
    assert "## Acceptance criteria" in md
    assert "**Given**" in md and "**When**" in md and "**Then**" in md
    assert section([]) == ""


@pytest.fixture
async def client():
    ctx = AppContext(memory_config())
    app = create_app(ctx)
    await ctx.seed_glossary()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as c:
        yield c


async def test_routed_ticket_carries_acceptance_criteria(client):
    sid = (await client.post("/api/sessions", json={
        "requester": {"name": "A", "dept": "Finance Ops", "role": "Analyst"}}
    )).json()["session_id"]
    t = (await client.post(f"/api/sessions/{sid}/turns?stream=false",
                           json={"message": "our monthly vendor report takes "
                                            "3 days to compile by hand"})).json()
    answers = [{"question_id": q["id"], "slot_key": q["slot_key"],
                "value": (q.get("options") or ["this month"])[0]}
               for q in t["questions"]]
    await client.post(f"/api/sessions/{sid}/turns?stream=false",
                      json={"message": "success means ready in under 1 hour",
                            "answers": answers})
    req_id = t["draft"]["req_id"]
    confirm = (await client.post(f"/api/requirements/{req_id}/confirm",
                                 json={"edits": {}},
                                 headers={"X-Session-Id": sid})).json()
    assert confirm["draft"]["status"] == "routed"
    assert confirm["acceptance"], "expected generated scenarios"
    s = confirm["acceptance"][0]
    assert all(k in s and s[k] for k in ("given", "when", "then"))

    body = pathlib.Path(confirm["ticket"]["path"]).read_text()
    assert "## Acceptance criteria (generated)" in body and "**Given**" in body