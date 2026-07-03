"""Provider registry — providers registered by name, selected in intakepilot.yaml.

No business logic may import a provider SDK; everything outside core/providers/
talks only to the protocols in llm/base.py, store/base.py, vector/base.py.
"""
from __future__ import annotations

from core.config import Config


def _make_llm_single(name: str, conf: dict):
    if name == "mock":
        from core.providers.llm.mock import MockLLM
        return MockLLM(conf)
    if name == "ollama":
        from core.providers.llm.ollama import OllamaLLM
        return OllamaLLM(conf)
    if name == "openai_compat":
        from core.providers.llm.openai_compat import OpenAICompatLLM
        return OpenAICompatLLM(conf)
    raise ValueError(f"unknown llm provider: {name}")


def make_llm(cfg: Config):
    primary = _make_llm_single(cfg.llm_provider, cfg.llm.get(cfg.llm_provider, {}))
    esc_name = cfg.llm_escalation_provider
    if esc_name:
        from core.providers.llm.base import EscalatingLLM
        # `llm_escalation:` section overrides (e.g. a bigger model on the same
        # provider); falls back to the provider's own `llm:` entry.
        esc_conf = cfg.llm_escalation or cfg.llm.get(esc_name, {})
        return EscalatingLLM(primary, _make_llm_single(esc_name, esc_conf))
    return primary


def make_store(cfg: Config):
    name = cfg.store_provider
    conf = cfg.store.get(name, {})
    if name in ("sqlite", "memory"):
        from core.providers.store.sqlite import SqliteStore
        return SqliteStore(conf)
    if name == "postgres":
        from core.providers.store.postgres import PostgresStore
        return PostgresStore(conf)
    raise ValueError(f"unknown store provider: {name}")


def make_connectors(cfg: Config) -> list:
    name = cfg.connector_provider
    conf = cfg.connectors.get(name, {})
    if name == "fixture":
        from core.providers.connector.fixture import load_fixture_connectors
        return load_fixture_connectors(conf.get("dir", "core/schemas/systems"))
    if name == "none":
        return []
    raise ValueError(f"unknown connector provider: {name}")


def make_vector(cfg: Config, embedder):
    name = cfg.vector_provider
    conf = cfg.vector.get(name, {})
    if name == "local":
        from core.providers.vector.local import LocalVectorIndex
        return LocalVectorIndex(embedder, conf)
    if name == "pgvector":
        from core.providers.vector.pgvector import PgVectorIndex
        return PgVectorIndex(embedder, conf)
    raise ValueError(f"unknown vector provider: {name}")
