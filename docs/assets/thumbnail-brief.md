# Thumbnail brief — IntakePilot hero illustration

Instructions for producing, refining and USING the 3D hero/thumbnail image.
Unlike the architecture drawings, this asset is deliberately **text-free** —
an image generator can't misspell what it doesn't write, and thumbnails are
read as shapes, not words. Meaning is carried by the legend below, which
doubles as the alt-text/caption so viewers actually learn from it.

---

## 1. Where it's used

| Placement | Size / ratio | Notes |
|---|---|---|
| Medium cover (alternative to `cover.png`) | 1600×800, 2:1 | title renders next to it, so no text needed in-image |
| LinkedIn link preview / post image | ≥1200×627, ~1.91:1 | crop-safe if key objects stay inside the middle 80% |
| YouTube / video thumb (if ever) | 1280×720, 16:9 | add a 3–4 word text overlay in an editor, never in the generator |
| GitHub social preview | 1280×640, 2:1 | works as exported |

## 2. Hard rules

1. **No text inside the generated image.** Ever. Generators corrupt small
   glyphs (we proved this over six rounds). Any words get overlaid later in
   an editor where text is typed, not painted.
2. **No third-party logos or mascots** — no Octocat, no OpenAI mark, no
   Ollama llama, no Slack hash. Generic hardware and icons only.
3. **One accent family.** Teal (#14B8A6 highlights, #0F766E deep) carries
   the brand; a single amber (#F59E0B) element is allowed and should mean
   something (see legend: the gate that catches an issue).
4. Chunky silhouettes, soft studio lighting, clean edges — it must stay
   readable at 200 px wide.

## 3. Composition (three zones, one story)

The canvas splits diagonally: **light half on the left (the business
world), dark half on the right (your system boundary)**. That split IS the
product's core claim — plain-language business asks on one side, controlled
enterprise infrastructure on the other, with IntakePilot as the bridge.

- **Left / light zone (~25%)** — floating white cards with a teal chat
  icon and text-placeholder lines; three smaller cards beneath with graph /
  funnel / double-check icons. Thin teal cables run from the cards toward
  the laptop.
- **Center (~40%, focal)** — a dark laptop, screen showing a flowchart of
  rounded nodes: teal and blue slot nodes, one teal check-node in the
  middle, side panels with amber/teal line items. Below the laptop, a white
  tray with four raised check-tiles: three teal, one amber. A dark panel
  with list rows and a stack of teal sheets sits to its right.
- **Right / dark zone (~35%)** — a rounded dark module with an exposed
  gear and two status dots (teal/amber); cables fan out to a server rack
  with lit bays, a chrome-and-teal database cylinder stack, and a voxel
  cube with glowing teal cells; all standing behind/inside a translucent
  blue glass plane crowned with a shield-and-padlock. A white plate with
  three interlocking gears sits at the front edge; a single amber cable
  returns from it toward the center.

## 4. Legend — what each element means (use as alt-text / caption)

| Visual | Meaning in IntakePilot |
|---|---|
| White chat cards, light side | Plain-language business asks — web chat, Slack/Teams, API; the requester's own words |
| Small cards: graph / funnel / checks | Typing & schema forks, budgeted questions, human confirmation |
| Laptop with node flowchart | The live Shadow Draft: slots filling with provenance while the orchestrator (deterministic code) runs the loop |
| Tray of four check-tiles, one amber | The quality gates — most pass, and the amber one is the point: gates exist to catch duplicates, ambiguity and collisions **before** routing |
| Dark list panel + stacked teal sheets | The routed ticket and the append-only ledgers underneath it |
| Rounded module with exposed gear | The deterministic core — "the LLM proposes, code decides" |
| Server rack, database cylinders, voxel cube | Your own infrastructure: local LLM, Postgres/SQLite store, vector index — nothing has to leave |
| Translucent glass wall + shield & padlock | The network/security boundary: session-bound access, admin token, signed webhooks |
| Three interlocking gears on the white plate | Provider protocols — the only door out; swap models/stores/targets without touching business logic |
| Single amber return cable | Learning signals flowing back: corrections, reroutes and validations that make the next intake smarter |
| Light→dark split itself | Business side / system side — IntakePilot is the bridge that keeps one requirement meaning one thing on both sides |

**Ready-made caption (Medium/LinkedIn):**
> From a plain-language ask (left) through deterministic gates and
> orchestration (center) to your own secured infrastructure (right) — with
> one amber thread of learning feeding every correction back. That's
> IntakePilot in one picture.

## 5. Paste-ready generation prompt

> Clean 3D isometric illustration, soft studio lighting, split background:
> matte white-gray on the left, deep navy on the right. Left: floating
> white UI cards with a teal chat-bubble icon and grey placeholder lines,
> three smaller cards with graph, funnel and checkmark icons, thin teal
> cables connecting them rightward. Center focus: a dark modern laptop,
> screen showing a rounded-node flowchart with teal and blue nodes and one
> teal check node, side panel of small list items; in front, a white tray
> holding four raised square tiles with bold checkmarks — three teal, one
> amber; beside it a dark panel with list rows and a small stack of glowing
> teal sheets. Right: a rounded dark device with an exposed gear and two
> small status lights, cables fanning to a small server rack with lit
> drive bays, a chrome database cylinder stack with teal bands, and a dark
> voxel cube with a few glowing teal cells, all behind a translucent blue
> glass plane topped by a shield with a padlock; a white plate with three
> interlocking dark and teal gears at the front, one amber cable running
> back toward the laptop. Consistent teal accent (#14B8A6), single amber
> accent, high contrast, chunky readable shapes, no text anywhere, no
> letters, no logos, no brand marks. 2:1 landscape.

## 6. Known-good review checklist (run on every new render)

- [ ] Zero legible or pseudo-text anywhere (zoom in on screens and panels)
- [ ] No recognizable third-party logo or mascot
- [ ] Key objects inside the middle 80% (crop-safe)
- [ ] Still readable scaled to 200 px wide
- [ ] Exactly one amber element family (gate tile + return cable)
- [ ] Export ≥1600×800 PNG; save as `docs/assets/hero-illustration.png`

## 7. Relationship to the other assets

This illustration is the *emotional* cover; `architecture.png` (modern
drawing) is the *factual* one. Pair them: illustration as the Medium cover
or LinkedIn first image, the architecture drawing immediately where the
text explains the system. Never use the illustration as the architecture
reference — it has no labels by design.
