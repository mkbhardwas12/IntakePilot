# IntakePilot → MANAS Integration Recommendations

**Status:** actionable architecture recommendation, not a claim of deployed integration

**Repository source-code evidence reviewed:** `42c1280`; current `main` at `0501575` adds the initial version of this
recommendation document but no product-code change, plus unmerged local refs `pr-1-demand` and `pr-2-admit`

**MANAS consumer baseline:** `0.1.0` exact-thread contract baseline. Producer work must pin the reviewed MANAS commit,
catalog subset, and shared-fixture digest in both repositories; this recommendation does not invent a schema digest.

**Last reviewed:** 2026-08-23

## MANAS 0.1.0 exact-thread integration delta

MANAS `0.1.0` now has executable, closed consumers for the complete redacted change thread. The two IntakePilot-owned
facts in that thread are:

| MANAS contract | Why IntakePilot must issue it | Source fact that must remain in IntakePilot |
|---|---|---|
| `io.manas.demand.requirement.versioned.v2` | Establishes the exact, immutable business-intent version and one explicit change reference that CleanCore and BasisPilot must reuse. It prevents a ticket label, copied ID, or similar field name from becoming an inferred join. | Original ask, typed version, changed-field history, clarification evidence, accepted assumptions, confirmation, request schema/version, and the authoritative mapping between `requirement_ref` and `change_ref`. |
| `io.manas.demand.outcome.adjudicated.v1` | Closes the loop only after an identified business owner or product owner judges the deployed result. This is the reviewed evidence MANAS may use for similar-change memory; delivery status alone is not success. | Full outcome evidence, reviewer authority, any narrative/rationale, source ACL, deployment citation, decision history, and later corrections. |

The `requirement.versioned.v2` outbox record must use the exact closed payload: source-qualified requirement and change
refs, immutable source binding, status `ready_for_build`, bounded request type, HMAC-form intent and acceptance-criteria
commitments, commitment policy, source schema name/version, and registration time. The
`outcome.adjudicated.v1` record must bind the exact deployment, requirement, and change refs plus their immutable source
bindings; it carries only the bounded verdict, human method/role, evidence hash, adjudication commitment/policy, and
time. Raw business narratives, names, email addresses, generated code, and source rows remain outside the default event.

### Required IntakePilot source work

1. Add an authenticated, tenant-scoped transactional outbox. The authoritative requirement version or outcome,
   approval/adjudication receipt, and deterministic event row commit atomically; MANAS availability never controls the
   user transaction.
2. Persist one organization-governed `change_ref` before build handoff and reuse it without reconstruction. Keep all
   source refs, bindings, event IDs, schema versions, receipts, publish attempts, acknowledgements, and dead-letter
   state for deterministic replay and audit.
3. Make the 12 MANAS golden pilot questions a sponsor-approved, versioned pilot artifact before observation begins.
   IntakePilot must retain who accepted the catalog, when it was accepted, the original need and manual-handoff
   baseline for each sampled change, and the source evidence used to answer each question. The catalog is an evaluation
   agreement, not an event payload and not permission to manufacture missing historical identifiers.
4. Emit `outcome.adjudicated.v1` only after the exact BasisPilot deployment receipt is available and an authenticated
   `business_owner` or `product_owner` chooses `achieved`, `partially_achieved`, or `not_achieved`. A Jira state,
   model score, or MANAS suggestion cannot issue this fact.

### Acceptance gates before any live feed claim

- Positive and negative shared fixtures validate against the pinned MANAS `0.1.0` schemas; unknown keys, missing
  bindings, wrong tenant, stale version, duplicate-key JSON, invalid chronology, and cross-thread refs fail closed.
- Retrying or replaying the same committed outbox event produces the same event ID and graph result; source history is
  never rewritten.
- An end-to-end conformance case resolves requirement version → CleanCore proposal/review/test → BasisPilot
  transport/deployment → IntakePilot outcome using exact refs and temporal evidence only.
- DLP, tenant-isolation, authorization, retention, restriction, dead-letter, recovery, and source-versus-MANAS receipt
  reconciliation tests pass before the exporter is enabled.
- The sponsor accepts the fixed question catalog and pilot entry criteria; later question changes are a new catalog
  version and cannot retroactively improve a score.

**Current truth:** these two MANAS consumers and a redacted conformance thread exist in the MANAS repository. This
IntakePilot checkout still has no merged native producer, transactional outbox, pinned live route, sponsor-accepted
pilot catalog, production receipt, or field-pilot evidence. “Contract-ready consumer” is not “deployed integration.”

