export type Provenance = "extracted" | "inferred" | "retrieved" | "answered" | "assumed" | "edited";
export type Status = "draft" | "questioning" | "awaiting_confirmation" | "confirmed" | "gated" | "routed" | "building" | "in_review" | "done" | "rejected";

export interface Slot { value: unknown; provenance: Provenance | null; confidence: number; source: string | null; default_reason: string | null; }
export interface Requester { id: string; name: string; dept: string; role: string; }
export interface Budget { max: number; per_turn: number; spent: number; }
export interface Confirmation { confirmed_by: string; confirmed_at: string; edits: number; }
export interface RoutingDecision { queue: string; confidence: number; explanation: string; alternatives: { queue: string; score: number }[]; }
export interface AuditEvent { event: string; at: string; detail: string; }
export interface RequirementObject {
  req_id: string; version: number; status: Status; requester: Requester;
  ask_verbatim: string; slots: Record<string, Slot>; question_budget: Budget;
  assumptions: string[]; readiness_score: number;
  confirmation: Confirmation | null; routing: RoutingDecision | null; audit: AuditEvent[];
  request_type: string;
}
export interface Question { id: string; slot_key: string; text: string; because: string; options: string[] | null; }
export interface BackendCustomization { name: string; type: string; description: string; owner_team: string; kind: string; }
export interface BackendEntity {
  system: string; system_label: string; entity: string; label: string;
  backend_name: string; description: string; matched_term: string;
  verified: boolean; customizations: BackendCustomization[];
}
export interface BackendContext { systems: string[]; entities: BackendEntity[]; discovered_at?: string; }
export type DecisionAction =
  | "extracted" | "inferred" | "retrieved" | "asked"
  | "skipped" | "assumed" | "answered" | "edited";
export interface DecisionEvent {
  slot: string;
  action: DecisionAction;
  reason: string;
  source: string | null;
}
export interface TurnResult { draft: RequirementObject; questions: Question[]; confirm_unlocked: boolean; degraded: boolean; }
export interface SlotSchemaEntry { required: boolean; askable: boolean; ask_hint?: string; default?: unknown; default_reason?: string; label: string; }
export interface GateResult {
  gate: number; name: string; passed: boolean;
  reason: string | null; suggestion: string | null;
  meta?: Record<string, unknown>;
}
export interface Ticket { target: string; ref: string; path: string; title: string; }
export interface Collision { req_id: string; status: string; queue: string | null; shared: string[]; }
export interface ConfirmResponse {
  draft: RequirementObject; gates: GateResult[]; routing: RoutingDecision;
  collisions?: Collision[]; ticket: Ticket | null;
}
