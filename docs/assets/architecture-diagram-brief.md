# Diagram brief — IntakePilot System Architecture (Drawing 02)

Instructions for recreating the architecture diagram in any tool
(Figma, draw.io, Lucidchart, Illustrator, or an AI image tool).
All box text below is verified against the codebase — copy it exactly.
Change styling freely; do not change wording without re-checking accuracy
(see "Accuracy rules" at the end).

---

## 1. Purpose and audience

One picture that shows: clients on top, a deterministic core in the middle,
provider protocols as the only door out, ledgers/learning at the bottom,
and one learning-feedback return. Audience: architects and technical
decision-makers. Tone: engineering drawing, not marketing graphic.

## 2. Canvas

- Landscape, ratio ~16:10 (reference: 2560 × 1560 px). Export PNG and SVG.
- White background. No gradients, no shadows heavier than subtle, no 3D.

## 3. Style tokens

| Token | Hex | Used for |
|---|---|---|
| Ink | #1E293B | titles, box borders, main connectors |
| Body text | #475569 | box body copy |
| Faint | #94A3B8 | layer labels, footer |
| Rule | #CBD5E1 | thin secondary rules |
| Band tint | #F8FAFC | alternating layer backgrounds (layers 2 & 4) |
| Teal accent | #0F766E | exactly two highlighted boxes (Orchestrator, LLMProvider) |
| Amber accent | #B45309 | ONLY the learning-return line + Learning Loops title |

Typography: one clean sans (Inter/Söhne/Helvetica). Box titles bold,
UPPERCASE, ~18 pt equivalent; body regular ~15 pt; connector labels in a
monospace ~14 pt. Line weights: box borders 2 px, connectors 2–3 px.

Rules: orthogonal connectors only (no diagonals, no curves), small closed
arrowheads, generous white space, everything on a strict grid.

## 4. Header

Title (bold, uppercase):
`SYSTEM ARCHITECTURE — DETERMINISTIC CORE, LLM AS A COMPONENT`

Subtitle (regular, one line):
`Layered view. Every outbound dependency sits behind a provider protocol; business logic imports no SDK (a test fails the build if it does).`

Below the subtitle: a full-width double rule (2 px ink + 1 px light).

## 5. Layers (4 full-width horizontal bands, top to bottom)

Each band: thin ink border; small uppercase label in Faint at top-left
inside the band. Bands 2 and 4 get the #F8FAFC tint; 1 and 3 stay white.

### LAYER 1 — CLIENTS  (3 equal boxes)

| Box title | Body (line breaks as shown) |
|---|---|
| WEB UI | React + TypeScript + Vite / live Shadow Draft over SSE, / provenance badges, readiness ring |
| API CLIENTS | plain-JSON turn endpoint / for scripts and integrations / (requirements are session-bound) |
| CHAT CHANNELS | Slack / Teams bots call one / inbound endpoint; numbered answers, / 'confirm' completes the flow |

### LAYER 2 — DETERMINISTIC CORE (FASTAPI)  (5 equal boxes)

| Box title | Body |
|---|---|
| TYPING + SCHEMA FORKS | keyword classifier on turn 1: / bug / data / new capability; / per-type slot schemas, / learning buckets are dept × type |
| ORCHESTRATOR (6.1) — **teal title** | extract → merge (human input / never overwritten) → infer → / retrieve → 3–9 budgeted questions / → defaults → readiness → append |
| CONFIRM + EDIT DIFFS | every human correction is / captured with its provenance — / the learning asset; / shakiest slots reviewed first |
| ENRICHMENT | resolves business terms to / backend entities + customizations / after confirm — the requester / is never asked |
| GATES 1–5 + ROUTER | duplicate + portfolio collision / checks vs open work (one-click / attach); keyword + precedent / routing, learns from reroutes |

### LAYER 3 — PROVIDER PROTOCOLS · THE ONLY DOOR OUT  (5 equal boxes)

| Box title | Body |
|---|---|
| LLMProvider — **teal title** | mock · Ollama (local) · any / OpenAI-compatible endpoint; / optional escalation tier for / validation-failed turns |
| Store | SQLite (zero-dep default) / Postgres (spec DDL); / versions append-only |
| VectorIndex | local cosine index (atomic / persistence) · pgvector |
| SystemConnector | SAP S/4HANA fixture / (VBAK/VBAP, Z-fields); / swap in OData / RFC / / DB-catalog connectors |
| Target | local repo · GitHub issues / (config switch); / Jira / ADO: same one-class / protocol, roadmap |