## Executive decision

IntakePilot should remain the **authoritative demand and intent system**. Its current application flow preserves what the requester actually asked for, the questions and answers that clarified it, every version, provenance per field, human corrections, confirmation, routing, consent, and later delivery feedback. MANAS should consume cited observations from that history and connect them to build and runtime evidence; it must not silently rewrite IntakePilot's source record.

The target relationship is:

```text
business need
  → IntakePilot authoritative intent versions
  → governed, source-qualified events
  → MANAS evidence graph and organizational memory
  → cited recommendation proposal
  → human review in IntakePilot
  → new IntakePilot version if accepted
```

This boundary is essential. Without IntakePilot, MANAS may know that code changed or a job ran, but it cannot reliably answer **why** the work existed, what outcome the business expected, what was assumed, who corrected the interpretation, or whether the result satisfied the original need. Without MANAS, IntakePilot's history remains valuable but isolated from CleanCore Compass build evidence and BasisPilot runtime evidence.

## Why IntakePilot is needed

Meeting notes, tickets, and hand-edited requirements usually lose information at each handoff. IntakePilot addresses that problem before implementation begins:

- It retains the requester's first message as `ask_verbatim`; the ordinary turn flow records it once and does not subsequently replace it ([`core/models.py`](../core/models.py), `RequirementObject.ask_verbatim`; [`core/api/sessions.py`](../core/api/sessions.py), `_run_turn`).
- It translates plain language into a typed requirement without allowing the LLM to control workflow state ([`core/agents/orchestrator.py`](../core/agents/orchestrator.py), `Orchestrator._turn`).
- It records how each slot was obtained—`extracted`, `inferred`, `retrieved`, `answered`, `assumed`, or `edited`—and protects human-answered or edited values from machine overwrite ([`core/models.py`](../core/models.py), `Provenance`; [`core/agents/intake.py`](../core/agents/intake.py), `PROTECTED`).
- It makes ambiguity visible through question budgets, assumptions, readiness, gates, and confirmation rather than allowing an AI-generated interpretation to become source truth accidentally.
- It turns corrections and later outcomes into durable learning signals, which is the foundation for MANAS to compound reviewed organizational experience rather than merely index documents.

MANAS therefore needs IntakePilot not as a generic form or chat frontend, but as the governed provenance layer for **business intent**.

## Current capability: evidence-backed truth

The following capabilities exist in the checked-out tree today.

| Capability | Current evidence | Current limit relevant to MANAS |
|---|---|---|
| Original ask retained and application-treated as immutable | `RequirementObject.ask_verbatim`; first non-empty message is recorded once by the turn flow | This is an application invariant, not a model/database immutability constraint; the field can contain sensitive free text and has no export policy |
| Append-only requirement versions | `Store.put_version`; SQLite/Postgres primary key on `(req_id, version)` in [`core/providers/store/`](../core/providers/store/) | `req_id` is only locally unique; versions have no explicit tenant or source-instance identity |
| Field provenance and confidence | `Slot`, `Provenance`, protected human values in the orchestrator/intake merge | `Slot.source` is an untyped string, not a source-qualified evidence reference |
| Human correction capture | `edit_diffs`, `capture_edit`, confirmation and mid-session revisions | Corrections are not published as durable integration events; changed-field semantics are not externally versioned |
| Typed demand schemas | Default, bug, and data-request schemas in [`core/schemas/`](../core/schemas/) | Schema versions are not stamped onto each requirement or exported record |
| Deterministic clarification | Code-enforced question limits, gap ladder, assumptions, readiness, SSE decisions | SSE events are client updates, not a durable MANAS event stream |
| Human confirmation and quality gates | `POST .../confirm`, five gates, routing explanation, acceptance scenarios | No externally verifiable approval policy or integration receipt is attached |
| Backend-aware enrichment | `SystemConnector` and post-confirm enrichment in [`core/agents/enrichment.py`](../core/agents/enrichment.py) | Shipped connector is fixture-based; metadata can itself be confidential and is not field-classified |
| Learning ledgers | `edit_diffs`, `question_ledger`, `outcome_ledger`, `system_kb`, glossary and vector exemplars | `context_bucket = department × request_type` is learning isolation, **not tenant isolation** |
| Consent and outcome feedback | Stakeholder countersigns, reroutes, duplicate attachment, Jira delivered outcome | Outcome types are internal ledger rows, not a stable cross-product contract |
| Basic access controls | Requirement routes are session-bound; admin bearer token and optional webhook secrets exist | There is no end-user SSO or real multi-tenancy; unset secrets deliberately preserve demo posture |
| Limited public-share minimization | Public snapshots blank requester identity and expire after 30 days | The snapshot can still contain the original ask and other sensitive slots; blanking requester fields is not complete de-identification |

