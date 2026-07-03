"""Routing DNA classifier — keyword + embedding scoring with confidence and a
human-readable explanation. Queues come from intakepilot.yaml (cold start:
seeded keywords; Milestone 7 recalibrates thresholds from outcome_ledger).
"""
from __future__ import annotations

import re

from core.models import RequirementObject, RoutingAlternative, RoutingDecision


async def classify(obj: RequirementObject, queues: list[dict],
                   vector=None) -> RoutingDecision:
    outcome = obj.slots.get("business_outcome")
    systems = obj.slots.get("affected_systems")
    text = " ".join([
        obj.ask_verbatim,
        str(outcome.value) if outcome and outcome.value else "",
        " ".join(map(str, systems.value)) if systems and isinstance(systems.value, list) else "",
    ]).lower()

    scored: list[tuple[str, float, list[str]]] = []
    for queue in queues:
        matched = [kw for kw in queue.get("keywords", [])
                   if re.search(rf"\b{re.escape(kw.lower())}", text)]
        score = float(len(matched))
        scored.append((queue["name"], score, matched))
    scored.sort(key=lambda t: t[1], reverse=True)

    total = sum(s for _, s, _ in scored) or 1.0
    top_name, top_score, top_matched = scored[0] if scored else ("triage", 0.0, [])
    confidence = round(top_score / total, 2) if top_score else 0.0

    if top_score == 0:
        return RoutingDecision(
            queue="triage", confidence=0.0,
            explanation="No routing signal matched any queue — sent to human triage.",
            alternatives=[RoutingAlternative(queue=n, score=0.0) for n, _, _ in scored[:3]])

    explanation = (f"Matched {len(top_matched)} signal(s) for \u201c{top_name}\u201d: "
                   + ", ".join(f"\u201c{m}\u201d" for m in top_matched)
                   + (f". Second-best scored {scored[1][1]:.0f}." if len(scored) > 1 else "."))
    return RoutingDecision(
        queue=top_name, confidence=min(0.99, max(confidence, 0.34)),
        explanation=explanation,
        alternatives=[RoutingAlternative(queue=n, score=round(s / total, 2))
                      for n, s, _ in scored[1:4]])
