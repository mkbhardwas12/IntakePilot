# LinkedIn Post

*(Attach BOTH drawings as images — `docs/assets/workflow.png` first, `docs/assets/architecture.png` second. Paste the text below as-is; LinkedIn keeps the line breaks. Add the GitHub + Medium links before posting.)*

---

I built and open-sourced IntakePilot. Here's its shipped demo, real numbers, reproducible in 5 minutes with "make dev" — no cloud account, no model download.

A Finance Ops analyst types one sentence: "our monthly vendor report takes 3 days to compile by hand."

Before asking her anything, the system drafts the requirement live — outcome extracted from her words (0.85 confidence), stakeholders inferred from her department, affected systems retrieved from the org glossary, data sensitivity assumed as "internal — override at confirm." Readiness: 34.

Then it asks exactly 2 questions, with reasons, against a hard budget of 7 — enforced in Python, not in a prompt (there's a test where a malicious model tries to ask more and can't). Two chip taps: readiness 83, confirm unlocks. She fixes one system the glossary missed. Five quality gates run, and the router explains itself in writing: 'Matched 1 signal for "data-platform": "report".'

The ticket that lands carries every claim with provenance + confidence, her original ask verbatim, and every assumption declared. Her one-field fix becomes a training exemplar for the next intake — the system learns your business from daily use, in ledgers, not fine-tuned weights.

And business users never get technical questions: after confirmation it auto-discovers backend context itself — in the SAP demo, "order info" resolves to VBAK/VBAP and even a custom Z-field (ZZ_PRIORITY_CODE) with its owning team.

From there: optional BA pass, functional review, then your PM tool — local repo or GitHub issues today, Jira/ADO via the same one-class protocol next. AI coding agents are only as good as the ticket that feeds them — this makes that ticket.

And the loops close. Duplicates get caught against the org's real history and attached with one click. When a team relabels a ticket to another queue, a webhook teaches the router it was wrong. Corrections replay as a self-writing eval suite that scores extraction accuracy on YOUR data. Intake even runs inside Slack/Teams through one endpoint — answer by number, type "confirm", done. 95 tests pin every invariant.

The two drawings attached are the whole system: sheet 1 is the workflow every role shares, sheet 2 is the architecture that makes it deployable anywhere — laptop, air-gapped data center, any cloud.

Two design choices I refuse to compromise on:

1. The LLM is a component, never in control. Deterministic code owns budgets, merges, gates, routing — and adversarial tests prove it.

2. Your model, your choice — including hybrid. "Is a local LLM smart enough to understand the business?" On day one, maybe not — so a stronger model (cloud frontier or a bigger internal one) answers ONLY the hard turns where the local model's output fails validation. Every human correction becomes a training exemplar on your side of the firewall, so the local model gets smarter on YOUR business with daily use and expensive escalations taper toward zero. Your processes are core IP — nothing has to leave your network unless you choose. Laptop, air-gapped data center, or any cloud.

And it learns: every human correction becomes an exemplar that improves the next intake. Model-agnostic, because the learning lives in data, not weights.

If you're in the SAP world staring at the 2027 ECC deadline with a migration backlog of ten thousand requirement conversations — this is the upstream tooling I wished existed.

Code + architecture: [GitHub link]
Full story: [Medium link]

What would make this useful for YOUR intake process? Genuinely asking.

#AI #EnterpriseAI #SAP #S4HANA #RequirementsEngineering #LocalLLM #OpenSource #BusinessAnalysis #DigitalTransformation #Jira