Useful implementation evidence is concentrated in:

- [`core/models.py`](../core/models.py): requirement, slot, provenance, confirmation, routing, and audit shapes.
- [`core/api/requirements.py`](../core/api/requirements.py): authorization, correction, consent, gates, routing, and outcomes.
- [`core/agents/orchestrator.py`](../core/agents/orchestrator.py): protected human input, decision emission, append-only turns, and learning isolation.
- [`core/learning/exemplars.py`](../core/learning/exemplars.py): corrections as human-originated learning evidence.
- [`core/agents/enrichment.py`](../core/agents/enrichment.py): backend entity discovery and human validation semantics.
- [`core/providers/store/sqlite.py`](../core/providers/store/sqlite.py) and [`postgres.py`](../core/providers/store/postgres.py): versions and ledgers.
- [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) and [`docs/DEPLOYMENT.md`](DEPLOYMENT.md): API, trust boundaries, and the explicit SSO/multi-tenancy gap.

## MANAS work found on unmerged refs

The checked-out `main` has **no MANAS exporter, event outbox, MANAS endpoint, or MANAS configuration**. However, the repository contains separate local refs based on `origin/main`:

- `pr-1-demand` (`ed897e5`, `64e2e0c`, `a4604ea`) adds a candidate metadata-only Demand exporter, flow hooks, tests, and README text.
- `pr-2-admit` (`5ff504e`) adds federation-admissibility tests for a data request.

These refs are valuable prototypes, but they must not be described as current checked-out or deployed capability. The candidate exporter should be **refined before merge**, because it currently:

- uses an unqualified `req_id` and department-based `context_bucket` instead of source-instance and tenant identities;
- omits CloudEvents `specversion`, `subject`, data schema, correlation/causation, source version, and classification/ACL fields;
- generates random event IDs and writes inline rather than using a transactional outbox, so retry, loss, duplication, and source-write atomicity are unresolved;
- marks extracted and connector-derived observations `verified=true`, which conflates “emitted successfully” with “human-reviewed evidence”;
- uses unsalted SHA-256 for free text; hashing is not anonymization and is vulnerable to guessing/linkability for predictable values;
- statically lists selected `data_request` slots rather than deriving an export policy from versioned schemas;
- provides off/list/file sinks, not an authenticated, acknowledged, replayable MANAS transport;
- has no organization-local semantic mode, so hashes alone cannot support useful intent similarity or cited reasoning inside an authorized organization.

Repository integration also needs care: checked-out `main` is currently 83 commits ahead of and 69 commits behind `origin/main`, while both prototype refs are based on `origin/main`. Port or rebase the relevant work with conflict review; do not merge either worktree blindly or assume its tests exercise the checked-out product history.

The right next step is to preserve its tests and metadata-minimization intent while replacing its envelope, identity, trust, delivery, and verification semantics with the contract below.

## Authority and ownership contract

| Information | System of record | What MANAS may do |
|---|---|---|
| Original business wording | IntakePilot | Store a permitted snapshot or source reference with citation; never edit it |
| Requirement versions and slot values | IntakePilot | Observe immutable versions and resolve them into graph nodes |
| Slot provenance, questions, assumptions, confirmations, corrections | IntakePilot | Preserve and cite them; calculate derived confidence separately |
| Demand schema and request type | IntakePilot | Validate against a declared schema version; never invent a source slot |
| Routing and stakeholder consent | IntakePilot | Link to build work and flag inconsistencies; changes return as proposals |
| Code, API, CDS, tests, review findings | CleanCore Compass | Link build evidence to the IntakePilot intent through MANAS |
| Jobs, reports, selections, plans, signals, actions, run outcomes | BasisPilot | Link runtime evidence and outcomes through MANAS |
| Cross-product entity resolution, temporal graph, citations, memory capsules, policies | MANAS | Own derived organizational memory while retaining every source reference |

MANAS-derived confidence must never overwrite IntakePilot provenance. For example, “high MANAS confidence” and “human answered” are different facts and must remain different fields.

## Target source-qualified identity

`IPR-2026-000042` is not globally unique. Every event and stored observation needs an explicit source reference:

