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
from core.api.security import verify_github_signature, verify_jira_token

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

_REQ_ID = re.compile(r"IPR-\d{4}-\d{6}")
_REQ_LABEL = re.compile(r"^ipr-\d{4}-\d{6}$")


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


@router.post("/jira")
async def jira(request: Request):
    """Jira Cloud `jira:issue_updated` events close two loops:

    * a queue relabel (`intake-<queue>`) is routing ground truth → reroute,
      exactly like the GitHub label handler;
    * a status move whose category is Done is the delivery terminal state →
      an outcome_ledger `delivered` row, the ground truth behind cycle-time
      and hours-displaced metrics.
    """
    verify_jira_token(request)
    try:
        payload = json.loads(await request.body())
    except json.JSONDecodeError:
        raise HTTPException(422, "invalid JSON payload")

    issue = payload.get("issue") or {}
    fields = issue.get("fields") or {}
    labels = [l for l in (fields.get("labels") or []) if isinstance(l, str)]
    req_id = next((l.upper() for l in labels if _REQ_LABEL.match(l)), None)
    if not req_id:
        return {"processed": False, "reason": "no requirement label on issue"}

    ctx = request.app.state.ctx
    changes = ((payload.get("changelog") or {}).get("items")) or []

    for item in changes:
        if item.get("field") == "labels":
            before = set((item.get("fromString") or "").split())
            after = set((item.get("toString") or "").split())
            added = [l for l in after - before if l.startswith("intake-")]
            if added:
                try:
                    result = await apply_reroute(
                        ctx, req_id, added[0].removeprefix("intake-"))
                except HTTPException as exc:
                    return {"processed": False, "reason": exc.detail}
                return {"processed": True, "event": "reroute", **result}

    for item in changes:
        if item.get("field") == "status":
            done = ((fields.get("status") or {}).get("statusCategory")
                    or {}).get("key") == "done"
            if done:
                try:
                    await ctx.store.latest(req_id)
                except KeyError:
                    return {"processed": False, "reason": "unknown requirement"}
                await ctx.store.log("outcome_ledger", {
                    "req_id": req_id, "stage": "delivered", "verdict": "closed",
                    "detail": {"issue": issue.get("key"),
                               "status": item.get("toString")}})
                return {"processed": True, "event": "delivered",
                        "req_id": req_id}

    return {"processed": False, "reason": "no queue relabel or done transition"}
