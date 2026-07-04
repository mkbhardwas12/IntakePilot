"""intakepilot.yaml loader + slot schema loader (spec 4.2), with env overrides."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class SlotSpec:
    key: str
    required: bool = False
    askable: bool = True
    label: str = ""
    ask_hint: str | None = None
    default: Any = None
    default_reason: str | None = None
    options: list[str] | None = None


@dataclass
class SlotSchema:
    slots: dict[str, SlotSpec]

    def required_keys(self) -> list[str]:
        return [k for k, s in self.slots.items() if s.required]

    def askable_keys(self) -> list[str]:
        return [k for k, s in self.slots.items() if s.askable]

    def unaskable_keys(self) -> list[str]:
        return [k for k, s in self.slots.items() if not s.askable]


def load_slot_schema(path: Path | None = None) -> SlotSchema:
    path = path or ROOT / "core" / "schemas" / "default.yaml"
    raw = yaml.safe_load(path.read_text())
    slots: dict[str, SlotSpec] = {}
    for key, cfg in raw["slots"].items():
        cfg = cfg or {}
        slots[key] = SlotSpec(
            key=key,
            required=bool(cfg.get("required", False)),
            askable=bool(cfg.get("askable", True)),
            label=cfg.get("label", key.replace("_", " ").capitalize()),
            ask_hint=cfg.get("ask_hint"),
            default=cfg.get("default"),
            default_reason=cfg.get("default_reason"),
            options=cfg.get("options"),
        )
    return SlotSchema(slots=slots)


@dataclass
class Config:
    llm_provider: str = "mock"
    llm_escalation_provider: str = ""   # optional stronger model for hard turns
    store_provider: str = "sqlite"
    vector_provider: str = "local"
    connector_provider: str = "fixture"
    target_provider: str = "local"
    llm: dict = field(default_factory=dict)
    llm_escalation: dict = field(default_factory=dict)
    targets: dict = field(default_factory=dict)
    store: dict = field(default_factory=dict)
    vector: dict = field(default_factory=dict)
    connectors: dict = field(default_factory=dict)
    budget_max: int = 7
    budget_per_turn: int = 3
    confirm_threshold: int = 70
    routing_queues: list[dict] = field(default_factory=list)
    demo_repo: str = "examples/demo-repo"
    analyst_baseline_hours: float = 2.0
    raw: dict = field(default_factory=dict)


def load_config(path: Path | None = None) -> Config:
    path = path or ROOT / "intakepilot.yaml"
    raw: dict = {}
    if path.exists():
        raw = yaml.safe_load(path.read_text()) or {}

    provider = raw.get("provider", {})
    cfg = Config(
        llm_provider=os.environ.get("INTAKEPILOT_LLM", provider.get("llm", "mock")),
        # `or ""`: compose files pass empty strings for unset env vars.
        llm_escalation_provider=(os.environ.get("INTAKEPILOT_LLM_ESCALATION")
                                 or provider.get("llm_escalation", "") or ""),
        store_provider=os.environ.get("INTAKEPILOT_STORE", provider.get("store", "sqlite")),
        vector_provider=os.environ.get("INTAKEPILOT_VECTOR", provider.get("vector", "local")),
        connector_provider=os.environ.get("INTAKEPILOT_CONNECTOR",
                                          provider.get("connector", "fixture")),
        target_provider=(os.environ.get("INTAKEPILOT_TARGET")
                         or provider.get("target", "local") or "local"),
        llm=raw.get("llm", {}),
        llm_escalation=raw.get("llm_escalation", {}) or {},
        targets=raw.get("targets", {}) or {},
        store=raw.get("store", {}),
        vector=raw.get("vector", {}),
        connectors=raw.get("connectors", {}),
        budget_max=int(raw.get("budget", {}).get("max", 7)),
        budget_per_turn=int(raw.get("budget", {}).get("per_turn", 3)),
        confirm_threshold=int(raw.get("readiness", {}).get("confirm_threshold", 70)),
        routing_queues=raw.get("routing", {}).get("queues", []),
        demo_repo=raw.get("demo_repo", "examples/demo-repo"),
        analyst_baseline_hours=float(raw.get("metrics", {}).get("analyst_baseline_hours", 2.0)),
        raw=raw,
    )
    # DATABASE_URL implies the postgres store, per README contract.
    if os.environ.get("DATABASE_URL") and "INTAKEPILOT_STORE" not in os.environ:
        cfg.store_provider = "postgres"
    return cfg
