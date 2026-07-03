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


async def complete_validated(provider: LLMProvider, messages: list[Msg],
                             json_schema: dict, **kw) -> Any:
    """The one wrapper. Never trust structured output; validate, retry once, raise."""
    result = await provider.complete(messages, json_schema=json_schema, **kw)
    for attempt in range(2):
        try:
            data = result.json()
            errors = _validate(data, json_schema)
            if not errors:
                return data
            failure = "; ".join(errors)
        except (json.JSONDecodeError, ValueError) as exc:
            failure = f"invalid JSON: {exc}"
        if attempt == 1:
            raise ExtractionError(failure)
        retry_messages = messages + [
            Msg(role="assistant", content=result.text[:2000]),
            Msg(role="user", content=(
                "Your previous output failed validation with: "
                f"{failure}. Output ONLY corrected JSON matching the schema.")),
        ]
        result = await provider.complete(retry_messages, json_schema=json_schema, **kw)
    raise ExtractionError("unreachable")