```json
{
  "source_system": "intakepilot",
  "source_instance_id": "ip-prod-us-01",
  "tenant_id": "org_01J...",
  "entity_type": "requirement",
  "source_entity_id": "IPR-2026-000042",
  "source_version": 7,
  "schema_name": "data_request",
  "schema_version": "1.0.0"
}
```

Rules:

1. `tenant_id` is an opaque, authenticated organization identifier—not a department name supplied in a request body.
2. The canonical MANAS key is the complete tuple `(source_system, source_instance_id, tenant_id, entity_type, source_entity_id, source_version)`.
3. Department and request type may remain retrieval partitions, but never substitute for authorization tenancy.
4. `source_version` is immutable. A correction creates a later version; it does not mutate or delete the prior observation.
5. Schema name and semantic version are stamped on every exported snapshot so old events remain interpretable after schema evolution.
6. Actor references use opaque subject IDs. Names, email addresses, and department labels are exported only when explicitly allowed.

## Target event envelope

There are two distinct contracts. IntakePilot may keep a source-native domain envelope and names such as
`io.intakepilot.intent.*`, but MANAS does not admit that shape directly. The outbound adapter must deterministically
translate every source-native record to the canonical MANAS wire catalog in
`MANAS:orgbrain/docs/SOURCE_SYSTEM_FEED_CONTRACTS.md`. Alternatively, IntakePilot may emit that exact MANAS profile
from its transactional outbox. Mixing fields from the two profiles is invalid.

The following is a **source-native example**, not a MANAS-admissible wire event:

```json
{
  "specversion": "1.0",
  "id": "evt_derived_from_source_ref_and_event_type",
  "source": "urn:intakepilot:ip-prod-us-01:org_01J...",
  "subject": "requirement/IPR-2026-000042/version/7",
  "type": "io.intakepilot.intent.confirmed.v1",
  "time": "2026-08-22T17:45:00Z",
  "datacontenttype": "application/json",
  "dataschema": "https://schemas.example.org/intakepilot/intent-confirmed/1.0.0",
  "correlationid": "chg_01J...",
  "causationid": "evt_01J...",
  "tenantid": "org_01J...",
  "classification": "internal",
  "data": {
    "source_ref": {
      "source_system": "intakepilot",
      "source_instance_id": "ip-prod-us-01",
      "tenant_id": "org_01J...",
      "entity_type": "requirement",
      "source_entity_id": "IPR-2026-000042",
      "source_version": 7,
      "schema_name": "data_request",
      "schema_version": "1.0.0"
    },
    "change_kind": "human_confirmation",
    "changed_fields": ["business_outcome", "success_criteria"],
    "content_digest": "sha256:...",
    "evidence_state": "human_confirmed",
    "access_policy_id": "policy_intent_internal_v1"
  }
}
```

For source-native `io.intakepilot.intent.execution_scope_confirmed.v1`—not the generic
`io.intakepilot.intent.confirmed.v1` example above—the currently implemented execution-scope mapping is exact:

| Source-native concept | Required MANAS wire value |
|---|---|
| source-native event and MANAS type | `io.intakepilot.intent.execution_scope_confirmed.v1` → `io.manas.demand.executionscope.confirmed.v1` |
| source and lobe | `//manas/demand/intakepilot`; `demand` |
| subject | canonical `scope:<source_instance>:<requirement>@v<version>:<scope_id>` |
| partition and entity refs | tenant + source-qualified requirement partition; ordered scope, requirement-version, and workload refs |
| privacy/profile fields | `tenant`, `piiscrubbed=true`, `scrubpolicy=scrub/2026.08`, `schemaversion=1.0.0`, `dataclassification=internal`, `datacategory=non-pii`, `dataschema=urn:manas:schema:io.manas.demand.executionscope.confirmed.v1:1.0.0`, and `recordedtime=confirmed_at` |
| provenance | `agent=svc:demand/intakepilot@manas-export-v1`, `activity=export.outbox`, `used=[source_binding, approval_receipt_commitment]`, and no derived refs |
| closed payload | exactly `scope_ref`, `scope_id`, `source_instance_id`, `source_binding`, `source_kind=execution_scope`, `requirement_ref`, `requirement_id`, `requirement_version`, `workload_ref`, `workload_source_binding`, `scope_status`, `acceptance_criterion_commitment`, `commitment_policy`, `approval_receipt_commitment`, `confirmation_method=human`, `confirmed_by_role`, `confirmation_policy`, `source_schema_name`, `source_schema_version`, and `confirmed_at`; no other keys |

The mapper must fail closed on any field it cannot represent exactly. A source-native ID, source URI, or privacy flag
does not automatically become its MANAS equivalent.

