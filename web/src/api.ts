import type {
  ConfirmResponse,
  DecisionEvent,
  GateResult,
  Question,
  RequirementObject,
  Slot,
  SlotSchemaEntry,
  TurnResult
} from "./types";

export type { DecisionEvent };

export interface HealthResponse { status: string; provider: string; store: string; }
export interface SchemaResponse {
  request_type: string;
  available_types: string[];
  slots: Record<string, SlotSchemaEntry>;
}
export interface SessionCreateResponse { session_id: string; req_id: string; draft: RequirementObject; }
export interface SessionTurnEntry { role: "user" | "assistant"; text: string; at: string; }
export interface SessionDetail {
  session_id: string; req_id: string; draft: RequirementObject;
  pending_questions: Question[]; turns: SessionTurnEntry[];
}
export interface RenderResponse { business: string; }
export interface MetricsResponse {
  totals: { intakes: number; confirmed: number; routed: number; edits: number; questions_asked: number };
  intake_latency_seconds_avg: number | null;
  questions_per_intake_avg: number | null;
  edit_rate_per_field: Record<string, number>;
  routing_accuracy: number | null;
  duplicate_catch_rate: number | null;
  analyst_hours_displaced: number;
  assumption_rate: number | null;
  system_kb: { entities: number; customizations: number; verified: number };
}

export interface TurnAnswer { question_id: string; slot_key: string; value: unknown; }
export interface TurnRequestBody {
  message: string;
  answers?: TurnAnswer[];
  /** Mid-session Shadow Draft revisions: {slot_key: new value}. */
  revisions?: Record<string, string>;
}

export type TurnStage = "extracting" | "resolving_gaps" | "composing_questions" | "scoring";

export interface TurnStreamHandlers {
  onStatus?: (stage: TurnStage) => void;
  onSlot?: (key: string, slot: Slot) => void;
  onDecision?: (decision: DecisionEvent) => void;
  onReadiness?: (score: number) => void;
  onQuestions?: (questions: Question[]) => void;
}

async function toJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = "";
    try { detail = await res.text(); } catch { /* body unreadable */ }
    throw new Error(`Request failed (${res.status})${detail ? `: ${detail.slice(0, 200)}` : ""}`);
  }
  return res.json() as Promise<T>;
}

const jsonHeaders = { "Content-Type": "application/json" };

export function getHealth(): Promise<HealthResponse> {
  return fetch("/health").then((r) => toJson<HealthResponse>(r));
}

export function getSchema(type = "default"): Promise<SchemaResponse> {
  return fetch(`/api/schema?type=${encodeURIComponent(type)}`).then((r) => toJson<SchemaResponse>(r));
}

export function createSession(requester?: { name: string; dept: string; role: string }): Promise<SessionCreateResponse> {
  return fetch("/api/sessions", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(requester ? { requester } : {})
  }).then((r) => toJson<SessionCreateResponse>(r));
}

export function getSession(sessionId: string): Promise<SessionDetail> {
  return fetch(`/api/sessions/${sessionId}`).then((r) => toJson<SessionDetail>(r));
}

/** Requirements are session-bound: the API rejects calls without the
 * X-Session-Id of the session that created the requirement. */
function ownerHeaders(sessionId: string): Record<string, string> {
  return { "X-Session-Id": sessionId };
}

export function getRequirement(reqId: string, sessionId: string): Promise<RequirementObject> {
  return fetch(`/api/requirements/${reqId}`, { headers: ownerHeaders(sessionId) })
    .then((r) => toJson<RequirementObject>(r));
}

export function getRequirementHistory(reqId: string, sessionId: string): Promise<RequirementObject[]> {
  return fetch(`/api/requirements/${reqId}/history`, { headers: ownerHeaders(sessionId) })
    .then((r) => toJson<RequirementObject[]>(r));
}

