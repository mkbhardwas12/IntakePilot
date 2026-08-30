"""The improvement loop, as one idempotent pass — run it on a schedule and
the system keeps getting better and keeps feeding MANAS without anyone
remembering to.

Each pass:

1. **Ships the MANAS outbox** — pending requirement.versioned / outcome.
   adjudicated envelopes go to the ingest endpoint (no-op with a clear
   reason when `MANAS_RELAY_URL`/`MANAS_RELAY_TOKEN` are not set), and the
   outbox health (pending / dead-letter counts) is reported so a stuck feed
   is visible, not silent.
2. **Harvests the research surfaces** — analyst signal proposals (taxonomy
   vocabulary mined from confirmed asks) and glossary proposals (mined from
   repeated human corrections). Both are *proposals*: this pass surfaces
   them for a human to accept via the API; it never auto-applies.
3. **Replays corrections as evals** — every confirmation edit becomes a
   regression test against the current extraction stack, so drift shows up
   here before it shows up with a requester.

Output: one JSON report on stdout (cron-friendly; pipe it wherever you keep
ops evidence).

    python -m scripts.improve            # one pass
    # cron: */30 * * * *  cd /path && .venv/bin/python -m scripts.improve
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone


async def run_pass() -> dict:
    from core.api.context import AppContext
    from core.export.manas_outbox import relay
    from core.learning import analyst_signals
    from core.learning import proposals as glossary_engine
    from core.learning.replay import replay_corrections

    ctx = AppContext()
    report: dict = {"at": datetime.now(timezone.utc).isoformat()}

    # 1. Feed MANAS.
    report["manas"] = await relay.ship_pending(ctx.store)
    rows = await ctx.store.query_ledger("manas_outbox")
    states: dict[str, str] = {}
    for row in rows:
        if row.get("outbox_id"):
            states[row["outbox_id"]] = row["state"]
    report["manas"]["outbox_health"] = {
        state: sum(1 for s in states.values() if s == state)
        for state in ("pending", "shipped", "attempt_failed", "dead_letter")}

    # 2. Harvest the research surfaces (proposals only — humans accept).
    analyst_props = await analyst_signals.signal_proposals(ctx.store)
    glossary_props = await glossary_engine.glossary_proposals(ctx.store)
    report["research"] = {
        "analyst_signal_proposals": analyst_props,
        "glossary_proposals": glossary_props,
        "action": ("review via GET /api/analyst/proposals and "
                   "GET /api/glossary/proposals; accept what is right"
                   if analyst_props or glossary_props else "nothing new"),
    }

    # 3. Corrections replayed as evals.
    try:
        report["evals"] = await replay_corrections(
            ctx.store, ctx.vector, ctx.llm, ctx.schema_for)
    except Exception as exc:  # noqa: BLE001 — one leg failing must not hide the rest
        report["evals"] = {"error": f"{type(exc).__name__}: {exc}"}

    return report


def main() -> None:  # pragma: no cover - thin cron wrapper
    print(json.dumps(asyncio.run(run_pass()), indent=2, default=str))


if __name__ == "__main__":  # pragma: no cover
    main()
