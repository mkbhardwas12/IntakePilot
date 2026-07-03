"""VectorIndex protocol (spec Section 5)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class Hit:
    id: str
    score: float
    text: str
    meta: dict = field(default_factory=dict)


@runtime_checkable
class VectorIndex(Protocol):
    async def upsert(self, id: str, text: str, meta: dict) -> None: ...
    async def search(self, text: str, k: int = 5,
                     filter: dict | None = None) -> list[Hit]: ...
