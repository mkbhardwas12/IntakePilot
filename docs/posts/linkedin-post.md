# LinkedIn Post

*(Attach `docs/assets/intakepilot-thumbnail.png` first as the labeled main thumbnail. Attach `docs/assets/architecture.png` second for the technical audience. The clean unlabeled artwork is preserved at `docs/assets/intakepilot-thumbnail-clean.png` if you want a quieter variant later. After the Medium article is published, replace `[Medium link]` with the real URL.)*

---

I just shipped a hardening pass for IntakePilot, my open-source AI requirements-intake platform.

The problem it is built for is painfully familiar in enterprise IT: a business user says what they need in plain language, a BA translates it, functional teams interpret it, developers interpret it again, and the requirement quietly changes shape every time it moves.

IntakePilot keeps that first conversation alive as structured evidence.

A requester can type:

> our monthly vendor report takes 3 days to compile by hand

The system builds a live Shadow Draft, asks only the missing business questions, runs quality gates after confirmation, enriches the ask with backend context, and routes a code-ready requirement with a written explanation.

The design rule is simple:

**The LLM proposes. Deterministic code decides.**

Architecture, in practical terms:

- React + TypeScript UI streams the intake loop with Server-Sent Events.
- FastAPI orchestrator owns the extract -> merge -> gap analysis -> budgeted questions -> readiness -> confirm flow.
- Provider protocols isolate the model, store, vector index, system connector, and ticket target.
- SQLite/mock mode runs locally in minutes; Postgres + pgvector + Ollama runs as the full local stack.
- Backend-aware enrichment resolves business terms to real system context, including SAP-style tables, custom fields, and owner metadata.
- Ledgers capture edits, questions, outcomes, reroutes, glossary proposals, and eval replay data.
- Five gates check schema quality, INVEST quality, ambiguity, duplicates, and routing sanity.

This latest pass tightened the parts that matter before real usage:

- schema-fork-aware eval replay, so bug reports and data requests are tested against their own slot schemas
- frontend schema loading per request type
- admin protection for metrics when an admin token is configured
- cleaner local-LLM production compose defaults
- dev/runtime dependency split
- Vite upgrade with a clean audit
- better test isolation

Verified:

- 117 backend tests passing
- TypeScript check passing
- production frontend build passing
- npm audit: 0 vulnerabilities
- pip check clean
- dev and prod Docker Compose configs valid
- end-to-end HTTP ops check: 31/31 checks passed

The repo includes the architecture diagram, workflow diagram, local demo, Docker deployment path, and the exact tests that pin the invariants.

GitHub: https://github.com/mkbhardwas12/IntakePilot
Longer architecture write-up: [Medium link]

If your intake process has different gates, schemas, or routing rules, that is the point: the core is meant to be forked around real enterprise workflows, not one generic template.

#EnterpriseAI #OpenSource #SAP #LocalLLM #AIArchitecture #SoftwareEngineering
