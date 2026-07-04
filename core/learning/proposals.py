"""Structural learning: repeated identical corrections become glossary
PROPOSALS — surfaced to an admin, never auto-applied (spec Section 11: only
human-originated signals mutate the glossary; an admin click is that signal).

Pattern: when the same slot is corrected to the same value N+ times, the
extraction stack is missing a piece of org vocabulary. The proposal carries
the evidence (occurrences, buckets, sample asks) and a suggested term mined
from the asks; the admin can rename it before accepting.
"""
from __future__ import annotations

import json
import re
from collections import Counter

PROPOSAL_MIN_OCCURRENCES = 3
_STOPWORDS = {
    "the", "a", "an", "and", "or", "our", "your", "their", "this", "that",
    "with", "from", "into", "for", "have", "has", "need", "needs", "want",
    "takes", "take", "days", "day", "hours", "hour", "compile", "hand",
    "monthly", "weekly", "daily", "every", "each", "please", "would", "like",
}


def _canon(value) -> str:
    if isinstance(value, list):
        return json.dumps(sorted(str(v).strip().lower() for v in value))
    return json.dumps(str(value).strip().lower())


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z][a-z0-9_-]{3,}", text.lower())
            if t not in _STOPWORDS]


def _suggest_term(asks: list[str]) -> str | None:
    """The most frequent significant token that appears in (almost) every
    sample ask — the vocabulary the corrections keep orbiting."""
    if not asks:
        return None
    counts: Counter[str] = Counter()
    for ask in asks:
        counts.update(set(_tokens(ask)))
    threshold = max(1, round(0.8 * len(asks)))
    # Ties broken toward longer tokens: they tend to be the domain-specific
    # vocabulary ("procurement" over "region").
    candidates = [(n, len(t), t) for t, n in counts.items() if n >= threshold]
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][2]


async def glossary_proposals(store, min_occurrences: int = PROPOSAL_MIN_OCCURRENCES) -> list[dict]:
    edits = await store.query_ledger("edit_diffs")
    existing_terms = {r["term"].lower()
                      for r in await store.query_ledger("glossary")}

    groups: dict[tuple[str, str], dict] = {}
    for row in edits:
        key = (row.get("slot_key") or "?", _canon(row.get("corrected")))
        g = groups.setdefault(key, {"count": 0, "buckets": set(), "req_ids": []})
        g["count"] += 1
        g["buckets"].add(row.get("context_bucket") or "?")
        g["req_ids"].append(row.get("req_id"))

    proposals = []
    for (slot_key, corrected_canon), g in groups.items():
        if g["count"] < min_occurrences:
            continue
        asks = []
        for req_id in g["req_ids"][:5]:
            try:
                obj = await store.latest(req_id)
            except KeyError:
                continue
            if obj.ask_verbatim:
                asks.append(obj.ask_verbatim)
        # Already covered: an existing glossary term appears in every ask.
        if asks and any(all(term in ask.lower() for ask in asks)
                        for term in existing_terms):
            continue
        proposals.append({
            "slot_key": slot_key,
            "corrected": json.loads(corrected_canon),
            "occurrences": g["count"],
            "buckets": sorted(g["buckets"]),
            "suggested_term": _suggest_term(asks),
            "sample_asks": asks[:3],
        })
    proposals.sort(key=lambda p: p["occurrences"], reverse=True)
    return proposals
