"""The analyst's taxonomy learning loop — signals mined from production,
accepted by a human, never auto-applied.

The curated taxonomy in ``core/knowledge/processes.yaml`` is the analyst's
starting knowledge; this is how it grows. Every confirmation logs what the
analyst believed (process, confidence, the ask). This module mines those
rows for vocabulary the taxonomy is missing:

* asks that **placed** in a process keep using a term the process's signals
  don't contain → propose that term as a new signal for that process;
* asks that **failed to place** share recurring terms → surface them as
  unassigned candidates for a human to assign.

Acceptance (``POST /api/analyst/signals``) writes to the ``analyst_signals``
ledger, which ``classify_process`` merges with the static taxonomy at read
time — so the analyst genuinely improves from its own history, while a human
stays between the data and the knowledge, exactly like glossary proposals.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

from core.agents import analyst as analyst_agent

PROPOSAL_MIN_OCCURRENCES = 3
MAX_PROPOSALS_PER_PROCESS = 5

_TOKEN = re.compile(r"[a-z][a-z-]{3,}")

# Generic intake vocabulary that recurs in every ask regardless of domain.
_STOPWORDS = {
    "need", "needs", "needed", "want", "wants", "would", "like", "please",
    "report", "reports", "data", "with", "from", "into", "that", "this",
    "takes", "days", "hours", "weeks", "compile", "hand", "manual",
    "manually", "monthly", "weekly", "daily", "every", "team", "teams",
    "have", "using", "used", "them", "then", "when", "which", "there",
    "about", "because", "spreadsheets", "spreadsheet", "excel", "system",
    "systems", "info", "information", "details", "currently", "build",
}


def _terms(text: str) -> set[str]:
    return {t for t in _TOKEN.findall(text.lower()) if t not in _STOPWORDS}


async def _accepted(store) -> dict[str, list[str]]:
    """Human-accepted signals, grouped by process."""
    grouped: dict[str, list[str]] = defaultdict(list)
    for row in await store.query_ledger("analyst_signals"):
        if row.get("process") and row.get("signal"):
            grouped[row["process"]].append(row["signal"])
    return dict(grouped)


async def learned_signals(store) -> dict[str, list[str]]:
    """What classify_process merges with the static taxonomy."""
    return await _accepted(store)


async def signal_proposals(store,
                           min_occurrences: int = PROPOSAL_MIN_OCCURRENCES) -> list[dict]:
    """Mine the confirm-time analyst ledger for missing vocabulary."""
    know = analyst_agent.load_knowledge()["processes"]
    accepted = await _accepted(store)

    def known(process: str | None) -> set[str]:
        """Signal phrases AND their constituent words — a token inside
        'purchase order' is already covered vocabulary."""
        phrases: set[str] = set()
        if process and process in know:
            phrases |= {s.lower() for s in know[process].get("signals", [])}
        phrases |= {s.lower() for s in accepted.get(process or "", [])}
        tokens = set(phrases)
        for phrase in phrases:
            tokens |= set(phrase.split())
        return tokens

    per_process: dict[str | None, Counter] = defaultdict(Counter)
    samples: dict[tuple[str | None, str], list[str]] = defaultdict(list)
    for row in await store.query_ledger("outcome_ledger", stage="analyst"):
        detail = row.get("detail") or {}
        ask = detail.get("ask") or ""
        if not ask:
            continue
        process = None if row.get("verdict") in (None, "unplaced") else row["verdict"]
        for term in _terms(ask):
            if term in known(process):
                continue
            per_process[process][term] += 1
            bucket = samples[(process, term)]
            if ask not in bucket and len(bucket) < 3:
                bucket.append(ask)

    proposals = []
    for process, counts in per_process.items():
        ranked = [(t, n) for t, n in counts.most_common()
                  if n >= min_occurrences][:MAX_PROPOSALS_PER_PROCESS]
        for term, n in ranked:
            proposals.append({
                "process": process,               # None → needs a human to assign
                "signal": term,
                "occurrences": n,
                "sample_asks": samples[(process, term)],
            })
    proposals.sort(key=lambda p: (-p["occurrences"], p["signal"]))
    return proposals
