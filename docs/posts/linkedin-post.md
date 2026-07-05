# LinkedIn Post

*(Attach `docs/assets/intakepilot-thumbnail.png` first as the labeled main thumbnail. Attach `docs/assets/architecture.png` second for the technical audience. The clean unlabeled artwork is preserved at `docs/assets/intakepilot-thumbnail-clean.png` if you want a quieter variant later. After the Medium article is published, replace `[Medium link]` with the real URL.)*

---

Last month I watched a simple request die the usual death.

A finance analyst asked for help: "our monthly vendor report takes 3 days to compile by hand." By the time it reached a sprint board it had been translated four times — requester to BA, BA to functional team, functional to architect, architect to developer. Nobody did anything wrong. Every translation was careful and well-meant. And the thing that shipped still wasn't what she needed.

That gap is what I built IntakePilot for.

You type the ask in plain words. It builds the requirement live — what it extracted, what it inferred from precedent, what it assumed and why — and asks at most seven questions, a budget enforced in code, not in a prompt. You confirm. It then discovers the backend context on its own (SAP tables, custom Z-fields, owning teams), so nobody has to interrogate a business user about systems she's never heard of. Five quality gates run, including a real duplicate check against past work. The ticket routes with a written explanation and a price on the delay: 3 days × 12 months is 288 hours a year of someone's working life.

One rule holds it together: the LLM proposes, deterministic code decides. Budgets, merges, gates, routing — plain Python, pinned by tests. The model cannot overwrite a human's answer. Ever.

The part I care most about: it runs on whatever AI you're allowed to use. Mock model for the offline demo, Ollama fully air-gapped, or any OpenAI-compatible endpoint (Azure, vLLM, LiteLLM, OpenRouter). Enabling your own model is three environment variables — no code changes — and /health tells you which model is answering. There's a hybrid mode too: a local model handles the day-to-day, a stronger one steps in only when structured output fails validation twice.

Every human correction lands in an append-only ledger and improves the next intake. The learning lives in data, not weights — swap the model next quarter, keep the memory.

Current state: 125 backend tests, a 31-check live ops probe, Docker paths from laptop to air-gapped prod. Honest gaps too: no end-user SSO yet; Jira/ADO targets are next.

Open source, MIT. If your intake chain loses meaning between well-intentioned hand-offs, have a look — and tell me where it's wrong.

GitHub: https://github.com/mkbhardwas12/IntakePilot
Architecture write-up: [Medium link]

#EnterpriseAI #OpenSource #LocalLLM #RequirementsEngineering #SAP
