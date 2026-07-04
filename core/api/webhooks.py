"""Webhooks router — closes the routing feedback loop from ticket tools.

GitHub: when the assigned team relabels an intakepilot issue to a different
`intake/<queue>` label, that is ground truth the classifier was wrong. The
event becomes an outcome_ledger reroute row (feeding routing_accuracy) and
re-indexes the requirement under the corrected queue.

Set INTAKEPILOT_WEBHOOK_SECRET (and the same secret in the GitHub webhook
settings) to enforce X-Hub-Signature-256 verification; unset, the endpoint
accepts unsigned payloads (demo posture — front with your proxy).
"""
from __future__ import annotations

import json
import re

from fastapi import APIRouter, HTTPException, Request

from core.api.requirements import apply_reroute
from core.api.security import verify_github_signature

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

_REQ_ID = re.compile(r"IPR-\d{4}-\d{6}")


@router.post("/github")
async def github(request: Request):
    body = await request.body()
    verify_github_signature(request, body)
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(422, "invalid JSON payload")
    label = (payload.get("label") or {}).get("name", "")
    issue = payload.get("issue") or {}
    if (payload.get("action") != "labeled"
            or not label.startswith("intake/")):
        return {"processed": False, "reason": "not a queue relabel"}
    match = _REQ_ID.search(f"{issue.get('title', '')} {issue.get('body', '')}")
    if not match:
        return {"processed": False, "reason": "no requirement id in issue"}
    try:
        result = await apply_reroute(request.app.state.ctx, match.group(0),
                                     label.removeprefix("intake/"))
    except HTTPException as exc:
        # Benign for a webhook (unknown/foreign issue, non-routed status):
        # never 4xx back at GitHub or it may disable the hook.
        return {"processed": False, "reason": exc.detail}
    return {"processed": True, **result}
