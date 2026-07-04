# IntakePilot

AI requirements-intake platform: a business user describes a need in plain
language; a deterministic orchestrator (LLM as component, never in control)
extracts structured requirement slots, resolves gaps by inference and
precedent before ever asking a question, enforces a hard question budget,
and — after human confirmation — runs a five-gate quality pipeline, routes the
requirement to the right team queue with an explanation, and creates a ticket.
Every human correction feeds a learning ledger that improves the next intake.

Built from `docs/build-specification.txt` (v1.0) plus
`docs/ADDENDUM-01-backend-aware-enrichment.md`. See `docs/SPEC-REVIEW.md`
for an honest review of the spec and the choices made where it was silent.

## The five-minute first run

Zero external dependencies — no model, no Docker, no database:

```bash
git clone <repo> && cd intakepilot
make dev            # backend :8000 (mock LLM + SQLite) and web :3000
open http://localhost:3000/loop
# type: "our monthly vendor report takes 3 days to compile by hand"
# watch the Shadow Draft build, answer <= 3 questions, confirm,
# see the ticket appear in examples/demo-repo/
#
# Note: run the SAME ask twice and gate 4 will (correctly) catch the second
# as a near-duplicate of the first — click "Attach to IPR-…" to see the
# dedup flow, reword the ask, or `make clean` to reset the demo database.
```

Or run the pieces separately:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn core.api.main:app --port 8000     # backend
cd web && npm install && npm run dev                # frontend on :3000
.venv/bin/python -m pytest -q                       # tests
```

Full stack per the spec (Postgres/pgvector + Ollama + api + web):

```bash
cd deploy && docker compose up
docker compose exec ollama ollama pull llama3.1     # first start only
```

Production deployment — on-premises, air-gapped, or any cloud — uses
`deploy/docker-compose.prod.yml` (built web bundle behind nginx, env-driven
secrets, non-root API, bring-your-own LLM endpoint). Every path is documented
in `docs/DEPLOYMENT.md`; the system design lives in `docs/ARCHITECTURE.md`.

Providers are selected in `intakepilot.yaml` and can be overridden with env
vars: `INTAKEPILOT_LLM=mock|ollama|openai_compat`,
`INTAKEPILOT_STORE=sqlite|postgres`, `INTAKEPILOT_VECTOR=local|pgvector`.
Any OpenAI-compatible endpoint works via `OPENAI_BASE_URL`/`OPENAI_MODEL`.
Setting `DATABASE_URL` switches the store to Postgres automatically.

**Hybrid model strategy:** set `INTAKEPILOT_LLM_ESCALATION` to give the
intake a second, stronger model (cloud frontier or bigger internal) that
answers only when the primary fails structured-output validation twice —
local-first economics with frontier-grade interpretation on the hard turns.
Escalations taper off as the learning ledger accumulates exemplars from
daily usage. Embeddings always stay on the primary.

## Demo via curl (no UI needed)

```bash
SID=$(curl -s -X POST localhost:8000/api/sessions -H 'content-type: application/json' \
  -d '{"requester":{"name":"Demo","dept":"Finance Ops","role":"Analyst"}}' | python3 -c 'import sys,json; print(json.load(sys.stdin)["session_id"])')
curl -s -X POST "localhost:8000/api/sessions/$SID/turns?stream=false" \
  -H 'content-type: application/json' \
  -d '{"message":"our monthly vendor report takes 3 days to compile by hand"}'
