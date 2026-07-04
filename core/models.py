"""Pydantic data model — spec Section 4.1, copy-paste faithful.

Shapes the spec names but never defines (Requester, Budget, Confirmation,
RoutingDecision, AuditEvent) are defined here; see docs/SPEC-REVIEW.md #9.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Status(str, Enum):
    DRAFT = "draft"
    QUESTIONING = "questioning"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    CONFIRMED = "confirmed"
    GATED = "gated"
    ROUTED = "routed"
    BUILDING = "building"
    IN_REVIEW = "in_review"
    DONE = "done"
    REJECTED = "rejected"


class Provenance(str, Enum):
    EXTRACTED = "extracted"   # from user text
    INFERRED = "inferred"     # from context (role, dept, history)
    RETRIEVED = "retrieved"   # from precedent / glossary
    ANSWERED = "answered"     # user answered a question
    ASSUMED = "assumed"       # budget exhausted, default applied
    EDITED = "edited"         # human corrected at confirmation


class Slot(BaseModel):
    value: Any | None = None
    provenance: Provenance | None = None
    confidence: float = 0.0
    source: str | None = None      # precedent id, question id, ...
    default_reason: str | None = None


class Requester(BaseModel):
    id: str = "anonymous"
    name: str = "Anonymous"
    dept: str = "General"
    role: str = "Requester"


class Budget(BaseModel):
    max: int = 7
    per_turn: int = 3
    spent: int = 0


class Confirmation(BaseModel):
    confirmed_by: str
    confirmed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    edits: int = 0


class RoutingAlternative(BaseModel):
    queue: str
    score: float


class RoutingDecision(BaseModel):
    queue: str
    confidence: float
    explanation: str
    alternatives: list[RoutingAlternative] = []


class AuditEvent(BaseModel):
    event: str
    at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    detail: str = ""


class RequirementObject(BaseModel):
    req_id: str                    # "IPR-{yyyy}-{seq:06d}"
    version: int = 1
    status: Status = Status.DRAFT
    requester: Requester
    ask_verbatim: str              # NEVER mutated; the original words
    slots: dict[str, Slot] = {}
    question_budget: Budget = Field(default_factory=Budget)
    assumptions: list[str] = []    # slot keys with provenance=assumed
    readiness_score: int = 0
    confirmation: Confirmation | None = None
    routing: RoutingDecision | None = None
    audit: list[AuditEvent] = []   # append-only, every transition

    # E: set by the deterministic request-type classifier on the first turn;
    # selects the slot-schema fork and the learning bucket.
    request_type: str = "default"

    @property
    def context_bucket(self) -> str:
        """dept × request type — the tenancy/learning isolation key."""
        return f"{self.requester.dept}:{self.request_type}"

    def touch(self, event: str, detail: str = "") -> None:
        self.audit.append(AuditEvent(event=event, detail=detail))


class Question(BaseModel):
    id: str
    slot_key: str
    text: str
    because: str = ""
    options: list[str] | None = None


class TurnResult(BaseModel):
    draft: RequirementObject
    questions: list[Question] = []
    confirm_unlocked: bool = False
    degraded: bool = False


class GateResult(BaseModel):
    gate: int
    name: str
    passed: bool
    reason: str | None = None
    suggestion: str | None = None
    # Structured, machine-readable context (e.g. gate 4 sets duplicate_of +
    # similarity so the UI can offer "attach to existing" instead of parsing
    # the reason string).
    meta: dict = {}


class Ticket(BaseModel):
    target: str
    ref: str
    path: str
    title: str


class ConfirmResponse(BaseModel):
    draft: RequirementObject
    gates: list[GateResult]
    routing: RoutingDecision
    ticket: Ticket | None = None


class ExtractionError(Exception):
    """LLM output failed schema validation twice — orchestrator degrades gracefully."""
