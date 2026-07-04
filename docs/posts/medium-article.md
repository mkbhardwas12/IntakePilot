# I built an AI requirements platform that doesn't need anyone's cloud

*A plain-language ask becomes a routed, code-ready ticket. Local model, your servers, and it learns from every correction.*

*(Cover image: `docs/assets/workflow.png` from the repo. Drop `docs/assets/architecture.png` into the architecture section below.)*

Most of my career has been in enterprise IT, a good part of it in and around SAP landscapes. In all those years I can count on one hand the projects that failed because the technology wasn't good enough. The ones that failed died earlier and quieter than that. A business requirement document that arrived six weeks late and still didn't say what the business meant. A requirement that meant one thing in Finance and something else by the time it reached the build team. An analyst carrying ten open requests who never got the one detail that mattered. And no shared picture anywhere, so the gap stayed invisible until UAT, where fixing it costs the most.

For a long time I filed this under "people problem". At some point I admitted it's a tooling problem. Delivery has Jira. Code has Git. Incidents have their pagers. The step where a business need becomes a requirement, the step everything downstream depends on, has a Word template and hope.

And it's getting more urgent, not less. AI coding agents can now take a Jira ticket and open a pull request. Atlassian has made [Agents in Jira generally available](https://www.atlassian.com/blog/rovo/ai-agents-in-jira), and GitHub's [Copilot coding agent works from inside Jira work items](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/cloud-agent/integrate-cloud-agent-with-jira), opening draft pull requests from the ticket's title, description and comments. Everyone deploying these tools is learning the same lesson: [the quality of AI-generated code is capped by the ticket that triggered it](https://www.augmentcode.com/guides/jira-ticket-to-pull-request-automation). A two-sentence ticket now produces the wrong thing faster than ever. The bottleneck moved upstream, into intake, where nothing was standing.

So on nights and weekends I built the tool I kept wishing existed, and open-sourced it. IntakePilot turns a plain-language business ask into a structured, quality-gated, correctly routed requirement, self-hosted, and whether a single token ever leaves your network is a configuration decision, not a product decision. Everything below comes from a real run of the shipped demo, which you can reproduce in about five minutes with `make dev`. No model download, no cloud account, no signup.

## The demo, minute by minute

The requester in the shipped scenario is a Finance Ops analyst. She types one sentence, the way she'd say it out loud:

> our monthly vendor report takes 3 days to compile by hand

Before the system asks her anything, the draft panel fills in live. Each slot is tagged with where its value came from and how confident the system is. In the actual run: the business outcome was extracted from her sentence at 0.85 confidence. Stakeholders were inferred at 0.55 from nothing more than her department. Affected systems came out of the org glossary, which already knows "vendor report" means ERP-VendorMaster and BI-Reporting. Data sensitivity was assumed to be "internal" and labeled as an assumption she can override. Readiness score: 34.

Then it asks two questions, urgency and success criteria, each with a one-line reason attached, answerable as chips. The budget meter shows 2 of 7 spent. That cap is a Python constant in the orchestrator, not an instruction in a prompt. There's a test where a deliberately malicious model tries to ask more questions and can't.

Two taps later readiness is at 83 and Confirm unlocks. She reviews the draft, notices the glossary missed a system, and edits the affected-systems field. Five gates run: schema completeness, INVEST, an ambiguity lint that wants measurable anchors, a duplicate check, routing sanity. Then the router picks a queue and writes down why. Verbatim from the run: *Matched 1 signal(s) for "data-platform": "report".*

The ticket that lands is something a developer can work from. This is the top of the real file, `IPR-2026-000001.md`:

```markdown
# Automate the monthly vendor report — currently 3 days to compile by hand

- Requirement: IPR-2026-000001 v6 · Requester: Demo (Finance Ops)
- Readiness at confirmation: 83

## Slots
- Business outcome  (extracted, 0.85): Automate the monthly vendor report …
- Affected systems  (edited,    1.00): ERP-VendorMaster, BI-Reporting, NewSys
- Urgency           (answered,  0.95): this week
- Data sensitivity  (assumed,   0.50): internal

## Original ask (verbatim)
> our monthly vendor report takes 3 days to compile by hand

## Assumptions
- data_sensitivity = internal — org norm; override at confirm
```

