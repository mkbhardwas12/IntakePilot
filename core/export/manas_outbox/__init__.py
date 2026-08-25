"""MANAS Demand-lobe outbox for IntakePilot. Default-off; commitments, never narrative."""

from .emitter import (
    Emitted,
    OutboxBinding,
    OutboxContractError,
    Rejected,
    commitment,
    emit_outcome_adjudicated,
    emit_requirement_versioned,
    load_pack,
    outbox_enabled,
)

__all__ = [
    "Emitted", "OutboxBinding", "OutboxContractError", "Rejected", "commitment",
    "emit_outcome_adjudicated", "emit_requirement_versioned", "load_pack", "outbox_enabled",
]
