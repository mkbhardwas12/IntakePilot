"""Local cosine-similarity index — zero-dependency default.

Embeddings come from the configured LLMProvider.embed (the mock provider
produces deterministic hash embeddings, so this works with no model installed).
Persisted as a JSON file so the demo survives restarts.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import threading
from pathlib import Path

from core.providers.vector.base import Hit


class LocalVectorIndex:
    name = "local"

    def __init__(self, embedder, config: dict | None = None):
        self._embedder = embedder
        path = (config or {}).get("path", "data/vector_index.json")
        self._path: Path | None = None if path == ":memory:" else Path(path)
        self._lock = threading.Lock()
        self._items: dict[str, dict] = {}
        if self._path and self._path.exists():
            try:
                self._items = json.loads(self._path.read_text())
            except (json.JSONDecodeError, ValueError):
                # A crash mid-write must not brick startup: the index is a
                # cache over the ledgers and can be rebuilt by usage.
                self._items = {}

    def _persist(self) -> None:
        """Atomic: write to a temp file, then rename over the real one, so a
        crash can never leave a half-written (unparseable) index behind."""
        if self._path:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self._items))
            os.replace(tmp, self._path)

    async def upsert(self, id: str, text: str, meta: dict) -> None:
        vec = (await self._embedder.embed([text]))[0]

        def _():
            with self._lock:
                self._items[id] = {"text": text, "meta": meta, "vec": vec}
                self._persist()
        await asyncio.to_thread(_)

    async def search(self, text: str, k: int = 5,
                     filter: dict | None = None) -> list[Hit]:
        if not self._items:
            return []
        query = (await self._embedder.embed([text]))[0]

        def _():
            qnorm = math.sqrt(sum(v * v for v in query)) or 1.0
            hits: list[Hit] = []
            for id_, item in self._items.items():
                if filter and any(item["meta"].get(fk) != fv
                                  for fk, fv in filter.items()):
                    continue
                vec = item["vec"]
                dot = sum(a * b for a, b in zip(query, vec))
                vnorm = math.sqrt(sum(v * v for v in vec)) or 1.0
                hits.append(Hit(id=id_, score=dot / (qnorm * vnorm),
                                text=item["text"], meta=item["meta"]))
            hits.sort(key=lambda h: h.score, reverse=True)
            return hits[:k]
        return await asyncio.to_thread(_)