Every claim carries provenance and confidence. Her original words survive verbatim. Assumptions are declared instead of buried. The requester, the analyst, the reviewer and the developer are all looking at the same requirement.

## Nobody asks the business user about SAP tables

Slots like affected systems are marked `askable: false` in the schema, and a test enforces that the question composer can never ask them. After confirmation, an enrichment step resolves the business terms against a system-knowledge connector. The demo ships with an SAP S/4HANA fixture. Run the second scenario, "I need a report of goods details for product line X with the order info", and the routed ticket gains a section called "System context (auto-discovered)": sales orders are VBAK/VBAP, materials are MARA, and there's a custom Z-field called ZZ_PRIORITY_CODE with a description and an owning team. The requester was never asked a technical question to get there.

## The edit is the product

The field she fixed became a row in an edit ledger: proposed value, corrected value, context, and a note about how the wrong value had been produced. The next similar intake gets her correction injected into its extraction prompt as an example. The discovered SAP entities land in a knowledge ledger that pre-fills future drafts. A business analyst can sit in the loop where the org wants one; smaller teams go straight to a functional reviewer. The learning lives in ledgers rather than in fine-tuned weights, so you can swap the model tomorrow and keep every lesson.

These loops run today, they are not roadmap slides. Corrections recalibrate how much the readiness score trusts each kind of inference, per department. Question outcomes reorder what gets asked first, so slots people keep skipping sink down the list. When a team relabels a ticket to another queue, a webhook feeds that back into routing. Repeated identical corrections surface as glossary proposals that a human accepts or ignores. The corrections ledger even replays as an eval suite (`/api/evals/replay`) that scores extraction accuracy per slot, which means prompt changes get regression-tested against your own history instead of hand-written fixtures. And a near-duplicate ask gets caught at gate 4 against the real index, with a one-click "attach to the existing requirement" instead of a dead end.

## One good requirement is table stakes. The portfolio is the point.

Here's the failure mode nobody's intake tool sees: two *different* requirements, both legitimate, both routed, quietly changing the same backend object. Team A extends `ZZ_PRIORITY_CODE` for order handling while Team B repurposes it for a fulfillment feed. Neither is a duplicate of the other, so no duplicate check fires. They meet three months later, at the merge conflict, or worse, in production.

IntakePilot catches this at confirmation. Every requirement already carries its auto-discovered backend context, so the system intersects entities across all open work: confirm a second ask touching `sales_order` and the response, the audit trail and the ticket all say so — "IPR-2026-000001 (routed, order-management) shares: sap_s4_demo:sales_order. These teams should talk before building." It doesn't block anything; collisions aren't duplicates. It just makes the conversation happen at intake instead of at UAT. A graph endpoint shows the hotspots: entities with more than one open requirement on them.

Three more things land on that same ticket, all shipped and tested. The ask prices its own pain: "3 days, monthly, by hand" becomes an auto-computed **288 hours per year of doing nothing** — plain arithmetic from the requester's own words, never an LLM guess — and the metrics endpoint sorts the routed backlog by it, so queues can work by value instead of by noise. Routed tickets carry generated Given/When/Then acceptance criteria, which is exactly what a coding agent needs to verify its own pull request. And every named stakeholder gets a countersign record at confirmation — approve or object, on the ledger, before the work starts. Objections at intake are cheap. Objections at UAT are how projects die.

Intake doesn't have to happen in yet another tool, either. One inbound endpoint lets a Slack or Teams bot run the whole flow. The user answers by number and types "confirm" at the end. Asks are classified on arrival (bug report, data request, new capability) and each type gets its own slot schema. The question budget scales from 3 to 9 depending on how many systems the ask touches and how tight the deadline is. Enforced in code, like everything else.

Tickets write to a local repo or straight to GitHub issues, one config switch. Jira and Azure DevOps are a single class away because every target implements the same small protocol. The roadmap's Builder Agent will attach a generated implementation scaffold next to the business requirement, so a coding agent gets the input it needs and a developer reviews two attachments instead of decoding one vague ticket.