Note: `LLMProvider`, `VectorIndex`, `SystemConnector` are the literal
Python protocol class names — keep them unspaced on purpose.

### LAYER 4 — LEDGERS, LEARNING & OPS  (3 equal boxes)

| Box title | Body |
|---|---|
| LEDGERS | requirement versions (append-only) / edit_diffs · question_ledger / outcome_ledger · glossary / system_kb (verified discoveries) |
| LEARNING LOOPS — **amber title** | edits → prompt exemplars + weights / question outcomes → asking order / reroutes → routing precedent / corrections → replayable evals / repeat edits → glossary proposals |
| OPS & SECURITY | /api/metrics incl. backlog by value / /api/graph: collision hotspots / /api/evals/replay (correction-derived) / admin bearer token · webhook HMAC |

## 6. Connectors (exactly four — no more)

All vertical, orthogonal, ink-colored, labeled in monospace beside the line:

1. Layer 1 → Layer 2, label: `REST + SSE · SESSION-BOUND`
2. Layer 2 → Layer 3, label: `PROTOCOL CALLS ONLY — SDK IMPORTS IN BUSINESS LOGIC FAIL THE BUILD`
3. Layer 3 → Layer 4, label: `APPEND-ONLY WRITES · DISCOVERIES · OUTCOMES`
4. **The amber return** (the only amber line): from the Layer-4 area, up the
   right margin, arrowhead pointing into the GATES 1–5 + ROUTER box (Layer 2).
   Rotated or horizontal label: `LEARNING SIGNALS RETURN TO THE CORE`

Do NOT draw box-to-box arrows between individual boxes across layers —
that's the arrow spaghetti we're avoiding. Layer-to-layer only.

## 7. Notes panel (bottom-left)

Small "NOTES" heading with underline, then:

```
1. INVARIANTS PINNED BY ADVERSARIAL TESTS (100+): QUESTION BUDGET, ASKABLE:FALSE FILTER, APPEND-ONLY
   VERSIONS, ANSWERED/EDITED NEVER OVERWRITTEN, NO PROVIDER SDK IMPORTS, DUPLICATE GATE, OWNERSHIP.
2. SAME CODEBASE: LAPTOP (MOCK LLM, ZERO DEPS) · AIR-GAPPED ON-PREM (OLLAMA/VLLM) · ANY CLOUD · HYBRID.
```

## 8. Title block (bottom-right, 3-row bordered table)

```
INTAKEPILOT — AI REQUIREMENTS INTAKE PLATFORM
DRAWING 02 — SYSTEM ARCHITECTURE
REV 0.1 · 2026-07 · MIT          | SHEET 2 / 2
```

## 9. Accuracy rules (do not violate while restyling)

- Jira / ADO and the Builder-Agent scaffold are ROADMAP — never present them
  as shipped. Local repo + GitHub issues are shipped.
- The router is keyword + precedent (it learns from reroutes) — not
  "AI-powered routing".
- Only requirement versions are strictly append-only; glossary/system_kb
  are upserts — hence "LEDGERS" not "append-only ledgers" as the box title.
- The escalation tier is optional and fires only on validation failures.
- Keep "the LLM is a component, never in control" framing in the header.

## 10. One-paragraph brief (paste into a design tool / AI)

> Clean engineering drawing, white background, landscape 16:10. Four
> full-width horizontal layers, each a thin-bordered band with a small grey
> uppercase label: CLIENTS (3 boxes), DETERMINISTIC CORE (5 boxes),
> PROVIDER PROTOCOLS (5 boxes), LEDGERS/LEARNING/OPS (3 boxes) — box titles
> bold uppercase, 3–5 short body lines each (exact copy provided). Slate
> ink (#1E293B) on white, teal (#0F766E) highlighting only the Orchestrator
> and LLMProvider titles, amber (#B45309) used only for one feedback line
> returning up the right margin labeled "LEARNING SIGNALS RETURN TO THE
> CORE" and the Learning Loops box title. Exactly three labeled vertical
> connectors between layers, orthogonal lines only, small closed
> arrowheads, monospace connector labels, notes panel bottom-left,
> architect's title block bottom-right. No gradients, no icons, no
> diagonal lines, no decorative arrows.