export function getRender(reqId: string, sessionId: string): Promise<RenderResponse> {
  return fetch(`/api/requirements/${reqId}/render`, { headers: ownerHeaders(sessionId) })
    .then((r) => toJson<RenderResponse>(r));
}

export function confirmRequirement(
  reqId: string,
  sessionId: string,
  edits: Record<string, unknown>,
  confirmedBy?: string
): Promise<ConfirmResponse> {
  return fetch(`/api/requirements/${reqId}/confirm`, {
    method: "POST",
    headers: { ...jsonHeaders, ...ownerHeaders(sessionId) },
    body: JSON.stringify({ edits, ...(confirmedBy ? { confirmed_by: confirmedBy } : {}) })
  }).then((r) => toJson<ConfirmResponse>(r));
}

export function getMetrics(): Promise<MetricsResponse> {
  return fetch("/api/metrics").then((r) => toJson<MetricsResponse>(r));
}

export interface ShareCreateResponse { token: string; url: string; expires_at: string; }
export interface SharePayload {
  req_id: string;
  draft: RequirementObject;
  decisions: DecisionEvent[];
  gates: GateResult[] | null;
  routing: ConfirmResponse["routing"] | null;
  ticket: ConfirmResponse["ticket"] | null;
  collisions: ConfirmResponse["collisions"] | null;
  acceptance: unknown[] | null;
  title_hint: string;
  ask_verbatim: string;
  queue: string | null;
  readiness_score: number;
  status: string;
}

export function createShare(
  reqId: string,
  sessionId: string,
  body: {
    decisions?: DecisionEvent[];
    gates?: GateResult[];
    routing?: ConfirmResponse["routing"];
    ticket?: ConfirmResponse["ticket"];
    collisions?: ConfirmResponse["collisions"];
    acceptance?: unknown[];
  } = {}
): Promise<ShareCreateResponse> {
  return fetch(`/api/requirements/${reqId}/share`, {
    method: "POST",
    headers: { ...jsonHeaders, ...ownerHeaders(sessionId) },
    body: JSON.stringify(body)
  }).then((r) => toJson<ShareCreateResponse>(r));
}

export function getShare(token: string): Promise<SharePayload> {
  return fetch(`/api/share/${encodeURIComponent(token)}`).then((r) => toJson<SharePayload>(r));
}

export function cloneFromShare(token: string): Promise<SessionCreateResponse> {
  return fetch(`/api/share/${encodeURIComponent(token)}/clone`, {
    method: "POST",
    headers: jsonHeaders,
    body: "{}"
  }).then((r) => toJson<SessionCreateResponse>(r));
}

export function cloneFromTriage(reqId: string): Promise<SessionCreateResponse> {
  return fetch(`/api/triage/${encodeURIComponent(reqId)}/clone`, {
    method: "POST",
    headers: jsonHeaders,
    body: "{}"
  }).then((r) => toJson<SessionCreateResponse>(r));
}

export interface TriageItem {
  req_id: string; status: string; queue: string | null;
  title_hint: string; readiness_score: number; ask_verbatim: string;
}

export function getTriage(limit = 50): Promise<{ items: TriageItem[] }> {
  return fetch(`/api/triage?limit=${limit}`).then((r) => toJson<{ items: TriageItem[] }>(r));
}

export interface GlossaryProposal { term: string; maps_to: unknown; evidence_count?: number; [k: string]: unknown; }

export function getGlossaryProposals(): Promise<{ proposals: GlossaryProposal[] } | GlossaryProposal[]> {
  return fetch("/api/glossary/proposals").then((r) => toJson<{ proposals: GlossaryProposal[] } | GlossaryProposal[]>(r));
}

export function acceptGlossaryTerm(term: string, mapsTo: unknown): Promise<unknown> {
  return fetch("/api/glossary", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ term, maps_to: mapsTo })
  }).then((r) => toJson<unknown>(r));
}

export function rerouteRequirement(reqId: string, queue: string): Promise<unknown> {
  return fetch(`/api/requirements/${reqId}/reroute`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ queue })
  }).then((r) => toJson<unknown>(r));
}

