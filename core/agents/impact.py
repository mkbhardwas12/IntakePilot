"""Portfolio impact — collision detection and the requirement↔entity graph.

Gate 4 catches sameness (a near-duplicate ask). Collisions are different:
two DIFFERENT requirements touching the SAME backend entities — say, two
asks that both change `ZZ_PRIORITY_CODE`, owned by two different teams.
That interference is invisible to intake tools, and it is where enterprise
delivery actually bleeds. The data to detect it already exists here: every
requirement carries auto-discovered backend_context and affected_systems.

Collisions do not block routing (they are not duplicates — both pieces of
work may proceed); they are surfaced on the ticket, in the confirm
response, and in the outcome ledger so the colliding teams meet BEFORE the
merge conflict, not after.
"""
from __future__ import annotations

from core.models import RequirementObject, Status

# Requirements in these states represent open work that new asks can collide
# with. DONE/REJECTED are history; drafts are not yet commitments.
OPEN_STATUSES = {Status.CONFIRMED, Status.GATED, Status.ROUTED,
                 Status.BUILDING, Status.IN_REVIEW}


def entity_keys(obj: RequirementObject) -> set[str]:
    """Stable keys for everything this requirement touches: discovered
    backend entities (system:entity) plus named affected systems."""
    keys: set[str] = set()
    bc = obj.slots.get("backend_context")
    if bc and isinstance(bc.value, dict):
        for ent in bc.value.get("entities") or []:
            if ent.get("system") and ent.get("entity"):
                keys.add(f"{ent['system']}:{ent['entity']}")
    systems = obj.slots.get("affected_systems")
    if systems and isinstance(systems.value, list):
        keys |= {f"system:{str(s).strip().lower()}"
                 for s in systems.value if str(s).strip()}
    return keys


async def open_requirements(store, exclude_req_id: str | None = None
                            ) -> list[RequirementObject]:
    seen: set[str] = set()
    out: list[RequirementObject] = []
    for session in await store.list_sessions():
        req_id = session.get("req_id")
        if not req_id or req_id in seen or req_id == exclude_req_id:
            continue
        seen.add(req_id)
        try:
            obj = await store.latest(req_id)
        except KeyError:
            continue
        if obj.status in OPEN_STATUSES:
            out.append(obj)
    return out


async def collisions(store, obj: RequirementObject) -> list[dict]:
    """Open requirements sharing backend entities/systems with this one,
    strongest overlap first."""
    mine = entity_keys(obj)
    if not mine:
        return []
    hits = []
    for other in await open_requirements(store, exclude_req_id=obj.req_id):
        shared = sorted(mine & entity_keys(other))
        if shared:
            hits.append({
                "req_id": other.req_id,
                "status": other.status.value,
                "queue": other.routing.queue if other.routing else None,
                "shared": shared,
            })
    hits.sort(key=lambda h: len(h["shared"]), reverse=True)
    return hits


def _pretty_key(key: str) -> str:
    return key.removeprefix("system:")


def collision_section(hits: list[dict]) -> str:
    """Markdown block appended to the routed ticket."""
    if not hits:
        return ""
    lines = ["", "## Impact — open work on the same entities (auto)", "",
             "_Detected at confirmation from discovered backend context. "
             "These teams should talk before building._", ""]
    for h in hits:
        queue = f", queue {h['queue']}" if h.get("queue") else ""
        shared = ", ".join(f"`{_pretty_key(k)}`" for k in h["shared"])
        lines.append(f"- **{h['req_id']}** ({h['status']}{queue}) — shares: {shared}")
    return "\n".join(lines)


async def graph(store) -> dict:
    """The requirement↔entity↔queue graph over open work — the portfolio
    view an admin/architect sees."""
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    for obj in await open_requirements(store):
        rid = obj.req_id
        nodes[rid] = {"id": rid, "kind": "requirement",
                      "status": obj.status.value,
                      "queue": obj.routing.queue if obj.routing else None,
                      "ask": obj.ask_verbatim[:120]}
        for key in sorted(entity_keys(obj)):
            if key not in nodes:
                nodes[key] = {"id": key, "kind": "entity",
                              "label": _pretty_key(key)}
            edges.append({"from": rid, "to": key, "kind": "touches"})
    entity_degree = {}
    for e in edges:
        entity_degree[e["to"]] = entity_degree.get(e["to"], 0) + 1
    hotspots = sorted(({"entity": _pretty_key(k), "open_requirements": n}
                       for k, n in entity_degree.items() if n > 1),
                      key=lambda h: h["open_requirements"], reverse=True)
    return {"nodes": list(nodes.values()), "edges": edges, "hotspots": hotspots}
