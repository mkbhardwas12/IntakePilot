"""Ollama provider — POST /api/chat with format=json when a schema is given.

Note (see docs/SPEC-REVIEW.md): Ollama's `format` enforces valid JSON (or a
schema on recent versions), but the validate-and-retry wrapper in base.py is
the actual guarantee — never trust structured output.
"""
from __future__ import annotations

import os

import httpx

from core.providers.llm.base import LLMResult, Msg


class OllamaLLM:
    name = "ollama"

    def __init__(self, config: dict | None = None):
        config = config or {}
        self.base_url = os.environ.get(
            "OLLAMA_BASE_URL", config.get("base_url", "http://localhost:11434")).rstrip("/")
        self.model = config.get("model", "llama3.1")
        self.embed_model = config.get("embed_model", "nomic-embed-text")
        self.timeout = float(config.get("timeout_seconds", 120))

    async def complete(self, messages: list[Msg], *, json_schema: dict | None = None,
                       temperature: float = 0.1, max_tokens: int = 2048) -> LLMResult:
        payload: dict = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if json_schema is not None:
            payload["format"] = json_schema  # older Ollama: use "json"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(f"{self.base_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
        return LLMResult(
            text=data["message"]["content"],
            usage={"eval_count": data.get("eval_count"),
                   "prompt_eval_count": data.get("prompt_eval_count")})

    async def embed(self, texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(f"{self.base_url}/api/embed",
                                     json={"model": self.embed_model, "input": texts})
            resp.raise_for_status()
            return resp.json()["embeddings"]
