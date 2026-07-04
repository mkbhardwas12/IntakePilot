# LinkedIn Post

*(Attach `docs/assets/workflow-social.png` FIRST — the mobile-friendly version — and `docs/assets/architecture.png` second. The detailed engineering sheet `workflow.png` stays in the repo/Medium. Paste the text below as-is; it is ~2,850 characters, under LinkedIn's 3,000 limit. Add the GitHub + Medium links before posting.)*

---

I've spent most of my career in enterprise IT, a lot of it around SAP. Looking back at the projects that slipped or failed, almost none died because the technology wasn't good enough. They died earlier: at the requirement.

A BRD came late. A ticket said one thing and meant another. Three teams read the same ask three different ways. The gap surfaced in UAT, where it costs the most.

So on nights and weekends I built IntakePilot, and open-sourced it.

It turns a plain-language business ask into a structured, quality-gated, correctly routed, code-ready requirement. Local-first: your model, your data, your network boundary.

Demo example: "our monthly vendor report takes 3 days to compile by hand."

Before asking anything, it drafts the requirement live:
- outcome extracted from the ask
- stakeholders inferred from context
- affected systems pulled from the org glossary
- every assumption declared, readiness scored

Then it asks only the missing business questions. The budget is enforced in Python, not in a prompt. There's a test where a malicious model tries to ask more; the orchestrator refuses.

After confirmation, five gates run: schema, INVEST, ambiguity, duplicate detection against real history, routing sanity. The route is explained in writing. The ticket keeps the original ask word for word, with provenance and confidence on every claim.

Business users are never asked about SAP tables or backend columns. Enrichment resolves that after confirmation. In the demo, "order info" maps to VBAK/VBAP and a custom Z-field with its owning team.

The learning lives in ledgers, not model weights:
- corrections become prompt exemplars
- reroutes become routing precedent
- duplicates get attached, not rebuilt
- repeated edits become glossary proposals
- correction replay shows whether accuracy is actually improving

And it sees the portfolio, not just one ticket. Two different asks touching the same SAP table meet at intake instead of at the merge conflict. Every ticket prices its own pain: "3 days, monthly, by hand" becomes 288 hours a year of doing nothing, computed from the requester's own words. Routed work carries generated acceptance criteria a coding agent can verify against. Named stakeholders countersign before the build starts, not after UAT fails.

The design rule underneath: the LLM proposes, deterministic code decides.

Local repo and GitHub issues work today. Jira/ADO and the builder-agent scaffold are roadmap, through the same target protocol. Runs on a laptop, air-gapped on-prem, or any cloud, with a local model, a cloud model, or a hybrid of both.

The attached drawings show the workflow and the architecture.

Code + drawings: [GitHub link]
Longer write-up: [Medium link]

What would make this useful for your intake process?

#EnterpriseAI #SAP #S4HANA #RequirementsEngineering #LocalLLM #OpenSource
