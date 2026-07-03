# UI Design Guidelines (binding)

1. **Modern AI-product quality** — Linear/Vercel-grade polish: cohesive design tokens, good typography, subtle motion, real empty states, no placeholder content.
2. **No purple anywhere.** No purple/violet/indigo hues in any state (brand, buttons, badges, charts, gradients, focus rings, links, hover states). Preferred accent palette: teal/cyan or blue-green primary; amber for warnings; red for failures; green for success. Provenance badge colors must also avoid the purple family.
3. **Dual theme, first-class.** Both dark and light themes fully supported:
   - All colors via CSS custom properties (semantic tokens: `--bg`, `--surface`, `--text`, `--muted`, `--accent`, `--border`, etc.), never hard-coded hex in components.
   - Theme toggle in the UI header; default follows `prefers-color-scheme`; choice persisted (localStorage).
   - Verify contrast (WCAG AA) and legibility of confidence bars, provenance badges, gate pipeline states, and charts in BOTH themes — screenshot-check each major screen in each theme.
4. Consistency: chat, Shadow Draft panel, confirmation view, gates/routing view, and metrics dashboard all consume the same token set; no per-page palettes.
