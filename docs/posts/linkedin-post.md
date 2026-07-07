# LinkedIn Post

*(Attach `docs/assets/hero-illustration.png` first — the text-free hero; paste the caption from `docs/assets/thumbnail-brief.md` §4 under it. Attach `docs/assets/architecture.png` second for the technical audience. `docs/assets/hero-illustration-labeled.png` is the numbered/legend variant for slides or the README. The Medium short link redirects to the published article automatically.)*

---

I've gained a lot from this community over the years, and I keep looking for ways to give something back. Here's my latest attempt.

A requirement in a large company is translated four times before a developer ever reads it. Requester to BA, BA to functional, functional to architect, architect to developer. Each translation is careful; each loses a little meaning. The bill arrives at UAT — "that's not what I asked for" — the most expensive sentence in the project.

Something trivial: a finance analyst says, in perfectly clear words, "our monthly vendor report takes 3 days to compile by hand." Five hand-offs later, something ships — well-built, tested, and not what she needed. Nobody did anything wrong. The drift is structural, not human error.

IntakePilot is my open-source attempt at closing that gap.

You type the ask in plain words. It builds the requirement live — extracted, inferred, assumed, each labeled — and asks at most seven questions, a budget enforced in code, not in a prompt. You confirm. It discovers backend context on its own (SAP tables, custom Z-fields, owning teams), runs five quality gates including a real duplicate check, and routes the ticket with a written explanation and a price on the delay: 3 days × 12 months is 288 hours a year of someone's working life.

One rule holds it together: the LLM proposes, deterministic code decides. Budgets, merges, gates, routing — plain Python, pinned by tests. The model cannot overwrite a human's answer. Ever.

It runs on whatever AI you're allowed to use: mock for the offline demo, Ollama fully air-gapped, or any OpenAI-compatible endpoint (Azure, vLLM, LiteLLM, OpenRouter). Your own model is three environment variables, no code changes. Hybrid mode: local handles the day-to-day; a stronger model steps in only when validation fails twice.

Where it fits your world:
- Drowning in report requests? Budgeted intake, duplicate catch, a backlog sorted by value.
- Bugs arriving as chat messages? They become structured tickets: what broke vs what should happen.
- Piloting AI coding tools? Tickets carry intent, acceptance criteria and system context an agent can build from — fewer clarification loops, faster from ask to diff.
- Different teams, fields, vocabulary? Schemas, queues and glossary are plain config.

Every correction improves the next intake. Learning lives in data, not weights — swap the model, keep the memory.

Current state: 136 backend tests, a 40-scenario golden eval set, GitHub and Jira targets with delivery sync. Honest gaps: no end-user SSO yet; Azure DevOps next.

Open source, MIT. If your intake chain loses meaning between well-intentioned hand-offs, have a look — and tell me where it's wrong.

(Personal project. The scenario is an industry composite, not any employer or client.)

GitHub: https://github.com/mkbhardwas12/IntakePilot
Architecture write-up: https://medium.com/p/2267d1ea9ec0

#EnterpriseAI #OpenSource #LocalLLM #RequirementsEngineering #SAP
