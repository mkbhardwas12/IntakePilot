"""OpenAI-compatible provider — /v1/chat/completions with response_format json_schema."""
from __future__ import annotations

import os

import httpx

from core.providers.http_retry import request_with_retries
from core.providers.llm.base import LLMResult, Msg


class OpenAICompatLLM:
    name = "openai_compat"

    def __init__(self, config: dict | None = None):
        config = config or {}
        # Env overrides let deployments point at any OpenAI-compatible server
        # (vLLM, LiteLLM, llama.cpp, TGI, an internal gateway) without editing
        # intakepilot.yaml — the on-prem/BYO-LLM path.
        # `or` (not a default arg): compose files pass empty strings for unset
        # env vars, which must fall through to the YAML config.
        self.base_url = (os.environ.get("OPENAI_BASE_URL")
                         or config.get("base_url", "https://api.openai.com/v1")).rstrip("/")
        self.model = os.environ.get("OPENAI_MODEL") or config.get("model", "gpt-4o-mini")
        self.embed_model = config.get("embed_model", "text-embedding-3-small")
        self.api_key = os.environ.get(config.get("api_key_env", "OPENAI_API_KEY"), "")
        self.timeout = float(config.get("timeout_seconds", 60))

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def complete(self, messages: list[Msg], *, json_schema: dict | None = None,
                       temperature: float = 0.1, max_tokens: int = 2048) -> LLMResult:
        payload: dict = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "output", "schema": json_schema, "strict": False},
            }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await request_with_retries(
                client, "POST", f"{self.base_url}/chat/completions",
                json=payload, headers=self._headers())
            resp.raise_for_status()
            data = resp.json()
        return LLMResult(text=data["choices"][0]["message"]["content"],
                         usage=data.get("usage", {}))

    async def embed(self, texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await request_with_retries(
                client, "POST", f"{self.base_url}/embeddings",
                json={"model": self.embed_model, "input": texts},
                headers=self._headers())
            resp.raise_for_status()
            return [d["embedding"] for d in resp.json()["data"]]
