# LinkedIn Post

*(Attach `docs/assets/workflow.png` as the image. Paste the text below as-is; LinkedIn keeps the line breaks. Add the GitHub + Medium links before posting.)*

---

Every failed IT project starts with a requirement that meant one thing to the person who wrote it and something else to everyone downstream.

AI coding agents made this worse, not better: they'll happily build the wrong thing faster. The quality ceiling of AI-generated code is set by the ticket that triggered it — and most tickets are two sentences long.

So I built IntakePilot, and open-sourced it.

A business user describes a need in plain language. The system drafts the structured requirement live, infers what it can from context and precedent, asks at most 7 questions (enforced in code, not in a prompt), and never asks a business user a technical question — backend context like SAP tables and Z-fields is auto-discovered after confirmation.

From there: an optional business-analyst pass, a functional review, five quality gates, and routing to the right team queue with a written explanation. The ticket lands in Jira/ADO carrying two artifacts — the business requirement and a code scaffold — ready for an AI coding agent to implement and a developer to review. Everyone in the chain sees the same requirement, in their own language.

Two design choices I refuse to compromise on:

1. The LLM is a component, never in control. Deterministic code owns budgets, merges, gates, routing — and adversarial tests prove it.

2. It runs entirely on YOUR infrastructure. Your processes are core IP; they don't belong in someone else's API logs. Swap one env var: local Ollama, vLLM, any OpenAI-compatible endpoint. Laptop, air-gapped data center, or any cloud. Open-weight models are already good enough for structured intake — and they're only getting better while per-token enterprise AI pricing isn't.

And it learns: every human correction becomes an exemplar that improves the next intake. Model-agnostic, because the learning lives in data, not weights.

If you're in the SAP world staring at the 2027 ECC deadline with a migration backlog of ten thousand requirement conversations — this is the upstream tooling I wished existed.

Code + architecture: [GitHub link]
Full story: [Medium link]

What would make this useful for YOUR intake process? Genuinely asking.

#AI #EnterpriseAI #SAP #S4HANA #RequirementsEngineering #LocalLLM #OpenSource #BusinessAnalysis #DigitalTransformation #Jira
