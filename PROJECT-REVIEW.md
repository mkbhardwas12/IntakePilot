# Project Review — 2026-07-03

Deep review of the full codebase (backend, frontend, deploy, docs, tests), plus verification that the project runs. Nine issues were fixed directly; the rest are catalogued below by priority.

## Verification results

| Check | Result |
|---|---|
| `pytest` (30 tests, incl. invariant + e2e suites) | 30/30 pass |
| `npm run build` (tsc + vite) | clean |
| API smoke test (session → turn → answers → confirm) | routed, all 5 gates pass |
| Double-confirm | 409 (was: 500 + side effects) |
| Unsolicited answer injection | rejected (was: accepted) |

**Verdict: the default path (mock LLM + SQLite + local vector) is ready to use.** The docker-compose "full stack" path had two startup-blocking bugs — both fixed, but untested against a live Postgres/Ollama here; run `cd deploy && docker compose up` once to confirm. Not ready for multi-user/production use (no auth — see below).

## Fixed in this review

1. **Postgres store crashed the docker stack at startup** — callers pass ISO strings and 0/1 ints where asyncpg requires `datetime`/`bool` (`TIMESTAMPTZ`/`BOOL` columns). Glossary seeding in the app lifespan raised, so the API never booted with `DATABASE_URL` set. Coercion added in `core/providers/store/postgres.py` (`_coerce`).
2. **Dockerized web UI couldn't reach the API** — vite proxied to `localhost:8000`, which inside the container is the web container itself. `web/vite.config.ts` now honors `INTAKEPILOT_API_URL`; compose sets it to `http://api:8000`. Added `web/.dockerignore` so `COPY . .` no longer clobbers container `node_modules` with macOS-native binaries.
3. **Confirm raced turns and itself** — ticket was created *before* the version write, so a concurrent confirm produced a duplicate ticket then a 500. Confirm now runs under the same per-requirement lock as turns (`Orchestrator.lock_for`), with the first-message `ask_verbatim` write moved under it too (`core/api/requirements.py`, `core/api/sessions.py`).
4. **Frontend re-POSTed failed turns** — any stream hiccup re-submitted the whole turn, double-spending question budget and duplicating versions; server SSE `error` events were silently ignored. `web/src/api.ts` now surfaces server errors and recovers broken streams via `GET /api/sessions/{id}` (the recovery contract SPEC-REVIEW.md documents) instead of replaying the POST.
5. **Gate 3 regex mis-grouped** — `\bjanuary|...|december\b` bound the anchors to only the first/last month, so "may" inside any word counted as a concrete anchor and disabled the ambiguity lint ("maybe improve things somehow" passed). Fixed grouping in `core/gates/pipeline.py`.
6. **Routing explanation collapsed to "."** with a single configured queue (ternary precedence bug in `core/gates/routing.py`).
7. **Arbitrary slot injection** — an "answer" with a bogus `question_id` wrote any schema slot (including `askable:false` ones like `backend_context`) with ANSWERED provenance and inflated question metrics. The orchestrator now only accepts answers matching pending question IDs and takes the slot key from the question, not the client.
8. **Confirm edits corrupted typed slots** — editing a list-valued slot in the UI replaced the array with one comma-joined string. `_coerce_edit` in `core/api/requirements.py` restores list/number/bool types from the string edit.
9. Smaller fixes: SSE client disconnect no longer cancels a turn mid-write (state stayed half-committed); UI no longer hardcodes readiness ≥ 70, so `confirm_threshold` in `intakepilot.yaml` is actually respected; React StrictMode no longer creates an orphan backend session per dev page load; `.gitignore` now covers the scratch `uiverify`/`.uiverify`/`.ui-verify` dirs, the stray root `package-lock.json`, `.env`, and `*.log`.

## Remaining — high priority