Exact-binding claims in this document apply to the closed requirement/change thread and the separate governed
execution-scope/workload/selection slice. Legacy MANAS Demand schemas with unqualified or name-derived identity remain
replay-compatible but need an operator trust tier and migration or quarantine before they can influence a governed
cross-product recommendation.

Event IDs must be stable for the same committed source version and event type, or the outbox must persist a generated ID in the same transaction. Replaying an outbox row must produce the same ID.

### Source-native domain catalog

These names describe IntakePilot domain facts. They are not a second MANAS wire catalog. Only a type ratified in the
canonical MANAS catalog may cross the Event Spine. At the MANAS `0.1.0` baseline, the Demand mappings implemented for
this program are `io.manas.demand.requirement.versioned.v2`,
`io.manas.demand.outcome.adjudicated.v1`, and the separate
`io.manas.demand.executionscope.confirmed.v1`; this repository does not yet produce them.

| Event | Emit only after | Purpose |
|---|---|---|
| `io.intakepilot.intent.created.v1` | Original ask and first requirement version are durably committed | Establish authoritative origin and correlation ID |
| `io.intakepilot.intent.versioned.v1` | Any semantically meaningful version commit | Preserve ordered source history and changed-field provenance |
| `io.intakepilot.intent.confirmed.v1` | Human confirmation version is committed | Mark which source version a PO/developer may treat as reviewed intent |
| `io.intakepilot.intent.execution_scope_confirmed.v1` | A PO or authorized human confirms whether execution genuinely requires full scope or bounded scope | Issue the source-qualified evidence ref MANAS must bind before classifying a BasisPilot selection as `broad_by_design` or proposing a bounded selection experiment; export only the bounded class and criterion commitment, never selection values |
| `io.intakepilot.intent.corrected.v1` | A human correction and its new version are committed | Supersede a field interpretation without erasing the earlier one |
| `io.intakepilot.intent.enriched.v1` | Backend context is committed | Link business vocabulary to permitted system/entity metadata |
| `io.intakepilot.intent.gated.v1` | Gate results are committed | Record why work was admitted or held |
| `io.intakepilot.intent.routed.v1` | Routing version and ticket reference are committed | Connect demand to the build work item |
| `io.intakepilot.intent.consent-recorded.v1` | Stakeholder verdict version is committed | Preserve approval/objection evidence |
| `io.intakepilot.intent.outcome-recorded.v1` | Delivery, reroute, duplicate, or validation outcome is committed | Close the learning loop |
| `io.intakepilot.intent.retracted.v1` | Authorized retention/retraction decision is committed | Tombstone future use while preserving required audit evidence |

Do not publish one event per transient UI delta. SSE `slot`, `decision`, and `readiness` messages remain session UX. Integration events represent committed domain facts.

## Correction and recommendation semantics

### IntakePilot → MANAS

- The original ask remains immutable.
- A field correction creates a new `source_version` and includes `supersedes_version`, `changed_fields`, change origin, actor reference, and reason when available.
- Sensitive before/after values stay in IntakePilot unless policy permits them. The event can carry field names and per-version digests while MANAS retrieves authorized content through a scoped read API.
- MANAS appends the new observation and marks earlier interpretations superseded; it does not rewrite the earlier graph evidence.

### MANAS → IntakePilot

MANAS recommendations must use a separate proposal contract, never the requirement write API:

```json
{
  "proposal_id": "mpr_01J...",
  "target_source_ref": {"...": "...", "source_version": 7},
  "expected_source_version": 7,
  "proposed_changes": [{"slot_key": "affected_systems", "operation": "add", "value_ref": "..."}],
  "reason": "Build and runtime evidence indicates an omitted dependency",
  "citations": [
    {"source_system": "cleancore-compass", "source_entity_id": "..."},
    {"source_system": "basispilot", "source_entity_id": "..."}
  ],
  "confidence": 0.86,
  "policy_id": "human-review-required"
}
```

IntakePilot validates the target schema and tenant, displays the citations, and requires an authorized human to accept or reject. Acceptance creates a normal IntakePilot version with `provenance=edited` or a future distinct `reviewed_recommendation` provenance; rejection is also recorded as an outcome. A stale `expected_source_version` must return a conflict and require MANAS to recompute against the latest source.

### Demand authority in MANAS selection analysis