# ... answer the returned questions, then confirm. Requirements are bound to
# the session that created them (IDs are sequential, so this stops enumeration):
#   curl -X POST localhost:8000/api/requirements/{req_id}/confirm \
#     -H "X-Session-Id: $SID" -H 'content-type: application/json' -d '{"edits":{}}'
```

## Architecture in one paragraph

`core/` is a FastAPI app. Three provider protocols (`LLMProvider`, `Store`,
`VectorIndex`) are the portability contract — no business logic imports a
provider SDK (enforced by a test). The orchestrator
(`core/agents/orchestrator.py`) is the spec's Section 6.1 loop: extract →
merge (ANSWERED/EDITED are never overwritten) → gap ladder (infer from
requester context, retrieve from glossary/precedent) → budgeted questions
(max 3/turn, 7 total, enforced in code) → stated-default assumptions →
readiness score → append-only version write. Confirmation captures every
human edit as an `edit_diffs` row (the learning asset) which
`core/learning/exemplars.py` injects into future extraction prompts —
model-agnostic learning. Gates 1/3 are deterministic pure functions; gates
2/4/5 use the LLM as a scored rubric behind one validate-and-retry wrapper.
The routing classifier is keyword-based with a confidence and a
human-readable explanation (embedding-assisted scoring is on the roadmap). `web/` is a React + TypeScript + Vite app that
consumes the SSE turn stream to animate the Shadow Draft live.

## Backend-aware enrichment and the system knowledge base

Business users never need to know backend details (ADDENDUM-01). After a
requirement is confirmed — and before gates/routing — an enrichment step
(`core/agents/enrichment.py`) resolves the business terms in the ask through
the glossary and a `SystemConnector` provider
(`core/providers/connector/`, protocol: `resolve_entity` /
`describe_entity` / `list_customizations`). The shipped `fixture` connector
reads YAML system definitions from `core/schemas/systems/` — an example SAP
S/4HANA system (sales orders `VBAK/VBAP` with Z-fields like
`ZZ_PRIORITY_CODE`, material master `MARA` with append fields) and a non-SAP
Postgres fulfillment DB with custom columns.

What the enrichment produces:

- A `backend_context` slot (provenance `retrieved`, `askable: false` — the
  Question Composer can never ask the requester about backend detail; an
  invariant test enforces it) holding the matched entities, their backend
  names, and every customization with type, description, and owner.
- A **System context (auto-discovered)** section on the routed ticket, so
  the assigned team sees e.g. `ZZ_PRIORITY_CODE` without re-interrogating
  the requester — try the ask *"I need a report of goods details for product
  line X with the order info"*.
- Rows in the `system_kb` ledger (entity schema, `evidence_count`,
  `verified`, `last_refreshed`, embedded into the vector index). The
  retrieval ladder reads `system_kb` on later intakes, so affected systems
  and backend context are pre-filled from cached discoveries; discoveries
  start `unverified` and are promoted via `mark_validated` when a human
  confirms them. `/api/metrics` reports entity/customization/verified counts.

Swap the fixture for a real connector (SAP OData/RFC, database catalog) by
implementing the three-method protocol and pointing `intakepilot.yaml`
(`connector:` / `connectors:`) at it.

## Theming

The UI follows `docs/DESIGN-GUIDELINES.md`: every color flows through
semantic CSS custom properties in `web/src/styles.css`, with first-class
**dark and light themes** selected by `html[data-theme]`. The header toggle
persists the choice to `localStorage`; the default follows the OS
`prefers-color-scheme` (applied pre-paint by an inline script in
`web/index.html`, so there is no flash). Accents are teal/cyan — no
purple/violet/indigo anywhere — with amber for warnings, red for failures,
green for success, and a distinct badge color per provenance value.

## What's implemented vs. spec'd for later

Implemented and verified (spec milestones 1–5 core, plus gates/routing from 6):

- Pydantic model per spec 4.1; slot schema loader with the `askable:false` rule (4.2)
- Providers: mock (deterministic, offline), Ollama, OpenAI-compatible, plus
  an optional escalation tier (`EscalatingLLM`: a stronger model answers
  validation-failed turns — the hybrid local/cloud strategy); SQLite
  (default) and Postgres (4.3 DDL) stores, both append-only; local cosine
  vector index and pgvector
- The full 6.1 turn loop with SSE streaming, budget enforcement, gap ladder,
  defaults with reasons, readiness scoring (rubric documented in
  `core/agents/orchestrator.py` — the spec omits one)
- Confirmation with edit-diff capture, exemplar selection/injection (7.2)
- Five-gate pipeline (1 & 3 deterministic; 2/4/5 LLM-rubric), routing
  classifier with explanation, local ticket target writing to
  `examples/demo-repo/` (a GitHub target exists in code but is not yet
  wired into config — see PROJECT-REVIEW.md)
- `/api/metrics` computing Section 9 metrics from the ledgers (plus
  system-KB counts, escalation rate, duplicate catch rate, and routing
  accuracy from reroute ground truth)
- The learning & feedback surface: gate 4 checks real known work (vector
  candidates + deterministic near-duplicate fail) with one-click
  attach-as-duplicate; routing blends keyword and precedent signals and
  learns from reroutes (`POST /api/requirements/{id}/reroute`, GitHub
  webhook); question ranking and readiness weights calibrate from the
  ledgers; corrections replay as evals (`GET /api/evals/replay`); repeated
  corrections surface as glossary proposals (`GET /api/glossary/proposals`,
  human-accepted via `POST /api/glossary`); system-KB validation via
  `POST /api/kb/{system}/{entity}/validate`
- ADDENDUM-01 backend-aware enrichment: `SystemConnector` protocol + fixture
  connector, post-confirm enrichment agent, `system_kb` ledger feeding the
  retrieval ladder, System-context section on routed tickets and in the
  confirm/post-confirm UI
- Web UI: chat with streaming + question chips + budget meter, live Shadow
  Draft with provenance badges and confidence bars, readiness ring, confirm
  view with inline edits and assumption register, gate/routing/ticket results,
  metrics dashboard — all themed dark/light via semantic tokens
- Tests for the Section 11 invariants plus the ADDENDUM-01 invariants and
  acceptance scenario (`tests/`)

Spec'd for later (honest gaps):

- Milestone 6 remainder: triage queue UI, GitHub webhook status sync
- Milestone 7: eval harness over a 40-scenario golden set (scenario #1 ships
  in `evals/golden/` and runs as a pytest), nightly distillation jobs,
  `prompt_configs` promotion gate
- Milestone 8: precedent backfill from targets, clone-and-modify UX, glossary
  importer CLI (a seed glossary ships for the demo)
- Milestones 9–10: Bedrock/DynamoDB/Bedrock-KB providers, SAM template,
  Builder Agent
- Auth/multi-tenancy, webhook signatures, migrations — see `docs/SPEC-REVIEW.md`

## Repo layout

Matches spec Section 3: `core/` (api, agents+prompts, gates, learning,
providers/{llm,store,vector}, targets, models.py, config.py), `web/`,
`deploy/` (docker-compose + Dockerfiles), `evals/golden/`, `docs/`,
`examples/demo-repo/`.
