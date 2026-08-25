"""The Analyst — reads the requirement the way a seasoned BA would.

Slot extraction answers "what did they say"; this answers "what do they mean,
and what would an experienced analyst check before believing the draft is
complete". Three parts, split by who is allowed to decide what:

* **Process placement** is deterministic: the ask is matched against curated
  signals in ``core/knowledge/processes.yaml`` (word-boundary phrase hits, the
  winner by votes). No model decides which business process this is — the
  placement drives everything downstream and must be reproducible and
  auditable.
* **Unstated needs, risks and KPIs** come from that same curated knowledge.
  Each unstated need names the slot keys that settle it, so its status flips
  from ``open`` to ``covered`` live as the draft fills — the analyst's mental
  checklist made visible.
* **The interpretation** — a plain-language reading of the underlying need —
  is the one part a model composes, through the same validate-and-retry
  wrapper as every other LLM call, and it degrades to a deterministic
  restatement rather than blocking a turn. It may rephrase; it may not add
  facts (the prompt forbids invention, and nothing it produces feeds routing,
  gates, or slots).
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Mapping

import yaml

from core.config import SlotSchema
from core.models import (AnalystRead, AnalystRisk, ExtractionError,
                         ProcessMatch, RequirementObject, UnstatedNeed)
from core.providers.llm.base import Msg, complete_validated

KNOWLEDGE_PATH = Path(__file__).resolve().parent.parent / "knowledge" / "processes.yaml"

INTERPRETATION_SCHEMA = {
    "type": "object",
    "required": ["interpretation"],
    "properties": {"interpretation": {"type": "string"}},
}

# Confidence smoothing: hits/(hits+k). One signal ≈ 0.33, three ≈ 0.6, many → 0.9.
_CONFIDENCE_K = 2
_CONFIDENCE_CAP = 0.9


@lru_cache(maxsize=1)
def load_knowledge() -> dict:
    with open(KNOWLEDGE_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def classify_process(text: str,
                     learned: Mapping[str, list[str]] | None = None) -> ProcessMatch | None:
    """Deterministic placement: most signal votes wins; ties break by taxonomy
    order (stable). Returns None when nothing in the ask votes at all.

    ``learned`` merges human-accepted signals from the analyst_signals ledger
    (mined from production asks, accepted via /api/analyst/signals) with the
    static taxonomy — the self-improvement loop, still with a human between
    the data and the knowledge."""
    low = text.lower()
    best: tuple[int, str, dict, list[str]] | None = None
    for key, entry in load_knowledge()["processes"].items():
        signals = list(entry.get("signals", [])) + list((learned or {}).get(key, []))
        hits = [s for s in signals
                if re.search(rf"\b{re.escape(s.lower())}\b", low)]
        if hits and (best is None or len(hits) > best[0]):
            best = (len(hits), key, entry, hits)
    if best is None:
        return None
    n, key, entry, hits = best
    return ProcessMatch(
        key=key, label=entry["label"],
        confidence=round(min(_CONFIDENCE_CAP, n / (n + _CONFIDENCE_K)), 2),
        evidence=hits)


def _filled(obj: RequirementObject, key: str) -> bool:
    slot = obj.slots.get(key)
    return slot is not None and slot.value not in (None, "", [])


def _needs(entry: dict, obj: RequirementObject,
           schema: SlotSchema) -> list[UnstatedNeed]:
    """The checklist, statused against the live draft. A need whose covering
    slot is not even in this request type's schema is dropped rather than
    left permanently open — the fork said it does not apply here."""
    out: list[UnstatedNeed] = []
    for raw in entry.get("unstated_needs", []):
        keys = raw.get("covered_by") or []
        in_schema = [k for k in keys if k in schema.slots]
        if keys and not in_schema:
            continue
        covering = next((k for k in in_schema if _filled(obj, k)), None)
        out.append(UnstatedNeed(
            need=raw["need"], why=raw["why"],
            status="covered" if covering else "open",
            covered_by=covering))
    return out


def _fallback_interpretation(obj: RequirementObject,
                             match: ProcessMatch | None) -> str:
    """Deterministic restatement when the model is unavailable or invalid."""
    outcome = obj.slots.get("business_outcome")
    core = (str(outcome.value) if outcome and outcome.value
            else obj.ask_verbatim.strip())
    placed = f" This sits in the {match.label} process." if match else ""
    return f"Reading of the ask: {core}.{placed}"


def _build_messages(obj: RequirementObject, match: ProcessMatch | None,
                    needs: list[UnstatedNeed]) -> list[Msg]:
    filled = {k: s.value for k, s in obj.slots.items()
              if s.value not in (None, "", []) and k != "backend_context"}
    open_needs = "; ".join(n.need for n in needs if n.status == "open") or "(none)"
    system = (
        "TASK: analyst\n"
        "You are a senior business analyst. Restate what the requester is "
        "actually trying to achieve — the underlying need behind the words — "
        "in 2–3 plain sentences a non-technical sponsor would sign off on. "
        "Use only the facts given; never invent systems, numbers, or names. "
        "Do not list the open questions — they are shown separately. "
        "Output JSON: {\"interpretation\": str}.")
    user = (f"Ask: {obj.ask_verbatim}\n"
            f"Process: {match.label if match else 'unplaced'}\n"
            f"Known slots: {filled}\n"
            f"Still open for the analyst: {open_needs}")
    return [Msg(role="system", content=system), Msg(role="user", content=user)]


async def read(llm, obj: RequirementObject, schema: SlotSchema,
               store=None) -> AnalystRead:
    """Produce the analyst's read for the current draft. Never raises: any
    model failure degrades to the deterministic interpretation. With a store,
    placement also uses the human-accepted learned signals."""
    know = load_knowledge()
    corpus = obj.ask_verbatim
    outcome = obj.slots.get("business_outcome")
    if outcome and outcome.value:
        corpus += " " + str(outcome.value)
    learned = None
    if store is not None:
        from core.learning import analyst_signals
        learned = await analyst_signals.learned_signals(store)
    match = classify_process(corpus, learned)
    entry = know["processes"][match.key] if match else know["general"]

    needs = _needs(entry, obj, schema)
    risks = [AnalystRisk(**r) for r in entry.get("risks", [])]
    kpis = list(entry.get("kpis", []))

    try:
        data = await complete_validated(
            llm, _build_messages(obj, match, needs), INTERPRETATION_SCHEMA)
        interpretation = str(data.get("interpretation", "")).strip()
        source = "llm"
    except ExtractionError:
        interpretation = ""
        source = "deterministic"
    if not interpretation:
        interpretation = _fallback_interpretation(obj, match)
        source = "deterministic"

    return AnalystRead(process=match, interpretation=interpretation,
                       interpretation_source=source, unstated_needs=needs,
                       risks=risks, kpis=kpis)
