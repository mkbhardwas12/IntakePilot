"""MANAS Demand exporter — metadata-only CloudEvents-shaped records.

Emits three event types for downstream MANAS smriti compilation:
  - io.manas.demand.asked:     When a data_request slot is extracted/confirmed
  - io.manas.demand.corrected: When a slot edit_diff is captured at confirmation
  - io.manas.demand.observed:  When enrichment discovers backend entities

HARD RULES (enforced in code, not prompt):
  - Metadata never row data: no VIN/IBAN/email/PAN or any PII in props
  - Hash all free text (sha256 of utf-8); store hashes + slot names + provenance
  - No environment identifiers (no hostnames, SIDs, landscape names)
  - LLM never in control of emit/gate/routing

Event shape follows CloudEvents spec:
  {
    "type": "io.manas.demand.asked",
    "source": "//manas/demand/intakepilot",
    "id": "<uuid>",
    "time": "<iso8601>",
    "data": { ... hashed slot data ... },
    "verified": true|false
  }

The sink is configurable: in-process list (test), append-only file, or off (default).
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable

from pydantic import BaseModel


EVENT_SOURCE = "//manas/demand/intakepilot"

ASKABLE_SLOTS = frozenset([
    "business_outcome",
    "success_criteria",
    "refresh_frequency",
    "data_fields",
    "urgency",
])


def _hash_text(text: str) -> str:
    """SHA256 hash of utf-8 encoded text. Never store the original."""
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _safe_value(value: Any) -> str:
    """Convert any value to a hashable string representation."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


class DemandEvent(BaseModel):
    """CloudEvents-shaped metadata record for MANAS Demand."""
    type: str
    source: str = EVENT_SOURCE
    id: str
    time: str
    data: dict
    verified: bool = False


@runtime_checkable
class DemandSink(Protocol):
    """Protocol for MANAS Demand event sinks."""
    async def write(self, event: DemandEvent) -> None: ...


class NullSink:
    """Default sink — discards all events (exporter off)."""
    async def write(self, event: DemandEvent) -> None:
        pass


class ListSink:
    """In-process list sink for testing."""
    def __init__(self) -> None:
        self.events: list[DemandEvent] = []

    async def write(self, event: DemandEvent) -> None:
        self.events.append(event)

    def clear(self) -> None:
        self.events.clear()


class FileSink:
    """Append-only file sink. One JSON line per event."""
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    async def write(self, event: DemandEvent) -> None:
        line = event.model_dump_json() + "\n"
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line)


_sink: DemandSink = NullSink()


def configure_sink(sink: DemandSink | None = None,
                   file_path: str | None = None) -> DemandSink:
    """Configure the global MANAS Demand sink.
    
    - sink=None, file_path=None: NullSink (off, default)
    - sink provided: use that sink directly
    - file_path provided: FileSink to that path
    
    Returns the configured sink for test inspection.
    """
    global _sink
    if sink is not None:
        _sink = sink
    elif file_path:
        _sink = FileSink(file_path)
    else:
        _sink = NullSink()
    return _sink


def get_sink() -> DemandSink:
    """Get the current sink (for testing)."""
    return _sink


def _make_event(event_type: str, data: dict, verified: bool = False) -> DemandEvent:
    """Create a CloudEvents-shaped MANAS Demand event."""
    return DemandEvent(
        type=event_type,
        source=EVENT_SOURCE,
        id=uuid.uuid4().hex,
        time=datetime.now(timezone.utc).isoformat(),
        data=data,
        verified=verified,
    )


async def emit_asked(
    req_id: str,
    slot_key: str,
    value_hash: str,
    provenance: str,
    context_bucket: str,
) -> DemandEvent | None:
    """Emit io.manas.demand.asked when a data_request slot is filled.
    
    Only emits for askable slots defined in core/schemas/data_request.yaml.
    Value is already hashed by the caller.
    """
    if slot_key not in ASKABLE_SLOTS:
        return None
    
    data = {
        "req_id": req_id,
        "slot_key": slot_key,
        "value_hash": value_hash,
        "provenance": provenance,
        "context_bucket": context_bucket,
    }
    event = _make_event("io.manas.demand.asked", data, verified=True)
    await _sink.write(event)
    return event


async def emit_corrected(
    req_id: str,
    slot_key: str,
    proposed_hash: str,
    corrected_hash: str,
    provenance: str | None,
    context_bucket: str,
) -> DemandEvent | None:
    """Emit io.manas.demand.corrected when a slot edit_diff is captured.
    
    Only emits for askable slots. Both proposed and corrected values are hashed.
    """
    if slot_key not in ASKABLE_SLOTS:
        return None
    
    data = {
        "req_id": req_id,
        "slot_key": slot_key,
        "proposed_hash": proposed_hash,
        "corrected_hash": corrected_hash,
        "provenance": provenance or "unknown",
        "context_bucket": context_bucket,
    }
    event = _make_event("io.manas.demand.corrected", data, verified=True)
    await _sink.write(event)
    return event


async def emit_observed(
    req_id: str,
    implicated_fields: list[dict],
    context_bucket: str,
) -> DemandEvent | None:
    """Emit io.manas.demand.observed when enrichment discovers backend entities.
    
    implicated_fields contains metadata only: {table, field, kind, owner_team}.
    No row values, no environment identifiers.
    """
    if not implicated_fields:
        return None
    
    safe_fields = []
    for f in implicated_fields:
        safe_fields.append({
            "table": f.get("table", ""),
            "field": f.get("field", ""),
            "kind": f.get("kind", ""),
            "owner_team": f.get("owner_team", ""),
            "provenance": "retrieved",
        })
    
    data = {
        "req_id": req_id,
        "implicated_fields": safe_fields,
        "context_bucket": context_bucket,
    }
    event = _make_event("io.manas.demand.observed", data, verified=True)
    await _sink.write(event)
    return event


def hash_slot_value(value: Any) -> str:
    """Hash a slot value for MANAS Demand emission.
    
    Public helper for callers to hash values before emission.
    """
    return _hash_text(_safe_value(value))


def extract_implicated_fields(backend_context: dict) -> list[dict]:
    """Extract implicated fields from backend_context for observed emission.
    
    Returns metadata only: table (backend_name), field name, kind, owner_team.
    No row values, no system identifiers beyond what's needed for join identity.
    """
    fields: list[dict] = []
    for entity in backend_context.get("entities", []):
        table = entity.get("backend_name", "")
        for custom in entity.get("customizations", []):
            fields.append({
                "table": table,
                "field": custom.get("name", ""),
                "kind": custom.get("kind", ""),
                "owner_team": custom.get("owner_team", ""),
            })
    return fields
