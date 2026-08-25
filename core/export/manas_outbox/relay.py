"""The relay — the last mile that actually ships the outbox to MANAS.

Reads ``state=pending`` rows (latest state per outbox_id wins), POSTs each
envelope to the authenticated MANAS ingest endpoint, and appends the result
as a new state row — ``shipped`` with the MANAS receipt, ``attempt_failed``
on transient trouble, ``dead_letter`` when MANAS rejects the contract (4xx)
or the attempt budget is spent. Rows are append-only throughout, so every
publish attempt, receipt and rejection stays on the record for replay/audit.

Retry is the cron cadence: one attempt per row per pass, attempts counted
across passes. Run it as ``python -m core.export.manas_outbox.relay`` (cron)
or trigger a pass via ``POST /api/export/outbox/ship``.

Config: ``MANAS_RELAY_URL`` (ingest endpoint) and ``MANAS_RELAY_TOKEN``
(bearer credential, tenant-scoped on the MANAS side).
"""
from __future__ import annotations

import os

import httpx

MAX_ATTEMPTS = 8
_TIMEOUT = 10.0
_RECEIPT_MAX = 2000


def relay_config(env=None) -> tuple[str, str]:
    values = env if env is not None else os.environ
    return (str(values.get("MANAS_RELAY_URL") or "").strip(),
            str(values.get("MANAS_RELAY_TOKEN") or "").strip())


async def pending_rows(store) -> list[dict]:
    """Rows whose latest state is still pending, annotated with the attempt
    count so far. Ordered by first-seen (FIFO)."""
    by_id: dict[str, list[dict]] = {}
    order: list[str] = []
    for row in await store.query_ledger("manas_outbox"):
        oid = row.get("outbox_id")
        if not oid:
            continue  # rejected-at-build rows have no envelope to ship
        if oid not in by_id:
            by_id[oid] = []
            order.append(oid)
        by_id[oid].append(row)

    out = []
    for oid in order:
        rows = by_id[oid]
        states = [r["state"] for r in rows]
        if "shipped" in states or "dead_letter" in states:
            continue
        original = next((r for r in rows if r.get("envelope_json")), None)
        if original is None:
            continue
        out.append({**original,
                    "attempts": sum(1 for s in states if s == "attempt_failed")})
    return out


async def _mark(store, row: dict, state: str, reason: str | None) -> None:
    await store.log("manas_outbox", {
        "outbox_id": row["outbox_id"], "req_id": row.get("req_id"),
        "event_type": row.get("event_type"),
        "content_hash": row.get("content_hash"),
        "envelope_json": None, "state": state,
        "reason": (reason or "")[:_RECEIPT_MAX] or None})


async def ship_pending(store, *, url: str | None = None,
                       token: str | None = None,
                       transport: httpx.AsyncBaseTransport | None = None,
                       max_attempts: int = MAX_ATTEMPTS) -> dict:
    """One relay pass. Never raises; returns counts for the caller/cron log."""
    env_url, env_token = relay_config()
    url = url or env_url
    token = token or env_token
    if not url or not token:
        return {"error": "MANAS_RELAY_URL / MANAS_RELAY_TOKEN not configured",
                "shipped": 0, "failed": 0, "dead_lettered": 0, "pending": 0}

    rows = await pending_rows(store)
    shipped = failed = dead = 0
    async with httpx.AsyncClient(transport=transport, timeout=_TIMEOUT) as client:
        for row in rows:
            try:
                resp = await client.post(
                    url, content=row["envelope_json"],
                    headers={"Authorization": f"Bearer {token}",
                             "Content-Type": "application/cloudevents+json"})
            except httpx.HTTPError as exc:
                outcome = ("dead_letter"
                           if row["attempts"] + 1 >= max_attempts else "attempt_failed")
                await _mark(store, row, outcome, f"transport: {exc}")
                dead += outcome == "dead_letter"
                failed += outcome == "attempt_failed"
                continue
            if 200 <= resp.status_code < 300:
                # The MANAS receipt (event id, accepted schema version,
                # ingest time) is the proof of admission — keep it verbatim.
                await _mark(store, row, "shipped", resp.text)
                shipped += 1
            elif 400 <= resp.status_code < 500:
                # Contract rejection: retrying the same bytes cannot succeed.
                await _mark(store, row, "dead_letter",
                            f"{resp.status_code}: {resp.text}")
                dead += 1
            else:
                outcome = ("dead_letter"
                           if row["attempts"] + 1 >= max_attempts else "attempt_failed")
                await _mark(store, row, outcome,
                            f"{resp.status_code}: {resp.text}")
                dead += outcome == "dead_letter"
                failed += outcome == "attempt_failed"
    return {"shipped": shipped, "failed": failed, "dead_lettered": dead,
            "pending": len(rows) - shipped - dead}


def main() -> None:  # pragma: no cover - thin cron wrapper
    import asyncio
    import json

    from core.api.context import AppContext

    async def run():
        ctx = AppContext()
        print(json.dumps(await ship_pending(ctx.store)))

    asyncio.run(run())


if __name__ == "__main__":  # pragma: no cover
    main()