BasisPilot may attest how a job, report, or CDS workload selected data; it cannot attest why the business needed that
scope. MANAS now has a local closed `io.manas.demand.executionscope.confirmed.v1` consumer and graph-backed governed wrapper.
The event issues an immutable source-qualified evidence reference, the
exact IntakePilot requirement version, a bounded status (`full_scope_required` or `bounded_scope_required`), an
acceptance-criterion and approval-receipt HMAC-form commitments, confirmation policy/version, exact workload identity/deployment binding,
and observation time. Today those HMAC-form commitments are producer assertions whose syntax is checked; MANAS does not
yet bind a tenant key ID/policy, recompute them, or verify rotation state. MANAS projects the event separately and its
graph-backed governed wrapper verifies exact graph edges and immutable receipts before supplying scope to the policy
primitive; that wrapper accepts no caller binding flags or scope status. The lower-level pure policy primitive does
accept explicit, already-trusted inputs and must not be exposed as a producer authority path. A Run event that self-declares
business scope is rejected and can never authorize `broad_by_design`. Full scope plus a narrow/expected observed
selection now produces a functional scope-conformance review rather than a false broad-by-design conclusion.

The `RequirementVersion` node in this local slice is a source-attested proxy created from the same scope event, not an
independent join to a separately admitted IntakePilot requirement-version receipt. This is consumer proof, not an
IntakePilot producer claim. The wrapper is exercised as local library/test code; it is not an ingestion hook, remote
MCP/API gate, persisted Decision, or human workflow. Successful assessments cite selection, workload, and scope events;
an abstaining result may have fewer citations because resolution stopped at the first missing or incoherent authority.
Current `main` still lacks the explicit bounded-scope control,
authenticated reviewer role, tenant/source instance, atomic requirement-version/approval/outbox commit, and operator-
authenticated route. MANAS labels the present trust `local_contract_only` until those controls exist.

## Two privacy modes—not one

### Organization-local memory mode

An authorized MANAS deployment may receive selected semantic values such as business outcome, success criteria, urgency, scope, and accepted assumptions. This is necessary for useful intent similarity, explanation, and traceability. Controls must include:

- tenant and purpose-scoped service identity;
- per-field allowlist driven by schema and `data_sensitivity`;
- encryption in transit and at rest;
- source ACL propagation and authorization at retrieval time;
- DLP/redaction before the outbox row is created;
- configurable retention and legal hold;
- audit logs for export, retrieval, proposal, acceptance, and rejection;
- no requester name, email, raw transcript, attachment, or secret by default.

### External/federated learning mode

Cross-organization export should contain only approved aggregates, vocabulary IDs, schema keys, evidence counts, or privacy-preserving digests. Raw free text, requester identity, environment identifiers, ticket bodies, custom field names, and detailed backend schemas remain out by default.

If equality matching is genuinely required, use tenant-scoped keyed HMAC with key rotation—not bare SHA-256—and document the linkability risk. For analytics, prefer minimum cohort thresholds and aggregate counts over per-request records.

Hashing free text does **not** make it anonymous. It only obscures the literal value and may still permit guessing or correlation.

## Privacy and minimization requirements

Before any production integration:

1. Add explicit classification to every schema slot: export modes allowed, sensitivity, retention class, and whether semantic content may leave IntakePilot.
2. Derive export policy from the versioned schema; do not maintain a second hard-coded slot list in exporter code.
3. Add a pre-publish scanner for secrets, credentials, email, phone, account identifiers, payment data, government IDs, and organization-specific identifiers. Pattern tests alone are insufficient; violations must block/quarantine an event.
4. Treat SAP table/CDS/API names, custom fields, system IDs, ticket references, and owner teams as potentially confidential metadata.
5. Export opaque actor and tenant IDs. Resolve display names only in the source system after authorization.
6. Do not export the complete session transcript or X-ray decision history by default.
7. Make restriction and retraction first-class events so MANAS can stop serving superseded or legally removed content.
8. Test that public shares and MANAS exports use different policy profiles. Current share redaction must not be reused as proof of federation safety.

## Recommended implementation architecture

```text
IntakePilot transaction
  ├─ append requirement version / ledger rows
  └─ append integration_outbox row (same transaction)
         ↓ async publisher
   policy + DLP gate
         ↓ signed CloudEvent
   MANAS ingest → schema/auth/idempotency checks → receipt
         ↓
   receipt/dead-letter status retained in IntakePilot

MANAS cited recommendation
         ↓
   IntakePilot proposal inbox
         ↓ authorized human decision
   new IntakePilot version + outcome event
```

Required building blocks:

