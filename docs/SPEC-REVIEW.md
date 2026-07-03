# IntakePilot Build Specification v1.0 — Review

Reviewed against: `docs/build-specification.txt` (July 2026). Verdict up front: this is an unusually good spec — implementation-grade in the places that matter most (data model, provider protocols, orchestrator loop, invariants) — but it has real gaps that an implementer must fill before the system is production-shaped. This document lists what is strong, what is missing or underspecified, and what we chose where the spec was silent.

---

## What is strong

1. **Deterministic control plane, LLM as component.** Section 6's "budget enforced in code, NOT in prompt" and Section 11's invariants are the right architecture. Most agent products get this backwards. The pseudocode in 6.1 is genuinely implementable verbatim.
2. **The learning loop lives in the data tier.** Storing all learned knowledge as ledger rows injected at prompt time (7.2) makes the system model-agnostic for real, makes learning auditable ("print exactly which corrections influenced this draft"), and blocks self-training feedback loops because only human-originated signals enter the ledgers.
3. **`askable:false` as a single-flag policy.** Encoding "never ask business users engineering questions" as schema data rather than prompt language is elegant and testable.
4. **Provenance as a first-class enum.** Six provenance states on every slot give the UI, the gates, and the learning loop a shared vocabulary. The merge rule (never overwrite ANSWERED/EDITED) falls out naturally.
5. **Benchmark-gated self-improvement (7.4).** Promotion only on golden-set parity-or-better, with one-UPDATE rollback, closes the classic drift failure mode of self-improving systems.
6. **Metrics computed from ledgers, no extra instrumentation (Section 9).** The ROI story and the observability story are the same tables.

## What is missing or underspecified

### 1. `readiness(obj)` is referenced but never defined *(critical — gates the whole UX)*
The turn loop calls `readiness(obj)` and the confirm button unlocks at `>= 70`, but no scoring rubric exists anywhere in the spec. This number drives the core user experience and the "readiness_at_confirm" eval metric, so two implementations of this spec would not be comparable.

**What we implemented** (documented in `core/agents/orchestrator.py`):

```
readiness = round(100 * (0.85 * required_coverage + 0.15 * optional_coverage))

each FILLED slot contributes: 0.7 + 0.3 * provenance_weight * confidence
provenance weights: answered/edited = 1.0, extracted = 0.9,
                    retrieved = 0.85, inferred = 0.75, assumed = 0.6
```

Required-slot coverage dominates; a filled slot is mostly ready (base 0.7) with
provenance and confidence tuning the remainder, so human-verified slots count
more than machine guesses and ASSUMED slots can't carry a draft to 100 on their
own. The spec should adopt an explicit rubric like this.

### 2. No auth or multi-tenancy model *(critical for anything beyond a demo)*
`Requester` exists as a model but nothing says how identity is established, whether sessions are scoped to a requester, or how one deployment serves multiple departments/orgs. `context_bucket` ("dept x req_type") implies tenancy-like partitioning of the learning data, but there is no isolation rule — dept A's edit diffs will be injected into dept B's prompts unless bucket filtering is mandatory, which is both a quality and a confidentiality problem. Recommendation: make `context_bucket` filtering a hard invariant in `select_exemplars` (we did), and spec an auth layer (OIDC in front of FastAPI, requester derived from the token) before Milestone 6.

### 3. Turn-loop error and timeout handling is one sentence
"The orchestrator degrades gracefully: keeps prior slots, flags turn" covers extraction failure only. Unspecified: LLM timeouts (Ollama cold-start can be 60s+), what a "flagged turn" looks like in the API contract and the UI, whether a failed turn consumes question budget (it must not), retry semantics for the *store* write at step 5, and what happens if the process dies between `spent += len(questions)` and `put_version` (budget spent is only durable inside the object — fine — but the question_ledger row could be lost). Recommendation: spec per-provider timeouts, an explicit `turn_degraded: bool` on `TurnResult`, and write the object version before returning questions to the user (we do).

