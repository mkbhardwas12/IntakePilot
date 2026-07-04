"""Routing DNA classifier — keyword scoring blended with embedding similarity
to previously ROUTED requirements, with confidence and a human-readable
explanation. Queues come from intakepilot.yaml (cold start: seeded keywords);
every routed ticket is indexed with its queue, so routing improves with use.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from core.models import RequirementObject, RoutingAlternative, RoutingDecision

# A routed precedent's cosine similarity must clear this to count as signal
# (hash/mock embeddings produce low-grade noise below it).
PRECEDENT_MIN_SIM = 0.35
# Weight of the precedent signal relative to one keyword match.
PRECEDENT_WEIGHT = 1.5


@dataclass
class _QueueScore:
    name: str
    matched: list[str] = field(default_factory=list)
    sim_sum: float = 0.0
    sim_hits: int = 0
    top_sim: float = 0.0

    @property
    def score(self) -> float:
        return len(self.matched) + PRECEDENT_WEIGHT * self.sim_sum


async def classify(obj: RequirementObject, queues: list[dict],
                   vector=None) -> RoutingDecision:
    outcome = obj.slots.get("business_outcome")
    systems = obj.slots.get("affected_systems")
    text = " ".join([
        obj.ask_verbatim,
        str(outcome.value) if outcome and outcome.value else "",
        " ".join(map(str, systems.value)) if systems and isinstance(systems.value, list) else "",
    ]).lower()

    by_name = {q["name"]: _QueueScore(name=q["name"]) for q in queues}
    for queue in queues:
        qs = by_name[queue["name"]]
        qs.matched = [kw for kw in queue.get("keywords", [])
                      if re.search(rf"\b{re.escape(kw.lower())}", text)]

    # Precedent signal: where did similar requirements get routed before?
    if vector is not None:
        hits = await vector.search(text, k=8, filter={"table": "requirements"})
        for hit in hits:
            queue_name = hit.meta.get("queue")
            if (not queue_name or queue_name not in by_name
                    or hit.meta.get("req_id") == obj.req_id
                    or hit.score < PRECEDENT_MIN_SIM):
                continue
            qs = by_name[queue_name]
            qs.sim_sum += hit.score
            qs.sim_hits += 1
            qs.top_sim = max(qs.top_sim, hit.score)

    scored = sorted(by_name.values(), key=lambda q: q.score, reverse=True)
    total = sum(q.score for q in scored) or 1.0
    top = scored[0] if scored else _QueueScore(name="triage")

    if top.score == 0:
        return RoutingDecision(
            queue="triage", confidence=0.0,
            explanation="No routing signal matched any queue — sent to human triage.",
            alternatives=[RoutingAlternative(queue=q.name, score=0.0) for q in scored[:3]])

    parts = []
    if top.matched:
        parts.append(f"Matched {len(top.matched)} signal(s) for “{top.name}”: "
                     + ", ".join(f"“{m}”" for m in top.matched))
    if top.sim_hits:
        parts.append(f"{top.sim_hits} similar past ticket(s) also landed in "
                     f"“{top.name}” (top similarity {top.top_sim:.2f})")
    explanation = ". ".join(parts)
    explanation += (f". Second-best scored {scored[1].score:.1f}."
                    if len(scored) > 1 else ".")
    confidence = round(top.score / total, 2)
    return RoutingDecision(
        queue=top.name, confidence=min(0.99, max(confidence, 0.34)),
        explanation=explanation,
        alternatives=[RoutingAlternative(queue=q.name, score=round(q.score / total, 2))
                      for q in scored[1:4]])
