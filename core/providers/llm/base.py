"""LLMProvider protocol (spec Section 5) + the single validate-and-retry wrapper.

Wrapper policy (applies to ALL providers, in one place):
  validate json against schema; on failure retry once with the validation
  error appended; on second failure raise ExtractionError.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from core.models import ExtractionError


@dataclass
class Msg:
    role: str  # system | user | assistant
    content: str


@dataclass
class LLMResult:
    text: str
    usage: dict = field(default_factory=dict)

    def json(self) -> Any:
        return json.loads(self.text)


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    async def complete(self, messages: list[Msg], *,
                       json_schema: dict | None = None,
                       temperature: float = 0.1,
                       max_tokens: int = 2048) -> LLMResult: ...

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


def _validate(data: Any, schema: dict) -> list[str]:
    """Minimal structural validation: type, required keys, property types.

    Deliberately small: enough to reject malformed model output without
    pulling in a full jsonschema dependency for the zero-dep default path.
    """
    errors: list[str] = []

    def check(value: Any, sch: dict, path: str) -> None:
        t = sch.get("type")
        if t == "object":
            if not isinstance(value, dict):
                errors.append(f"{path}: expected object, got {type(value).__name__}")
                return
            for req in sch.get("required", []):
                if req not in value:
                    errors.append(f"{path}: missing required key '{req}'")
            props = sch.get("properties", {})
            for k, v in value.items():
                if k in props:
                    check(v, props[k], f"{path}.{k}")
                elif sch.get("additionalProperties") is False:
                    errors.append(f"{path}: unexpected key '{k}'")
                elif isinstance(sch.get("additionalProperties"), dict):
                    check(v, sch["additionalProperties"], f"{path}.{k}")
        elif t == "array":
            if not isinstance(value, list):
                errors.append(f"{path}: expected array, got {type(value).__name__}")
                return
            item_sch = sch.get("items")
            if item_sch:
                for i, item in enumerate(value):
                    check(item, item_sch, f"{path}[{i}]")
        elif t == "string" and not isinstance(value, str) and value is not None:
            errors.append(f"{path}: expected string")
        elif t == "number" and not isinstance(value, (int, float)):
            errors.append(f"{path}: expected number")
        elif t == "boolean" and not isinstance(value, bool):
            errors.append(f"{path}: expected boolean")

    check(data, schema, "$")
    return errors


class EscalatingLLM:
    """Two-tier provider for the hybrid model strategy.

    `primary` (typically a local/open-weight model) answers every call.
    When a structured completion fails validation twice, `complete_validated`
    makes ONE final attempt on `escalation` — a stronger model, which can be
    a cloud frontier endpoint or a bigger internal one. As the learning
    ledger accumulates exemplars from daily usage, the primary succeeds more
    often and escalations (the expensive tokens) become rare.

    Embeddings ALWAYS use the primary so the vector index stays
    dimensionally consistent.
    """

    def __init__(self, primary: LLMProvider, escalation: LLMProvider):
        self.primary = primary
        self.escalation = escalation
        self.name = f"{primary.name}+{escalation.name}"
        # Observability: "escalations taper off as exemplars accumulate" is a
        # headline claim — these counters (and the on_escalation hook, wired
        # to the outcome ledger by AppContext) make it measurable.
        self.stats = {"validated_calls": 0, "escalations": 0, "rescues": 0}
        self.on_escalation = None  # optional async hook(failure_detail: str)

    async def complete(self, messages: list[Msg], *,
                       json_schema: dict | None = None,
                       temperature: float = 0.1,
                       max_tokens: int = 2048) -> LLMResult:
        return await self.primary.complete(
            messages, json_schema=json_schema,
            temperature=temperature, max_tokens=max_tokens)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return await self.primary.embed(texts)


def _parse(result: LLMResult, json_schema: dict) -> tuple[Any, str | None]:
    """Parse + validate one completion. Returns (data, None) or (None, failure)."""
    try:
        data = result.json()
    except (json.JSONDecodeError, ValueError) as exc:
        return None, f"invalid JSON: {exc}"
    errors = _validate(data, json_schema)
    if errors:
        return None, "; ".join(errors)
    return data, None


def _retry_messages(messages: list[Msg], result: LLMResult, failure: str) -> list[Msg]:
    return messages + [
        Msg(role="assistant", content=result.text[:2000]),
        Msg(role="user", content=(
            "Your previous output failed validation with: "
            f"{failure}. Output ONLY corrected JSON matching the schema.")),
    ]


async def complete_validated(provider: LLMProvider, messages: list[Msg],
                             json_schema: dict, **kw) -> Any:
    """The one wrapper. Never trust structured output; validate, retry once,
    escalate once to the stronger model if one is configured, then raise."""
    stats = getattr(provider, "stats", None)
    if stats is not None:
        stats["validated_calls"] += 1

    result = await provider.complete(messages, json_schema=json_schema, **kw)
    data, failure = _parse(result, json_schema)
    if failure is None:
        return data

    retry = _retry_messages(messages, result, failure)
    result = await provider.complete(retry, json_schema=json_schema, **kw)
    data, failure = _parse(result, json_schema)
    if failure is None:
        return data

    # Both primary attempts failed: one final attempt on the escalation
    # tier (EscalatingLLM only). Same messages, same validation, no loop.
    escalation = getattr(provider, "escalation", None)
    if escalation is not None:
        if stats is not None:
            stats["escalations"] += 1
        hook = getattr(provider, "on_escalation", None)
        if hook is not None:
            await hook(failure)
        result = await escalation.complete(
            _retry_messages(messages, result, failure),
            json_schema=json_schema, **kw)
        data, failure = _parse(result, json_schema)
        if failure is None:
            if stats is not None:
                stats["rescues"] += 1
            return data

    raise ExtractionError(failure)