### 4. Concurrency on session turns is unaddressed
Two concurrent POSTs to the same session both read `latest(req_id)`, both spend budget, both append version N+1 — the append-only primary key makes the second write *fail*, which is good, but the spec never says who wins or how the client is told. We serialize turns with a per-session mutex and return 409 on version conflicts. A spec-level statement (optimistic concurrency via the version PK, one in-flight turn per session) is needed, especially for the DynamoDB mapping where a conditional write is required.

### 5. Streaming contract is a parenthesis
"(append version, stream deltas)" and Milestone 4's "(SSE)" is all the spec says. Undefined: event names, delta granularity (per-slot? per-token?), how questions and readiness arrive, reconnection/idempotency. We defined a concrete SSE contract (`slot`, `readiness`, `questions`, `status`, `done` events; the terminal `done` event carries the full TurnResult so a dropped stream can be recovered by a plain GET). This belongs in the spec as an API appendix.

### 6. Webhook endpoints have no security section
`register_webhook` and status sync from GitHub/Jira are in the plugin protocol, and `webhooks` is a router in the repo layout — but there is no mention of signature verification (HMAC `X-Hub-Signature-256` for GitHub), replay protection, or idempotency of status updates. Inbound webhooks are the only unauthenticated write path into the system; this is the most security-sensitive omission in the spec.

### 7. No migration tooling
Section 4.3 gives DDL but nothing manages schema evolution (Alembic for Postgres, versioned mapping for DynamoDB). The learning tables *will* evolve (7.3 already implies new columns like ask-priority). Also `VECTOR(768)` hard-codes an embedding dimension while the provider protocol lets you swap embedding models — dimension should be config, and a model swap needs a re-embedding job the spec doesn't mention.

### 8. Observability beyond product metrics
Section 9 is ROI metrics, which is great, but there is no operational story: no structured logging spec, no tracing across the extract → gap → question chain, no per-provider latency/cost accounting (token counts are not even captured on `LLMResult`). Cheap fix: `audit` already exists on the object — spec required audit events per turn stage with durations, and add `usage` to `LLMResult`.

### 9. Smaller but real gaps
- **`Requester`, `Confirmation`, `RoutingDecision`, `AuditEvent`, `Budget` fields are never defined** — 4.1 names them, we had to invent their shapes.
- **Question re-asking rules**: `question.md` says "Never re-ask: {answered}" but the spec never defines what happens when a user *skips* a question — does it stay open forever? (We: skipped slots remain gaps but drop in rank; a "don't know" applies the default immediately.)
- **Gate 3 word list is unspecified** ("weak-word list plus context check") — the list is org policy and should be a config file, not code (we ship it as `core/gates/weak_words.txt`).
- **Routing taxonomy**: the classifier picks "the target queue" but nothing defines where queues come from. We made them config (`intakepilot.yaml: routing.queues`) with keyword/embedding evidence per queue.
- **`IPR-{yyyy}-{seq:06d}`** needs an allocation strategy under concurrency (sequence table / atomic counter); a UUID suffix would be simpler and the spec should say why it wants pretty IDs.
- **Ollama `format=json`** does not enforce a *schema*, only valid JSON — the validate-and-retry wrapper is doing all the schema work, which the spec implies but should state (structured-output support varies by provider and model).
- **Cold start for routing**: 7.5 covers exemplars/glossary but the routing classifier has no labeled data until tickets get re-routed; the spec should mention seeding queue keywords (we did that in config).

## Recommendations (priority order)

1. Define the readiness rubric normatively (adopt or amend the formula above).
2. Add an auth + tenancy section; make `context_bucket` isolation an invariant in 11.
3. Specify the SSE event contract and turn-degradation semantics in the API layer.
4. Add webhook signature verification + idempotency to the TargetPlugin contract.
5. Adopt Alembic from Milestone 2; make embedding dimension configuration.
6. Add `usage`/latency to `LLMResult` and required per-stage audit events.
7. Define the undefined model shapes (Requester et al.) in 4.1 so implementations are interoperable.

None of these change the architecture — they are specification completeness issues. The core design is sound and, as this repo demonstrates, buildable as specified.