- A versioned contract package containing JSON Schemas, examples, compatibility tests, and a changelog.
- A transactional outbox supported by both SQLite and Postgres stores.
- A publisher protocol with authenticated HTTPS first; Kafka/NATS adapters can come later without changing domain semantics.
- HMAC or asymmetric event signing, timestamp/replay-window checks, tenant-scoped credentials, and key rotation.
- MANAS receipts containing event ID, accepted schema version, ingest time, and rejection reason.
- Idempotent replay and a dead-letter queue; source request latency must not depend on MANAS availability.
- A scoped read API for content that policy does not allow in event payloads.
- A proposal inbox with optimistic concurrency and mandatory human review.

## Phased backlog with acceptance criteria

### P0 — truth, identity, policy, and contract (must precede runtime export)

- Define `tenant_id`, `source_instance_id`, source reference, schema version, event envelope, event catalog, and evidence-state vocabulary.
- Add slot-level export classification to all request schemas.
- Decide organization-local versus federation profiles and document their field allowlists.
- Rework the `pr-1-demand` prototype against this contract; keep useful minimization/admissibility fixtures from both local refs.
- Add architecture decision records for authority, corrections, retention, and proposal review.
- Define the tenant key/policy registry for Demand commitments: key ID/version, allowed purpose, rotation/retirement,
  recomputation/verification, and negative cross-tenant tests. HMAC-shaped text alone is not verification.

**Acceptance criteria**

- 100% of contract examples validate against checked-in JSON Schemas.
- No event can validate without tenant, source instance, source entity, source version, schema version, classification, and access-policy ID.
- Golden compatibility tests prove a v1 consumer can read all v1.x producer events.
- Security review explicitly approves both export profiles and their field lists.

### P0 — real identity and tenant isolation

- Derive requester and tenant from OIDC/service claims, not request JSON.
- Enforce tenant filtering in stores, vector metadata, ledgers, sessions, admin APIs, shares, connector results, and integration outbox.
- Replace the single global admin token for production with role/scoped service authorization while retaining demo mode only behind an explicit flag.

**Acceptance criteria**

- Cross-tenant read, search, event replay, share, connector, and proposal tests all fail closed.
- Every persisted requirement, ledger row, vector record, event, and receipt carries the same authenticated tenant.
- A test suite with at least two tenants proves zero search or learning leakage in 1,000 mixed records.

### P1 — transactional outbound feed

- Add `integration_outbox` and atomic writes with committed requirement versions.
- Publish asynchronously with stable IDs, retry/backoff, signing, receipts, and dead-letter handling.
- Emit the minimum catalog at committed domain boundaries, not inline before persistence.
- Emit confirmed execution scope as a separate source-issued demand fact; never copy a BasisPilot runtime label into demand authority.
- Match MANAS's closed v1 contract exactly: requirement version, workload ref and deployment binding, two-value scope
  status, criterion/approval HMAC-form commitments, bounded human role and policy/schema metadata, and confirmation time; no raw prose.
- Establish a pre-run identity handoff. BasisPilot/SAP scheduling or another registered Run authority allocates the
  immutable future `workload_ref`, `workload_source_binding`, and intended observation window before execution. MANAS may
  validate and relay that attestation but may not originate it. IntakePilot presents those exact refs to the authorized
  business reviewer and atomically commits the requirement version, approval receipt, scope confirmation, and outbox row
  with `confirmed_at <= window_start`. The later Basis observation must reuse the same ref/binding; until it arrives,
  MANAS retains the scope event as a pending dependency and does not manufacture a workload.
- Add replay tooling by tenant, time range, requirement, and event type.

**Acceptance criteria**

- Failure injection between source commit, publish, receipt, and retry produces no lost committed events and no duplicate effect in MANAS.
- Replaying the same 10,000 outbox rows yields one MANAS observation per event ID.
- A conformance test proves that only an exact admitted IntakePilot scope receipt and scope-to-workload edge—not a
  BasisPilot assertion or caller boolean—can satisfy the business-scope condition in MANAS's graph-backed governed assessment.
- A chronology test rejects a scope confirmed after the planned workload starts, a Basis observation that changes the
  pre-issued workload ref/binding, and a cross-tenant or unregistered handoff.
- MANAS downtime adds no more than 5% to IntakePilot request p95 latency.
- After recovery, 99% of eligible events are acknowledged within 60 seconds; every remainder is visible with a reason.

### P1 — minimization and content access

- Implement schema-derived allowlists, DLP/quarantine, semantic versus digest profiles, and source ACL propagation.
- Add a tenant-scoped read endpoint for explicitly permitted snapshots and version history.
- Provide restriction/retraction and retention jobs with auditable MANAS acknowledgement.

