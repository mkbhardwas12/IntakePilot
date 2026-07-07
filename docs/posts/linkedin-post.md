# LinkedIn Post

*(Attach `docs/assets/hero-illustration.png` first — the text-free hero; paste the caption from `docs/assets/thumbnail-brief.md` §4 under it. Attach `docs/assets/architecture.png` second for the technical audience. `docs/assets/hero-illustration-labeled.png` is the numbered/legend variant for slides or the README. The Medium short link redirects to the published article automatically.)*

---

A requirement in a large company is translated four times before a developer ever reads it.

Requester to BA. BA to functional team. Functional to architect. Architect to developer. Each translation is careful. Each one loses a little meaning. The bill arrives at UAT — "that's not what I asked for" — and by then it's the most expensive sentence in the project.

Watch it happen with something trivial: a finance analyst says, in perfectly clear words, "our monthly vendor report takes 3 days to compile by hand." Five hand-offs later, something ships. It is well-built, tested, documented — and not what she needed. Nobody did anything wrong. Every translation was well-meant. The drift is structural, not human error.

IntakePilot is my open-source attempt at closing that gap.

You type the ask in plain words. It builds the requirement live — what it extracted, what it inferred from precedent, what it assumed and why — and asks at most seven questions, a budget enforced in code, not in a prompt. You confirm. It then discovers the backend context on its own (SAP tables, custom Z-fields, owning teams), so nobody has to quiz a business user about systems she's never heard of. Five quality gates run, including a real duplicate check against past work. The ticket routes with a written explanation and a price on the delay: 3 days × 12 months is 288 hours a year of someone's working life.

One rule holds it together: the LLM proposes, deterministic code decides. Budgets, merges, gates, routing — plain Python, pinned by tests. The model cannot overwrite a human's answer. Ever.

The part I care most about: it runs on whatever AI you're allowed to use. Mock model for the offline demo, Ollama fully air-gapped, or any OpenAI-compatible endpoint (Azure, vLLM, LiteLLM, OpenRouter). Enabling your own model is three environment variables — no code changes — and /health tells you which model is answering. There's a hybrid mode too: a local model handles the day-to-day, a stronger one steps in only when structured output fails validation twice.

Every human correction lands in an append-only ledger and improves the next intake. The learning lives in data, not weights — swap the model next quarter, keep the memory.

Current state: 125 backend tests, a 31-check live ops probe, Docker paths from laptop to air-gapped prod. Honest gaps too: no end-user SSO yet; Jira/ADO targets are next.

Open source, MIT. If your intake chain loses meaning between well-intentioned hand-offs, have a look — and tell me where it's wrong.

(Personal open-source project. The scenario above is an industry composite, not any employer or client.)

GitHub: https://github.com/mkbhardwas12/IntakePilot
Architecture write-up: https://medium.com/p/2267d1ea9ec0

#EnterpriseAI #OpenSource #LocalLLM #RequirementsEngineering #SAP
