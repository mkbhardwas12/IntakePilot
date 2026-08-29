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


class ProcessMatch(BaseModel):
    """Where the ask sits in the business — decided deterministically from
    curated signals in core/knowledge/processes.yaml, never by a model."""
    key: str
    label: str
    confidence: float
    evidence: list[str] = []   # the signal phrases that voted


class UnstatedNeed(BaseModel):
    """Something requesters reliably forget to say. `covered` flips as slots
    fill, so the checklist is live across the session."""
    need: str
    why: str
    status: str = "open"           # open | covered
    covered_by: str | None = None  # slot key that settled it, when covered
    # In-schema slot keys that could settle it — the deterministic bridge
    # from an open need to a question candidate.
    candidate_slots: list[str] = []
    # How many delivered requirements left this need open at confirm and were
    # later adjudicated as missing the mark — production evidence it matters.
    evidence_count: int = 0


class AnalystRisk(BaseModel):
    risk: str
    why: str


class AnalystRead(BaseModel):
    """The analyst's interpretation of the ask: process placement (curated
    knowledge), a plain-language reading of the underlying need (LLM-composed,
    deterministic fallback), and what a seasoned BA would still check."""
    process: ProcessMatch | None = None
    interpretation: str = ""
    interpretation_source: str = "llm"   # llm | deterministic
    unstated_needs: list[UnstatedNeed] = []
    risks: list[AnalystRisk] = []
    kpis: list[str] = []


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

    # The analyst's read of the ask — recomputed each interactive turn so the
    # unstated-needs checklist tracks the live slots.
    analyst: AnalystRead | None = None

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
    revised: int = 0
    # The analyst's account of the turn — composed deterministically from
    # what actually happened (placements, fills by provenance, questions,
    # open decisions), never from a template that ignores the turn.
    narrative: str = ""


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


def coerce_edit(proposed: Any, corrected: Any) -> Any:
    """UI edit fields are strings; restore the slot's original type so a
    list-valued slot edited as "a, b" doesn't become one string, and numeric
    slots don't silently become text. Shared by confirmation edits and
    mid-session revisions."""
    if not isinstance(corrected, str):
        return corrected
    if isinstance(proposed, list):
        return [part.strip() for part in corrected.split(",") if part.strip()]
    if isinstance(proposed, bool):
        return corrected.strip().lower() in ("true", "yes", "1")
    if isinstance(proposed, (int, float)):
        try:
            num = float(corrected)
            return int(num) if num.is_integer() and isinstance(proposed, int) else num
        except ValueError:
            return corrected
    return corrected
