"""Wires the MANAS emitter into the application flow — the missing half of
"contract-ready is not deployed".

The pattern is the transactional outbox from the integration recommendation:
the domain write (confirm, adjudication) and the outbox row are committed in
the same request, and an external relay ships ``state=pending`` rows to MANAS
later. MANAS availability therefore never controls a user transaction, and a
requirement that routed while the outbox was misconfigured still leaves an
auditable ``rejected`` row instead of silently emitting nothing.

Default-off (``MANAS_OUTBOX_ENABLED=true`` plus the ``MANAS_*`` binding and
``MANAS_TENANT_PEPPER``). Every function here returns quietly — a broken
outbox must never cost an intake.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from datetime import datetime, timezone

from core.export.manas_outbox.emitter import (
    OutboxBinding, OutboxContractError, emit_outcome_adjudicated,
    emit_requirement_versioned, outbox_enabled)

logger = logging.getLogger("intakepilot.manas_outbox")

_CHANGE_ID = re.compile(r"[^A-Za-z0-9._-]+")

# The pack requires roles from a closed set; anything else is mapped by the
# caller before it reaches here.
ADJUDICATOR_ROLES = ("business_owner", "product_owner")
VERDICTS = ("achieved", "partially_achieved", "not_achieved")


def wire_ts(dt: datetime | None = None) -> str:
    """MANAS wire timestamps are millisecond-precision Zulu, exactly."""
    dt = dt or datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def change_id_from(ticket_ref: str | None, req_id: str) -> str:
    """One organization-governed change handle, sanitised to the pack's
    pattern. The routed ticket ref is that handle; the req_id is the
    fallback when no external ticket exists."""
    raw = (ticket_ref or req_id).strip()
    cleaned = _CHANGE_ID.sub("-", raw).strip("-.") or req_id
    return cleaned[:96]


def _pepper() -> bytes:
    return os.environ.get("MANAS_TENANT_PEPPER", "").encode("utf-8")


def _row(req_id: str, result) -> dict:
    if result.ok:
        return {"req_id": req_id, **result.as_item(), "reason": None}
    return {"req_id": req_id, "outbox_id": None,
            "event_type": result.event_type, "content_hash": None,
            "envelope_json": None, "state": "rejected",
            "reason": result.reason}


def build_requirement_versioned_row(obj, *, acceptance_text: str) -> dict | None:
    """The version that went to build, as an outbox row ready to commit in
    the SAME transaction as the version itself (put_version_with_outbox).
    None when the outbox is off. change_ref is the IPR id — the org-governed
    change handle that exists before build handoff and is reused verbatim by
    the later adjudication, never reconstructed from a downstream ticket."""
    if not outbox_enabled():
        return None
    try:
        binding = OutboxBinding.from_env()
        result = emit_requirement_versioned(
            binding,
            requirement_id=obj.req_id,
            requirement_version=obj.version,
            change_id=change_id_from(None, obj.req_id),
            request_type=obj.request_type,
            intent_text=obj.ask_verbatim,
            acceptance_criteria_text=acceptance_text or "none stated",
            pepper=_pepper(),
            registered_at=wire_ts(),
        )
    except OutboxContractError as exc:
        result = _config_rejection(str(exc))
    except Exception as exc:  # noqa: BLE001 — the outbox never costs a confirm
        logger.exception("outbox emit failed for %s", obj.req_id)
        result = _config_rejection(f"unexpected: {type(exc).__name__}")
    return _row(obj.req_id, result)


def build_outcome_adjudicated_row(obj, *, verdict: str, role: str,
                                  receipt_text: str, evidence_text: str,
                                  deployment_ref: str | None,
                                  deployment_source_binding: str | None) -> dict | None:
    """A human adjudication of the delivered result, as an outbox row. The
    deployment attestation (ref + binding) is originated by the delivery
    system and presented by the caller — IntakePilot never fabricates it;
    without one the adjudication stays local and the outbox records why."""
    if not outbox_enabled():
        return None
    if not deployment_ref or not deployment_source_binding:
        return _row(obj.req_id, _config_rejection(
            "no deployment attestation presented — adjudication kept local"))
    try:
        binding = OutboxBinding.from_env()
        result = emit_outcome_adjudicated(
            binding,
            outcome_id=f"{obj.req_id}-adj-{obj.version}",
            deployment_ref=deployment_ref,
            deployment_source_binding=deployment_source_binding,
            requirement_id=obj.req_id,
            requirement_version=obj.version,
            requirement_source_binding=binding.source_binding,
            change_id=change_id_from(None, obj.req_id),
            change_source_binding=binding.source_binding,
            verdict=verdict,
            adjudicated_by_role=role,
            outcome_evidence_hash="sha256:" + hashlib.sha256(
                (evidence_text or receipt_text).encode("utf-8")).hexdigest(),
            receipt_text=receipt_text,
            pepper=_pepper(),
            adjudicated_at=wire_ts(),
        )
    except OutboxContractError as exc:
        result = _config_rejection(str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("outbox emit failed for %s", obj.req_id)
        result = _config_rejection(f"unexpected: {type(exc).__name__}")
    return _row(obj.req_id, result)


class _config_rejection:
    """A Rejected-shaped record for failures upstream of the emitter
    (binding/pepper misconfiguration, unexpected errors)."""

    ok = False
    event_type = "outbox.config"

    def __init__(self, reason: str):
        self.reason = reason
