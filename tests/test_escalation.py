"""Hybrid model strategy: primary answers everything; a configured stronger
model gets ONE attempt when the primary fails validation twice. Embeddings
always stay on the primary (vector-index dimensional consistency)."""
from __future__ import annotations

import json

import pytest

from core.config import Config
from core.models import ExtractionError
from core.providers import make_llm
from core.providers.llm.base import (EscalatingLLM, LLMResult, Msg,
                                     complete_validated)

SCHEMA = {"type": "object", "required": ["slots"],
          "properties": {"slots": {"type": "object"}}}
MSGS = [Msg(role="user", content="extract this")]


class BrokenLLM:
    """Always returns unparseable output."""
    name = "broken"

    def __init__(self):
        self.calls = 0
        self.embed_calls = 0

    async def complete(self, messages, *, json_schema=None,
                       temperature=0.1, max_tokens=2048):
        self.calls += 1
        return LLMResult(text="definitely not json")

    async def embed(self, texts):
        self.embed_calls += 1
        return [[0.0] * 8 for _ in texts]


class StrongLLM:
    """Always returns valid output; records the messages it saw."""
    name = "strong"

    def __init__(self):
        self.calls = 0
        self.embed_calls = 0
        self.seen: list[list[Msg]] = []

    async def complete(self, messages, *, json_schema=None,
                       temperature=0.1, max_tokens=2048):
        self.calls += 1
        self.seen.append(messages)
        return LLMResult(text=json.dumps({"slots": {"ok": True}}))

    async def embed(self, texts):
        self.embed_calls += 1
        return [[1.0] * 8 for _ in texts]


async def test_escalation_rescues_after_two_primary_failures():
    primary, strong = BrokenLLM(), StrongLLM()
    tiered = EscalatingLLM(primary, strong)
    seen: list[str] = []

    async def hook(detail: str) -> None:
        seen.append(detail)

    tiered.on_escalation = hook
    data = await complete_validated(tiered, MSGS, SCHEMA)
    assert data == {"slots": {"ok": True}}
    assert primary.calls == 2, "primary gets exactly its usual attempt + retry"
    assert strong.calls == 1, "escalation gets exactly one attempt"
    # The escalation prompt carries the failure context, not a bare re-ask.
    assert any("failed validation" in m.content for m in strong.seen[0])
    # Observability: counters + hook fire on every escalation.
    assert tiered.stats == {"validated_calls": 1, "escalations": 1, "rescues": 1}
    assert seen and "JSON" in seen[0]


async def test_stats_track_primary_successes_without_escalation():
    tiered = EscalatingLLM(StrongLLM(), StrongLLM())
    await complete_validated(tiered, MSGS, SCHEMA)
    assert tiered.stats == {"validated_calls": 1, "escalations": 0, "rescues": 0}


async def test_no_escalation_configured_keeps_existing_contract():
    primary = BrokenLLM()
    with pytest.raises(ExtractionError):
        await complete_validated(primary, MSGS, SCHEMA)
    assert primary.calls == 2  # unchanged: one attempt + one retry, then raise


async def test_escalation_failure_still_raises():
    with pytest.raises(ExtractionError):
        await complete_validated(EscalatingLLM(BrokenLLM(), BrokenLLM()),
                                 MSGS, SCHEMA)


async def test_primary_success_never_touches_escalation():
    primary, strong = StrongLLM(), StrongLLM()
    await complete_validated(EscalatingLLM(primary, strong), MSGS, SCHEMA)
    assert primary.calls == 1 and strong.calls == 0


async def test_embeddings_always_use_primary():
    primary, strong = StrongLLM(), StrongLLM()
    tiered = EscalatingLLM(primary, strong)
    await tiered.embed(["a", "b"])
    assert primary.embed_calls == 1 and strong.embed_calls == 0


def test_make_llm_builds_tiered_provider_from_config():
    cfg = Config(llm_provider="mock", llm_escalation_provider="mock",
                 llm={"mock": {"dim": 8}}, llm_escalation={"dim": 8})
    llm = make_llm(cfg)
    assert isinstance(llm, EscalatingLLM)
    assert llm.name == "mock+mock"
    assert make_llm(Config(llm_provider="mock")).name == "mock"