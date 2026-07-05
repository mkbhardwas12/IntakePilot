"""Bring-your-own-AI, proven: enabling any backend is environment variables
alone — provider, endpoint, key, model — and /health shows what took effect,
so nobody has to wonder whether their AI is actually the one answering."""
from __future__ import annotations

import httpx
import pytest

from core.api.context import AppContext
from core.api.main import create_app
from core.config import load_config
from core.providers import make_llm
from core.providers.llm.base import EscalatingLLM
from core.providers.llm.ollama import OllamaLLM

from tests.conftest import memory_config


def test_env_enables_any_openai_compatible_backend(monkeypatch):
    monkeypatch.setenv("INTAKEPILOT_LLM", "openai_compat")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://your-gateway:8001/v1")
    monkeypatch.setenv("OPENAI_MODEL", "qwen3-32b")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    llm = make_llm(load_config())
    assert llm.name == "openai_compat"
    assert llm.base_url == "http://your-gateway:8001/v1"
    assert llm.model == "qwen3-32b"
    assert llm.api_key == "test-key"


def test_env_points_ollama_at_any_host(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://gpu-box:11434")
    assert OllamaLLM({}).base_url == "http://gpu-box:11434"


def test_hybrid_is_two_env_vars(monkeypatch):
    monkeypatch.setenv("INTAKEPILOT_LLM", "ollama")
    monkeypatch.setenv("INTAKEPILOT_LLM_ESCALATION", "openai_compat")
    llm = make_llm(load_config())
    assert isinstance(llm, EscalatingLLM)
    assert llm.name == "ollama+openai_compat"
    assert llm.primary.name == "ollama"
    assert llm.escalation.name == "openai_compat"


@pytest.mark.parametrize("provider", ["mock", "ollama", "openai_compat"])
def test_every_provider_enables_without_code_changes(monkeypatch, provider):
    monkeypatch.setenv("INTAKEPILOT_LLM", provider)
    assert make_llm(load_config()).name == provider


async def test_health_shows_the_enabled_model(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "my-team-model")
    cfg = memory_config()
    cfg.llm_provider = "openai_compat"
    ctx = AppContext(cfg)
    app = create_app(ctx)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as c:
        h = (await c.get("/health")).json()
    assert h["provider"] == "openai_compat"
    assert h["model"] == "my-team-model"


async def test_health_shows_primary_model_when_hybrid(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "strong-model")
    cfg = memory_config()
    cfg.llm_provider = "ollama"
    cfg.llm_escalation_provider = "openai_compat"
    ctx = AppContext(cfg)
    app = create_app(ctx)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as c:
        h = (await c.get("/health")).json()
    assert h["provider"] == "ollama+openai_compat"
    assert h["model"]  # the primary's model, visible at a glance