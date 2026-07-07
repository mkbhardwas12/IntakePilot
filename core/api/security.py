"""Admin/ops surface protection — one switch closes everything.

`INTAKEPILOT_ADMIN_TOKEN` unset -> the ops endpoints stay open (zero-friction
demo, the project's documented posture). Set -> every admin/ops surface
(metrics, system-KB, glossary, evals replay, reroute) requires
`Authorization: Bearer <token>`. Constant-time comparison throughout.

`INTAKEPILOT_WEBHOOK_SECRET` set -> /api/webhooks/github verifies GitHub's
`X-Hub-Signature-256` (HMAC-SHA256 over the raw body) — the same secret you
enter in the GitHub webhook settings.
"""
from __future__ import annotations

import hashlib
import hmac
import os

from fastapi import HTTPException, Request


def require_admin(request: Request) -> None:
    """FastAPI dependency for admin/ops routes."""
    token = os.environ.get("INTAKEPILOT_ADMIN_TOKEN", "")
    if not token:
        return  # demo posture: no token configured, surface stays open
    auth = request.headers.get("Authorization", "")
    if not (auth.startswith("Bearer ")
            and hmac.compare_digest(auth[len("Bearer "):], token)):
        raise HTTPException(401, "admin token required")


def verify_github_signature(request: Request, body: bytes) -> None:
    secret = os.environ.get("INTAKEPILOT_WEBHOOK_SECRET", "")
    if not secret:
        return  # demo posture: unsigned webhooks accepted
    signature = request.headers.get("X-Hub-Signature-256", "")
    expected = "sha256=" + hmac.new(secret.encode(), body,
                                    hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(401, "invalid webhook signature")


def verify_jira_token(request: Request) -> None:
    """Jira Cloud webhooks can't sign payloads; a shared token travels in the
    URL (`?token=`) or the `X-IntakePilot-Token` header instead. Set
    `INTAKEPILOT_JIRA_WEBHOOK_SECRET` to enforce it; unset keeps the demo
    posture (front with your reverse proxy)."""
    secret = os.environ.get("INTAKEPILOT_JIRA_WEBHOOK_SECRET", "")
    if not secret:
        return
    supplied = (request.query_params.get("token")
                or request.headers.get("X-IntakePilot-Token", ""))
    if not hmac.compare_digest(supplied, secret):
        raise HTTPException(401, "invalid webhook token")
