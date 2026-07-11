"""Shared httpx helpers — short backoff retries on 429 / 5xx."""
from __future__ import annotations

import asyncio

import httpx

_RETRY_STATUSES = {429, 500, 502, 503, 504}


async def request_with_retries(client: httpx.AsyncClient, method: str, url: str,
                               *, retries: int = 2, backoff: float = 0.25,
                               **kwargs) -> httpx.Response:
    """POST/GET with up to `retries` retries on transient upstream errors."""
    attempt = 0
    while True:
        resp = await client.request(method, url, **kwargs)
        if resp.status_code not in _RETRY_STATUSES or attempt >= retries:
            return resp
        attempt += 1
        await asyncio.sleep(backoff * attempt)
