# IntakePilot — Web

Frontend for IntakePilot, an AI requirements-intake platform. A business user chats with an intake agent; extracted requirement "slots" stream into a live Shadow Draft, and once readiness reaches 70 the user reviews, edits, and confirms — kicking off a 5-gate quality pipeline, routing, and ticket creation.

## Stack

- React 18 + TypeScript + Vite 5
- react-router-dom v6
- Hand-written CSS (single design-system file, `src/styles.css`)

## Development

```sh
npm install
npm run dev     # dev server on http://localhost:3000
npm run build   # tsc + vite build
```

The dev server proxies `/api` and `/health` to the backend at `http://localhost:8000`.

## Structure

- `src/types.ts` — backend API contract types
- `src/api.ts` — API client, including the SSE stream consumer for `POST /api/sessions/{sid}/turns` (with a `?stream=false` JSON fallback)
- `src/pages/IntakePage.tsx` — session state, chat + Shadow Draft layout, confirm/post-confirm flow
- `src/pages/MetricsPage.tsx` — metrics dashboard
- `src/components/` — chat pane, Shadow Draft panel (readiness ring, provenance badges), confirm overlay, gate pipeline