export function getGraph(): Promise<{ nodes: { id: string; label?: string }[]; edges: { source: string; target: string; shared?: string[] }[] }> {
  return fetch("/api/graph").then((r) => toJson(r));
}

export interface AttachResponse { draft: RequirementObject; attached_to: string; }

/** Duplicate-merge: close this (gated) requirement as a duplicate of target. */
export function attachRequirement(
  reqId: string,
  sessionId: string,
  targetReqId: string
): Promise<AttachResponse> {
  return fetch(`/api/requirements/${reqId}/attach`, {
    method: "POST",
    headers: { ...jsonHeaders, ...ownerHeaders(sessionId) },
    body: JSON.stringify({ target_req_id: targetReqId })
  }).then((r) => toJson<AttachResponse>(r));
}

import { parseFrame } from "./sseParse";
export { parseFrame };

/**
 * Send a turn and consume the SSE stream, invoking handlers per event.
 * Turns are NOT idempotent (they spend question budget and append versions),
 * so a broken stream is never retried with a second POST. Instead the
 * authoritative post-turn state is recovered with GET /api/sessions/{id}
 * (the recovery contract in docs/SPEC-REVIEW.md). Server-sent `error`
 * events surface as thrown Errors with the server's detail message.
 */
export async function sendTurn(
  sessionId: string,
  body: TurnRequestBody,
  handlers: TurnStreamHandlers = {},
  signal?: AbortSignal
): Promise<TurnResult> {
  let turnReached = false; // did the server receive/process the turn?
  try {
    const res = await fetch(`/api/sessions/${sessionId}/turns`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(body),
      signal
    });
    if (!res.ok) throw new Error(`Turn request failed (${res.status})`);
    turnReached = true;
    if (!res.body) throw new Error("Streaming not supported by this browser");

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let result: TurnResult | null = null;

    const handleFrame = (frame: string) => {
      const { event, data } = parseFrame(frame);
      if (!data) return;
      const payload: unknown = JSON.parse(data);
      switch (event) {
        case "status":
          handlers.onStatus?.((payload as { stage: TurnStage }).stage);
          break;
        case "slot": {
          const p = payload as { key: string; slot: Slot };
          handlers.onSlot?.(p.key, p.slot);
          break;
        }
        case "decision":
          handlers.onDecision?.(payload as DecisionEvent);
          break;
        case "readiness":
          handlers.onReadiness?.((payload as { score: number }).score);
          break;
        case "questions":
          handlers.onQuestions?.((payload as { questions: Question[] }).questions);
          break;
        case "done":
          result = payload as TurnResult;
          break;
        case "error":
          throw new TurnFailedError((payload as { detail?: string }).detail ?? "Turn failed");
      }
    };

    for (;;) {
      if (signal?.aborted) {
        await reader.cancel();
        throw new DOMException("Aborted", "AbortError");
      }
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let sep: number;
      while ((sep = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        handleFrame(frame);
      }
    }
    buffer += decoder.decode();
    if (buffer.trim()) handleFrame(buffer);

    if (!result) throw new Error("Stream ended without a done event");
    return result;
  } catch (err) {
    if ((err as { name?: string })?.name === "AbortError") throw err;
    // Pre-flight failure (network error, non-2xx): the turn didn't run.
    if (!turnReached) throw err;
    // The server itself reported the turn failed: surface its message.
    if (err instanceof TurnFailedError) throw err;
    // The turn reached the server but the stream broke mid-flight: recover
    // the authoritative state via GET instead of replaying the POST.
    const s = await getSession(sessionId);
    return {
      draft: s.draft,
      questions: s.pending_questions,
      confirm_unlocked: ["awaiting_confirmation", "confirmed", "gated", "routed"]
        .includes(s.draft.status),
      degraded: false
    };
  }
}

/** Marker for failures the server reported via an SSE `error` event. */
class TurnFailedError extends Error {}