**Acceptance criteria**

- A seeded corpus containing credentials, PII, payment/account data, and system identifiers produces zero forbidden fields in published events.
- Restricted records cannot be fetched using an otherwise valid service identity lacking the required purpose/scope.
- Retraction tests make content unavailable from MANAS retrieval while retaining the required non-content audit tombstone.

### P2 — cited recommendation return path

- Add proposal create/list/review endpoints or queue, optimistic concurrency, schema validation, citation validation, and an IntakePilot review surface.
- Record accept/reject decisions and emit them as outcomes.
- Never auto-apply a MANAS proposal to an authoritative slot.

**Acceptance criteria**

- A proposal with missing citations, wrong tenant, invalid slot, or stale source version is rejected.
- 100% of accepted proposals identify the human reviewer and create a new append-only IntakePilot version.
- Tests prove MANAS service credentials cannot call authoritative mutation paths directly.

### P3 — complete demand → build → run → learning trace

- Carry MANAS correlation IDs into routed work items.
- Accept source-qualified CleanCore Compass build references and BasisPilot run/outcome references through MANAS proposals or link records.
- Show the PO/developer the trace from original need to reviewed change, runtime evidence, outcome, and later correction.
- Feed adjudicated outcomes—not raw model suggestions—into IntakePilot replay evals and glossary/precedent learning.

**Acceptance criteria**

- A golden scenario resolves one business need to at least one reviewed build artifact and one runtime outcome with no ambiguous identifier.
- Every displayed recommendation has at least one accessible citation and its source version.
- Removing either source permission makes the dependent citation unavailable rather than leaking cached content.
- Human rejection prevents the recommendation from entering promoted learning.

### P4 — production operations and open-source readiness

- Add SLO dashboards for outbox age, publish success, rejection reason, receipt latency, dead letters, schema compatibility, DLP blocks, and proposal disposition.
- Document deployment profiles, key rotation, backup/restore, disaster replay, migrations, retention, and incident response.
- Ship a conformance kit so an organization can connect its own MANAS without adopting a specific broker or AI provider.

**Acceptance criteria**

- Backup/restore plus outbox replay reconstructs the same MANAS state in a clean environment.
- A key-rotation drill completes without event loss or accepting expired signatures.
- A second reference implementation passes the same producer/consumer conformance suite.

## Product metrics

Measure whether the integration improves work rather than merely moving data:

- percentage of routed requirements with an unbroken intent → build → run trace;
- clarification questions, confirmation edits, and reroutes per request over time;
- percentage of MANAS proposals accepted, rejected, or stale, by cited evidence type;
- time from business ask to developer-ready confirmed intent;
- time from confirmed intent to reviewed build and first runtime evidence;
- percentage of source fields whose displayed MANAS answer includes a valid citation;
- event delivery/receipt SLO, DLP block rate, dead-letter age, and cross-tenant violations (target: zero);
- outcome coverage: requirements with a measured result versus only a delivery status.

Do not optimize for “number of events” or “number of AI recommendations.” Those are activity counts, not organizational learning.

## Non-goals

- MANAS does not replace IntakePilot, its UX, question loop, human confirmation, or authoritative version history.
- IntakePilot does not become a code generator; CleanCore Compass owns build-time analysis and reviewed change evidence.
- IntakePilot does not become a runtime monitor; BasisPilot owns system/run evidence and operational recommendations.
- MANAS does not directly edit requirements, route work, approve stakeholders, merge code, transport SAP changes, or change production.
- The integration does not export business row data, secrets, full transcripts, or unrestricted personal information.
- A generic vector database is not the source of truth; embeddings are derived indexes that can be rebuilt from governed source versions.
- “Open source” does not mean “open organizational data.” Code and contracts may be public while every organization's evidence remains private and policy controlled.
- The existence of prototype commits is not proof that the integration is complete, merged, deployed, or production-safe.

## Definition of done

IntakePilot is ready to feed MANAS when all of the following are true:

- source-qualified tenant identity is enforced end to end;
- versioned event schemas and authority rules are published;
- source commit and outbox write are atomic;
- delivery is authenticated, acknowledged, replayable, observable, and idempotent;
- privacy profiles and DLP controls are tested with adversarial fixtures;
- MANAS stores cited immutable observations and never overwrites IntakePilot source truth;
- recommendations return only as cited, version-checked, human-reviewed proposals;
- a golden demand → CleanCore Compass → BasisPilot → reviewed outcome trace passes conformance tests;
- documentation states current versus target capability without implying that a prototype or fixture connector is a live production integration.