**No authentication on any endpoint.** Confirm triggers file writes (and GitHub API calls if wired); `/api/metrics` and `GET /api/requirements/{id}` expose all intake content. README lists auth as future work, but even a shared bearer-token dependency on the routers would help before exposing beyond localhost. Related: `make dev` binds uvicorn to `0.0.0.0` — change to `127.0.0.1` for local runs.

**Blocking I/O on the event loop.** Every SQLite call and each full-file rewrite of the local vector index (`core/providers/vector/local.py`, rewritten on *every* upsert) runs synchronously inside async handlers, stalling all concurrent SSE streams. Wrap store calls in `asyncio.to_thread` (or aiosqlite) and persist the vector index atomically (temp file + rename) with a corruption fallback — today a corrupt index JSON bricks startup.

**No Postgres/pgvector test coverage.** Fix #1 shipped precisely because nothing exercises `PostgresStore`/`PgVectorIndex`. Add a CI job running the e2e suite against real Postgres.

**GitHub target is dead code but README claims it's implemented.** `core/targets/github.py` is never wired — `AppContext` hardcodes `LocalTarget` and no `target:` config key exists. Add a target factory or correct the README.

## Remaining — medium

Ticket creation still precedes the version write inside the (now-locked) confirm, so a store failure after ticket creation can orphan a ticket — consider persisting first or writing two versions. Lazy pool init in both asyncpg providers can double-create pools under concurrent first requests (guard with a lock). `next_seq` on SQLite is racy across *processes* (use `UPDATE ... RETURNING`). LLM JSON parsing does a bare `json.loads` — code-fence-tolerant parsing would help with OpenAI-compatible gateways that ignore `response_format`. `_validate` accepts booleans as numbers (`isinstance(True, int)`), giving a model `confidence: true` → 1.0. Enrichment can silently mutate a human-EDITED `affected_systems` after confirmation. Malformed `requester` bodies 500 instead of 422 (type it as `Requester | None`). Hardcoded Postgres credentials in compose; API container runs as root; `Dockerfile.web` still ships the vite dev server rather than a built bundle behind nginx.

## Remaining — low / polish

Frontend: no AbortController on the turn stream (navigating away leaves it running); confirm modal lacks focus trap and Escape *commits* instead of reverting; chat has no `aria-live`; "View raw" on the ticket card shows the path twice (API never returns ticket content); health badge checked once, never re-polled; TopBar logo hardcodes hex despite the design rule (use `var(--accent)`); theme toggle can desync when the OS theme changes; build script should be `tsc -b`; no ESLint despite an `eslint-disable` comment; no frontend tests (the SSE parser in `api.ts` most deserves them). Backend: duplicate SSE `slot` events per turn; dead code (`initTheme`, unused API helpers, `ask_embedding` column never written, `select_exemplars(agent=)` unused, unbounded `_locks` dict); `requirements.txt` duplicates `pyproject.toml` deps and bundles pytest into runtime installs. Evals: `evals/golden/scenario_001.yaml` isn't machine-consumed — `test_e2e.py` hand-duplicates it, so the YAML can drift.

## Repo cruft (safe to delete by hand)

`uiverify/` (includes 1.7 MB of vendored `websockets`), `.uiverify/`, `.ui-verify/` — three iterations of the same scratch screenshot tool, referenced by nothing; the empty stub `package-lock.json` at the repo root (the real one is `web/package-lock.json`). All are now gitignored, so they won't pollute a future `git init` either way. Note the project is not yet a git repo.

## What's genuinely good

The core architectural claims hold up under adversarial reading: the question budget, askable-filter, append-only versioning, and ANSWERED/EDITED protection are enforced in code *and* by genuinely adversarial tests (`RogueLLM`); no business logic imports a provider SDK (enforced by a lint test); SQL is parameterized, YAML loads are safe, all HTTP calls have timeouts; the frontend is strict TypeScript with zero `any`, no XSS vectors, and the theming system actually follows its own design rules. The docs are unusually honest — nearly every README claim checked out against the code.
