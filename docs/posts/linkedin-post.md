# LinkedIn Post

*(Attach both drawings as images: `docs/assets/workflow.png` first, `docs/assets/architecture.png` second. Paste the text below as-is; LinkedIn keeps the line breaks. Add the GitHub + Medium links before posting.)*

---

I've spent most of my career in enterprise IT, a lot of it around SAP. Looking back at the projects that failed or slipped, almost none died because of technology. They died at the requirement. The BRD came late, or said one thing and meant another, or three teams read it three different ways. Nobody shared the same picture, so the gap surfaced months later in UAT, where it costs the most.

We gave delivery Jira and code Git. The step everything depends on, where a business need becomes a requirement, still runs on a Word template and follow-up calls.

At some point I stopped complaining and built something about it, on nights and weekends. It's called IntakePilot and it's open source. The numbers below are from its shipped demo, reproducible in about five minutes with "make dev". No cloud account, no model download.

A Finance Ops analyst types one sentence: "our monthly vendor report takes 3 days to compile by hand."

Before asking her anything, the system drafts the requirement live. Outcome extracted from her words at 0.85 confidence, stakeholders inferred from her department, affected systems pulled from the org glossary, data sensitivity assumed as "internal, override at confirm". Readiness: 34.

Then it asks 2 questions, with reasons, against a budget that lives in Python code rather than a prompt. There's a test where a malicious model tries to ask more and can't. Two taps: readiness 83, confirm unlocks. She fixes one system the glossary missed. Five quality gates run, and the router explains itself in writing: 'Matched 1 signal for "data-platform": "report".'

The ticket keeps her original ask word for word, tags every claim with provenance and confidence, and declares every assumption. Her one-field fix becomes a training example for the next intake. The learning sits in ledgers, not fine-tuned weights, so you can swap models and keep every lesson.

Business users never get technical questions. After confirmation the system discovers backend context on its own. In the SAP demo, "order info" resolves to VBAK/VBAP plus a custom Z-field (ZZ_PRIORITY_CODE) with its owning team.

From there: an optional BA pass, functional review, then your PM tool. Local repo or GitHub issues today, Jira/ADO next via the same one-class protocol. AI coding agents are only as good as the ticket that feeds them. This makes that ticket.

The feedback loops are live, not planned. Duplicates get caught against real history and attached with one click. A relabeled ticket teaches the router it picked the wrong queue. Corrections replay as an eval suite that scores extraction accuracy on your own data. Intake also runs inside Slack or Teams through a single endpoint: answer by number, type "confirm", done. 100+ tests pin the invariants.

Two things I didn't compromise on.

1. The LLM is a component, never in control. Deterministic code owns budgets, merges, gates and routing, and adversarial tests prove it.

2. Your model, your choice, including hybrid. Is a local LLM smart enough to understand the business? On day one, maybe not. So a stronger model (cloud or a bigger internal one) answers only the hard turns where the local model's output fails validation, and every correction makes the local model better on your business until those escalations mostly stop. Your processes are core IP. Nothing leaves your network unless you decide it should.

The two drawings attached are the whole system. Sheet 1 is the workflow every role shares. Sheet 2 is the architecture that makes it run anywhere: laptop, air-gapped data center, any cloud.

Code + drawings: [GitHub link]
Longer write-up: [Medium link]

What would make this useful for your intake process? Asking because I want to build the next piece against real needs.

#EnterpriseAI #SAP #S4HANA #RequirementsEngineering #LocalLLM #OpenSource
