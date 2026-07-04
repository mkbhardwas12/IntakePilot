# LinkedIn Post

*(Attach `docs/assets/workflow-social.png` FIRST — the mobile-friendly version — and `docs/assets/architecture.png` second. The detailed engineering sheet `workflow.png` stays in the repo/Medium. Paste the text below as-is; it is ~2,999 characters, under LinkedIn's 3,000 limit. Add the GitHub + Medium links before posting.)*

---

After many years in enterprise IT, most of them around SAP, one complaint has followed me everywhere. Colleagues, friends at other companies, people at user groups, same sentence: "Getting a clear BRD is hard when no one is aligned yet on what should change, where, and how."

The story is always the same. Business describes a need, a business analyst helps translate it, the functional side reads it one way, the developer another. Each closes a gap for the next person; the differences surface late, when fixes are expensive. Nobody did anything wrong. The ask just changed shape every time it changed hands.

I heard it often enough that I stopped nodding and started building, in my own time. The community has helped me grow everywhere I have been, mostly through people who never knew they were helping. So this is a give-back: IntakePilot, open source. Use it as it is, or adapt the basics to your setup.

It turns a plain-language business ask into a structured, quality-gated, correctly routed, code-ready requirement. Local-first: your model, your data, your network boundary.

Demo ask: "our monthly vendor report takes 3 days to compile by hand."

Before asking anything, it drafts the requirement live: outcome extracted, stakeholders inferred, systems pulled from the org glossary, assumptions declared, readiness scored.

Then it asks only the missing business questions, against a budget enforced in Python, not a prompt. A malicious model can try to ask more; the orchestrator refuses.

After confirmation, five gates run (schema, INVEST, ambiguity, duplicate detection, routing sanity); the route is explained in writing. The ticket keeps the original ask word for word, with provenance and confidence on every claim.

Business users are never asked about SAP tables or backend columns. Enrichment resolves that after confirmation. In the SAP demo, "order info" maps to VBAK/VBAP and a Z-field with its owning team.

Learning lives in ledgers, not model weights: corrections become prompt exemplars, reroutes teach the router, repeated edits become glossary proposals, and replaying old corrections shows whether accuracy is improving.

And it sees the portfolio, not just one ticket. Two different asks touching the same SAP table meet at intake, not at the merge conflict. Every ticket prices its own pain ("3 days, monthly, by hand" becomes 288 hours a year of doing nothing). Routed work carries generated acceptance criteria. Named stakeholders countersign before the build.

The rule underneath: the LLM proposes, deterministic code decides.

Local repo and GitHub issues work today; Jira/ADO and the builder-agent scaffold are next via the same protocol.

The drawings show the workflow and the architecture: laptop, air-gapped on-prem, or any cloud.

Code + drawings: [GitHub link]
Longer write-up: [Medium link]

If something doesn't fit your intake process, tell me. I'd rather improve it against real needs than my own guesses.

#EnterpriseAI #SAP #LocalLLM #OpenSource
