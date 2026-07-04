"""Webhooks router — closes the routing feedback loop from ticket tools.

GitHub: when the assigned team relabels an intakepilot issue to a different
`intake/<queue>` label, that is ground truth the classifier was wrong. The
event becomes an outcome_ledger reroute row (feeding routing_accuracy) and
re-indexes the requirement under the corrected queue.

NOTE: webhook signature verification (X-Hub-Signature-256) is not implemented
yet — terminate this behind your reverse proxy / IP allowlist for now.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Request

from core.api.requirements import apply_reroute

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

_REQ_ID = re.compile(r"IPR-\d{4}-\d{6}")


@router.post("/github")
async def github(request: Request):
    payload = await request.json()
    label = (payload.get("label") or {}).get("name", "")
    issue = payload.get("issue") or {}
    if (payload.get("action") != "labeled"
            or not label.startswith("intake/")):
        return {"processed": False, "reason": "not a queue relabel"}
    match = _REQ_ID.search(f"{issue.get('title', '')} {issue.get('body', '')}")
    if not match:
        return {"processed": False, "reason": "no requirement id in issue"}
    result = await apply_reroute(request.app.state.ctx, match.group(0),
                                 label.removeprefix("intake/"))
    return {"processed": True, **result}
