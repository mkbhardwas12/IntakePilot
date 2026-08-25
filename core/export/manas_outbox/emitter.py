"""MANAS Demand-lobe outbox for IntakePilot — the business intent, committed, never disclosed.

IntakePilot owns two facts in the MANAS change thread and no others: the exact requirement version that
went to build, and the human adjudication of whether the delivered result met the need. Everything else
about a requirement — the original ask, the clarification dialogue, reviewer identities, narrative
rationale — stays here. What crosses is an HMAC commitment to the intent, so a later reader can prove
which text was meant without ever being shown it.

**This module is the reconciled reference for the producer work.** An earlier exploratory branch emits
``io.manas.demand.asked`` / ``.corrected`` / ``.observed``; none of those is a MANAS contract, and all
three would be rejected at admission. The contracts IntakePilot actually owns are
``requirement.versioned.v2`` and ``outcome.adjudicated.v1``, exactly as this repository's own
integration recommendation states.

Envelopes are **built from the vendored pack's wire specification**, not from remembered conventions.
That is deliberate: every drift incident so far came from a producer reconstructing envelope rules by
hand. Source, agent, activity, subject, timestamp field, entity refs, partition key and provenance all
come from `demand-lobe-pack.json`, which is exported from the same projector the consumer validates
with.

Default-off. Never raises into a caller's transaction: returns ``Emitted`` or ``Rejected``.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

__all__ = [
    "Emitted",
    "OutboxBinding",
    "OutboxContractError",
    "Rejected",
    "commitment",
    "emit_outcome_adjudicated",
    "emit_requirement_versioned",
    "load_pack",
    "outbox_enabled",
]

PACK_PATH = Path(__file__).with_name("demand-lobe-pack.json")
REQUIREMENT_VERSIONED = "io.manas.demand.requirement.versioned.v2"
OUTCOME_ADJUDICATED = "io.manas.demand.outcome.adjudicated.v1"

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_REF_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_HMAC = re.compile(r"^hmac-sha256:[0-9a-f]{64}$")
_WIRE_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
_MAX_CLOCK_SKEW = timedelta(minutes=5)
_MAX_SAFE_INT = 2 ** 53 - 1

_PII_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("phone", re.compile(r"(?<![\w.-])\+?\d[\d ().-]{8,}\d(?![\w.-])")),
    ("iban", re.compile(r"(?<![A-Z0-9])[A-Z]{2}\d{2}[A-Z0-9]{10,30}(?![A-Z0-9])")),
)
_NON_PII_EXACT: tuple[re.Pattern[str], ...] = (
    _HASH, _HMAC, _WIRE_TS,
    re.compile(r"^[a-z][a-z0-9_-]{0,31}:[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,223}$"),
)


class OutboxContractError(ValueError):
    """A fact cannot safely cross the boundary. Message is bounded and never echoes a value."""


@dataclass(frozen=True)
class Rejected:
    reason: str
    event_type: str | None = None

    @property
    def ok(self) -> bool:
        return False


@dataclass(frozen=True)
class Emitted:
    outbox_id: str
    event_type: str
    envelope: Mapping[str, Any]
    content_hash: str

    @property
    def ok(self) -> bool:
        return True

    def as_item(self) -> dict[str, Any]:
        return {
            "outbox_id": self.outbox_id,
            "event_type": self.event_type,
            "content_hash": self.content_hash,
            "envelope_json": json.dumps(self.envelope, sort_keys=True, separators=(",", ":")),
            "state": "pending",
        }


def outbox_enabled(env: Mapping[str, str] | None = None) -> bool:
    values = env if env is not None else os.environ
    return str(values.get("MANAS_OUTBOX_ENABLED", "")).strip().lower() == "true"


# ----------------------------------------------------------------- canonicalization (RFC 8785)

def _jcs_check(value: Any) -> Any:
    """Mirrors ``manas.canon._check``. Integral floats become integers (1.0 -> 1)."""
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, int):
        if abs(value) > _MAX_SAFE_INT:
            raise OutboxContractError("integer exceeds 2**53 and must be stringified first")
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise OutboxContractError("NaN/Infinity are not representable in I-JSON")
        if value.is_integer() and abs(value) <= _MAX_SAFE_INT:
            return int(value)
        return value
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key in value:
            if not isinstance(key, str):
                raise OutboxContractError("object keys must be strings")
            out[key] = _jcs_check(value[key])
        return out
    if isinstance(value, (list, tuple)):
        return [_jcs_check(v) for v in value]
    raise OutboxContractError(f"type {type(value).__name__} is not JSON-serialisable")


def _utf16_units(text: str) -> list[int]:
    raw = text.encode("utf-16-be")
    return [(raw[i] << 8) | raw[i + 1] for i in range(0, len(raw), 2)]


def _jcs_dumps(value: Any) -> str:
    if isinstance(value, dict):
        items = sorted(value.items(), key=lambda kv: _utf16_units(kv[0]))
        return "{" + ",".join(
            json.dumps(k, ensure_ascii=False) + ":" + _jcs_dumps(v) for k, v in items
        ) + "}"
    if isinstance(value, list):
        return "[" + ",".join(_jcs_dumps(v) for v in value) + "]"
    if isinstance(value, float):
        r = repr(value)
        if "e" in r or "E" in r:
            mant, exp = r.lower().split("e")
            exp_i = int(exp)
            r = f"{mant}e{'+' if exp_i >= 0 else '-'}{abs(exp_i)}"
        return r
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def canonical_bytes(value: Any) -> bytes:
    """Must match ``manas.canon.canonical_bytes`` byte for byte."""
    return _jcs_dumps(_jcs_check(value)).encode("utf-8")


# ----------------------------------------------------------------- commitments

def commitment(text: str, pepper: bytes) -> str:
    """Commit to business text without disclosing it.

    The original ask, the acceptance criteria and the adjudication receipt are IntakePilot's to keep.
    MANAS receives only this commitment, which proves *which* text was meant to anyone holding the
    tenant pepper and reveals nothing to anyone who does not.
    """
    if not isinstance(text, str) or not text:
        raise OutboxContractError("commitment requires non-empty text")
    if not pepper or len(pepper) < 16:
        raise OutboxContractError("commitment requires a tenant pepper of at least 16 bytes")
    return "hmac-sha256:" + hmac.new(pepper, text.encode("utf-8"), hashlib.sha256).hexdigest()


def _pii_kind(value: str) -> str | None:
    if any(p.fullmatch(value) for p in _NON_PII_EXACT):
        return None
    for kind, pattern in _PII_PATTERNS:
        if pattern.search(value):
            return kind
    return None


def _assert_non_pii(value: Any, path: str = "data") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            _assert_non_pii(nested, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _assert_non_pii(nested, path)
    elif isinstance(value, str):
        kind = _pii_kind(value)
        if kind:
            raise OutboxContractError(f"{kind}-like data rejected at {path}")


# ----------------------------------------------------------------- the pack

_PACK_CACHE: dict[str, Any] = {}


def load_pack(path: Path | str = PACK_PATH) -> Mapping[str, Any]:
    key = str(path)
    if key in _PACK_CACHE:
        return _PACK_CACHE[key]
    pack = json.loads(Path(path).read_text(encoding="utf-8"))
    for section, digest_key in (("schemas", "digest"), ("wire", "wire_digest")):
        payload = pack.get(section)
        if not payload:
            if section == "schemas":
                raise OutboxContractError("vendored contract pack has no schemas")
            continue
        material = json.dumps({k: payload[k] for k in sorted(payload)},
                              sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        if "sha256:" + hashlib.sha256(material.encode("utf-8")).hexdigest() != pack.get(digest_key):
            raise OutboxContractError(f"vendored contract pack {section} digest does not match")
    _PACK_CACHE[key] = pack
    return pack


@dataclass(frozen=True)
class OutboxBinding:
    tenant_id: str
    source_instance_id: str
    source_binding: str
    source_schema_name: str = "intakepilot.requirement"
    source_schema_version: str = "1.0.0"
    commitment_policy: str = "tenant-pepper/v1"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "OutboxBinding":
        v = env if env is not None else os.environ
        binding = cls(
            tenant_id=str(v.get("MANAS_TENANT_ID") or "").strip(),
            source_instance_id=str(v.get("MANAS_SOURCE_INSTANCE_ID") or "").strip(),
            source_binding=str(v.get("MANAS_SOURCE_BINDING") or "").strip(),
            source_schema_name=str(v.get("MANAS_SOURCE_SCHEMA_NAME")
                                   or "intakepilot.requirement").strip(),
            source_schema_version=str(v.get("MANAS_SOURCE_SCHEMA_VERSION") or "1.0.0").strip(),
            commitment_policy=str(v.get("MANAS_COMMITMENT_POLICY") or "tenant-pepper/v1").strip(),
        )
        binding.validate()
        return binding

    def validate(self) -> None:
        checks = {
            "MANAS_TENANT_ID": bool(_SAFE_ID.fullmatch(self.tenant_id)),
            "MANAS_SOURCE_INSTANCE_ID": bool(_REF_COMPONENT.fullmatch(self.source_instance_id)),
            "MANAS_SOURCE_BINDING": bool(_HASH.fullmatch(self.source_binding)),
        }
        invalid = sorted(n for n, ok in checks.items() if not ok)
        if invalid:
            raise OutboxContractError(
                "MANAS outbox binding is incomplete or invalid: " + ", ".join(invalid))

    def requirement_ref(self, requirement_id: str, version: int) -> str:
        return f"req:{self.source_instance_id}:{requirement_id}@v{version}"

    def change_ref(self, change_id: str) -> str:
        return f"change:{self.source_instance_id}:{change_id}"

    def outcome_ref(self, outcome_id: str) -> str:
        return f"outcome:{self.source_instance_id}:{outcome_id}"


# ----------------------------------------------------------------- envelope, built from the pack

def _build(
    binding: OutboxBinding, pack: Mapping[str, Any], event_type: str, payload: Mapping[str, Any],
    recorded_at: str | None,
) -> Emitted | Rejected:
    wire = (pack.get("wire") or {}).get(event_type)
    if wire is None:
        return Rejected("the vendored pack carries no wire specification for this type", event_type)

    observed_at = payload[wire["time_field"]]
    recorded = recorded_at or observed_at
    for label, value in (("observed", observed_at), ("recorded", recorded)):
        if not _WIRE_TS.fullmatch(value):
            return Rejected(f"{label} timestamp is not a MANAS wire timestamp", event_type)
    if (datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
            > datetime.fromisoformat(recorded.replace("Z", "+00:00")) + _MAX_CLOCK_SKEW):
        return Rejected("occurrence is ahead of recordedtime beyond the allowed skew", event_type)

    import jsonschema

    schema = pack["schemas"][event_type]
    errors = [
        f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.validator}"
        for e in sorted(jsonschema.Draft7Validator(schema).iter_errors(dict(payload)),
                        key=lambda e: list(e.absolute_path))
    ]
    if errors:
        return Rejected("payload rejected by the pinned contract: " + "; ".join(errors[:5]),
                        event_type)

    normalized = _jcs_check(dict(payload))
    subject = payload[wire["subject_field"]]
    envelope = {
        "specversion": "1.0",
        "id": str(uuid.uuid5(uuid.NAMESPACE_URL,
                             f"{wire['source']}|{event_type}|{subject}|{observed_at}")),
        "source": wire["source"],
        "type": event_type,
        "dataschema": pack["schema_uris"][event_type],
        "subject": subject,
        "time": observed_at,
        "recordedtime": recorded,
        "contenthash": "sha256:" + hashlib.sha256(canonical_bytes(normalized)).hexdigest(),
        "datacontenttype": "application/json",
        "tenant": binding.tenant_id,
        "lobe": event_type.split(".")[2],
        "piiscrubbed": True,
        "scrubpolicy": wire["scrubpolicy"],
        "schemaversion": wire["schemaversion"],
        "dataclassification": wire["dataclassification"],
        "datacategory": "non-pii",
        "partitionkey": f"{binding.tenant_id}#{payload[wire['partition_field']]}",
        "entityrefs": ",".join(payload[f] for f in wire["ref_fields"]),
        "provenance": json.dumps(
            {
                "agent": wire["agent"],
                "activity": wire["activity"],
                "used": [payload[f] for f in wire["used_fields"]],
                "derived": [payload[f] for f in wire["derived_fields"]],
            },
            separators=(",", ":"), sort_keys=True,
        ),
        "data": normalized,
    }
    _assert_non_pii(envelope["data"])
    return Emitted(envelope["id"], event_type, envelope, envelope["contenthash"])


def emit_requirement_versioned(
    binding: OutboxBinding,
    *,
    requirement_id: str,
    requirement_version: int,
    change_id: str,
    request_type: str,
    intent_text: str,
    acceptance_criteria_text: str,
    pepper: bytes,
    registered_at: str,
    recorded_at: str | None = None,
    pack_path: Path | str = PACK_PATH,
) -> Emitted | Rejected:
    """The exact business-intent version that went to build. The text itself stays in IntakePilot."""
    try:
        binding.validate()
        pack = load_pack(pack_path)
        payload = {
            "requirement_ref": binding.requirement_ref(requirement_id, requirement_version),
            "requirement_id": requirement_id,
            "requirement_version": requirement_version,
            "source_instance_id": binding.source_instance_id,
            "source_binding": binding.source_binding,
            "source_kind": "requirement_version",
            "change_ref": binding.change_ref(change_id),
            "change_id": change_id,
            "status": "ready_for_build",
            "request_type": request_type,
            "intent_commitment": commitment(intent_text, pepper),
            "acceptance_criteria_commitment": commitment(acceptance_criteria_text, pepper),
            "commitment_policy": binding.commitment_policy,
            "source_schema_name": binding.source_schema_name,
            "source_schema_version": binding.source_schema_version,
            "registered_at": registered_at,
        }
        return _build(binding, pack, REQUIREMENT_VERSIONED, payload, recorded_at)
    except OutboxContractError as exc:
        return Rejected(str(exc), REQUIREMENT_VERSIONED)


def emit_outcome_adjudicated(
    binding: OutboxBinding,
    *,
    outcome_id: str,
    deployment_ref: str,
    deployment_source_binding: str,
    requirement_id: str,
    requirement_version: int,
    requirement_source_binding: str,
    change_id: str,
    change_source_binding: str,
    verdict: str,
    adjudicated_by_role: str,
    outcome_evidence_hash: str,
    receipt_text: str,
    pepper: bytes,
    adjudicated_at: str,
    adjudication_policy: str = "intakepilot-adjudication/v1",
    recorded_at: str | None = None,
    pack_path: Path | str = PACK_PATH,
) -> Emitted | Rejected:
    """A human judgement that the delivered result met the need. Delivery status is not success."""
    try:
        binding.validate()
        pack = load_pack(pack_path)
        payload = {
            "outcome_ref": binding.outcome_ref(outcome_id),
            "outcome_id": outcome_id,
            "source_instance_id": binding.source_instance_id,
            "source_binding": binding.source_binding,
            "source_kind": "adjudicated_outcome",
            "deployment_ref": deployment_ref,
            "deployment_source_binding": deployment_source_binding,
            "requirement_ref": binding.requirement_ref(requirement_id, requirement_version),
            "requirement_source_binding": requirement_source_binding,
            "change_ref": binding.change_ref(change_id),
            "change_source_binding": change_source_binding,
            "verdict": verdict,
            # const in the contract: only a human adjudicates an outcome. Not a parameter,
            # so no caller can substitute a model score or a workflow state.
            "adjudication_method": "human",
            "adjudicated_by_role": adjudicated_by_role,
            "outcome_evidence_hash": outcome_evidence_hash,
            "adjudication_receipt_commitment": commitment(receipt_text, pepper),
            "adjudication_policy": adjudication_policy,
            "adjudicated_at": adjudicated_at,
        }
        return _build(binding, pack, OUTCOME_ADJUDICATED, payload, recorded_at)
    except OutboxContractError as exc:
        return Rejected(str(exc), OUTCOME_ADJUDICATED)