*(Diagram: the whole system in one drawing, `docs/assets/architecture.png`.)*

## Is a local model smart enough for this?

This is the objection I would raise myself. Understanding what a business user means takes real model capability, and a small open-weight model will misread things a frontier model wouldn't. If running locally required pretending otherwise, I wouldn't have bothered.

Three things make it work anyway.

First, you can bring any model. The LLM sits behind a small provider protocol and business logic imports no SDK (there's a test that fails the build if someone tries). One env var points the system at a deterministic mock, at Ollama on your own GPU box, or at any OpenAI-compatible endpoint: vLLM, LiteLLM, Azure OpenAI, an internal gateway. If your policy allows a frontier model in the cloud, use it from day one.

Second, you can go hybrid. A local model answers every turn, and a stronger model gets exactly one attempt when the local model's structured output fails validation twice. You pay premium tokens only for the hard turns. Embeddings stay on the primary so the vector index stays consistent, and a fully air-gapped hybrid (small local model plus a big local one) works the same way. The whole setup is `INTAKEPILOT_LLM_ESCALATION=openai_compat`, and it ships with tests, not as a promise.

Third, daily usage closes the gap. Understanding "what the business is saying" turns out to be less about raw model IQ and more about knowing that in your company "the vendor report" means these two systems, this team, that Z-field. That knowledge accumulates in ledgers on your side of the firewall. The local model gets measurably better on your domain every week, escalations taper off, and the cost curve bends down while usage goes up.

Security and economics push the same direction. Business processes are core IP, and an intake system sees all of them, in employees' own words, all day. In DSAG's research, [data protection ranks second only to cost among cloud concerns for SAP customers](https://www.asug.com/insights/asug-and-dsag-research-shows-customer-perceptions-of-rise-with-sap-cloud-and-sap-s-4hana), and [more than half of LLM workloads already run on-premises](https://www.techstoriess.com/open-source-on-premise-llms-deployment-security-cost-and-performance-compared/). Per-token enterprise pricing adds up fast at intake volume; SAP doesn't publish AI Unit list prices, but [third-party licensing analysts put negotiated pricing around €7 per unit, with heavy users reportedly exhausting allocations within months](https://saplicensingexperts.com/blog/sap-ai-units-explained-the-complete-enterprise-guide-for-2026). Apache-2.0 open-weight models ([Qwen, Gemma and friends](https://huggingface.co/blog/daya-shankar/open-source-llm-models-to-run-locally)) keep closing the quality gap, and on your accumulated context they will eventually be better for you than any general model. One Docker Compose file deploys the stack (Postgres with pgvector, model server, API, UI) on-premises, fully air-gapped, or on any cloud VM.

## The SAP situation

If you live in the SAP world you know the clock. SAP provides mainstream maintenance for SAP Business Suite 7 core applications [until the end of 2027, followed by optional extended maintenance until the end of 2030](https://www.seidor.com/en-us/blog/understanding-sap-ecc-deadlines), and Gartner expects [close to 17,000 of roughly 35,000 ECC organizations to still be on it at the deadline](https://www.softwareseni.com/what-sap-ecc-end-of-support-actually-means-and-why-17000-companies-are-not-ready/). SAP's answer is RISE. In earlier DSAG research, [only 12% of members saw high value in RISE](https://www.ibsolution.com/academy/blog_en/dsag-survey-determines-companies-opinion-of-rise-with-sap). Separately, DSAG's 2026 investment reporting shows [42% of members still planning high or medium investment in S/4HANA on-premises](https://www.ibsolution.com/academy/blog_en/dsag-survey-determines-companies-opinion-of-rise-with-sap). The user group has said openly that [SAP's cloud-first innovation discriminates against on-premise customers](https://www.constellationr.com/insights/news/dsag-saps-innovation-focus-cloud-discriminates-against-premise-users).

Signavio is good software. It's a [Leader in Gartner's process-intelligence Magic Quadrant](https://news.sap.com/2026/05/sap-signavio-gartner-magic-quadrant-process-intelligence-platforms/) and now has [Joule as a conversational front end](https://news.sap.com/2026/02/process-conversation-joule-sap-signavio-solutions-generally-available/). It's also cloud-only and metered, and it tells you how your processes run. Nothing in that stack helps the thousands of on-prem and hybrid customers govern how new requirements enter, and that backlog is exactly what the 2027 deadline multiplies. Every S/4HANA migration is thousands of requirement conversations: what do we keep, what do we drop, which Z-field still matters and why. That upstream gap is what IntakePilot aims at, and it's why the demo connector speaks SAP. Your requirement doesn't just say "orders". It knows you mean VBAK/VBAP, that ZZ_PRIORITY_CODE exists, who owns it, and that someone should decide its fate.

The same squeeze applies outside SAP: deep on-prem systems, deep process IP, modernization pressure from above, cloud-only AI tooling from vendors, and a security team that won't stream internal operations to third-party APIs.

## What's missing

IntakePilot is v0.1 and says so. There's no end-user SSO yet; requirements are bound to their creating session, one bearer token closes every admin surface, and the GitHub webhook verifies HMAC signatures, but user identity is your reverse proxy's job for now. The Jira target is next. The Builder Agent that auto-attaches code scaffolds is specified but not shipped. What is shipped is tested: 100+ tests pin the invariants, including the question budget, the rule that human input is never overwritten, append-only versioning, the duplicate gate, ownership binding, and the ban on SDK imports in business logic. One test plays a malicious LLM that tries to break the budget. It can't.

The design principle under all of it: the LLM is a component, never in control. Deterministic code decides budgets, merges, gates and routing. The model proposes; code disposes. I don't think AI earns trust in enterprise workflows any other way, and it's also what keeps the system working when you swap models underneath it. In the age of fast-improving open weights, you will.

Code, drawings, and the five-minute demo: **[github.com/YOUR-USERNAME/intakepilot]** *(update after pushing)*. If your team drowns in requirements ping-pong, or you're staring down an S/4 migration backlog, I'd like to hear what would make this useful for you.

---

*Sources: [Atlassian — Agents in Jira](https://www.atlassian.com/blog/rovo/ai-agents-in-jira) · [GitHub Docs — Copilot cloud agent with Jira](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/cloud-agent/integrate-cloud-agent-with-jira) · [GitHub Changelog — Copilot for Jira GA](https://github.blog/changelog/2026-06-25-github-copilot-for-jira-is-now-generally-available/) · [Augment Code — ticket-to-PR quality ceiling](https://www.augmentcode.com/guides/jira-ticket-to-pull-request-automation) · [ASUG/DSAG cloud perception research](https://www.asug.com/insights/asug-and-dsag-research-shows-customer-perceptions-of-rise-with-sap-cloud-and-sap-s-4hana) · [DSAG on RISE value & investment plans](https://www.ibsolution.com/academy/blog_en/dsag-survey-determines-companies-opinion-of-rise-with-sap) · [Constellation — DSAG on cloud-first innovation](https://www.constellationr.com/insights/news/dsag-saps-innovation-focus-cloud-discriminates-against-premise-users) · [SEIDOR — ECC deadlines](https://www.seidor.com/en-us/blog/understanding-sap-ecc-deadlines) · [SoftwareSeni — 17,000 not ready](https://www.softwareseni.com/what-sap-ecc-end-of-support-actually-means-and-why-17000-companies-are-not-ready/) · [SAP Licensing Experts — AI Units](https://saplicensingexperts.com/blog/sap-ai-units-explained-the-complete-enterprise-guide-for-2026) · [SAP News — Signavio in Gartner MQ](https://news.sap.com/2026/05/sap-signavio-gartner-magic-quadrant-process-intelligence-platforms/) · [SAP News — Joule with Signavio GA](https://news.sap.com/2026/02/process-conversation-joule-sap-signavio-solutions-generally-available/) · [TechStoriess — on-prem LLM share](https://www.techstoriess.com/open-source-on-premise-llms-deployment-security-cost-and-performance-compared/) · [Hugging Face — open models to run locally](https://huggingface.co/blog/daya-shankar/open-source-llm-models-to-run-locally)*
