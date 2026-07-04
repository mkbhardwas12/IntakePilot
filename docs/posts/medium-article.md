# I Built an AI Requirements Platform That Never Sends Your Business Knowledge to Anyone's Cloud

*How a plain-language ask becomes a routed, code-ready ticket — with a local LLM, on your own servers, improving itself with every use.*

*(Cover image: `docs/assets/workflow.png` — upload from the repo)*

No invented war story — I'll just show you the thing I built doing its job. Every number and quote below comes from a real run of the shipped demo, which you can reproduce in five minutes with `make dev`: no model download, no cloud account, no signup. The problem it attacks is easy to state, because we've all lived it: between the person who needs something and the person who builds it sit a two-line ticket form, a busy business analyst reconstructing intent from fragments through no fault of their own, and a developer building a best guess. The two things everybody actually wanted — speed and accuracy — are the first casualties. IntakePilot exists to protect exactly those two.

In 2026 there's a new twist. AI coding agents can now take a Jira ticket and open a pull request — Atlassian is shipping [agents in Jira](https://community.atlassian.com/forums/Jira-articles/Introducing-Agents-in-Jira/ba-p/3194583), GitHub connects [Copilot's coding agent straight to Jira](https://devops.com/github-copilot-coding-agent-for-jira-connects-planning-to-pull-requests-without-leaving-your-workflow/). But everyone deploying these tools is learning the same lesson: [the quality ceiling for AI-generated code is set by the ticket that triggered it](https://www.augmentcode.com/guides/jira-ticket-to-pull-request-automation). A two-sentence ticket produces a best-guess implementation. The bottleneck has moved upstream — to intake.

So I built **IntakePilot**: an open, self-hosted platform that turns a plain-language business ask into a structured, quality-gated, correctly-routed requirement — and *you* decide, per deployment, whether a single token ever leaves your network.

## The real demo, minute by minute

The requester in the shipped scenario is a Finance Ops analyst. She types one sentence — what she'd say out loud, not what a form wants:

> our monthly vendor report takes 3 days to compile by hand

**Before asking her anything**, the Shadow Draft panel fills in live, every slot tagged with where it came from and how sure the system is. From the actual run: *business outcome* — **extracted** from her sentence (confidence 0.85). *Stakeholders* — **inferred** (0.55) from nothing more than her department. *Affected systems* — **retrieved** from the org glossary, which already knows "vendor report" means `ERP-VendorMaster` and `BI-Reporting`. *Data sensitivity* — **assumed**: `internal`, tagged *"org norm; override at confirm."* Readiness score: 34.

Only now does it ask — two questions (urgency, success criteria), each with a one-line *because*, answerable as chips. The budget meter reads 2 of 7 spent. That cap is a Python constant enforced in the orchestrator, not a prompt suggestion an LLM might ignore — there is a test where a deliberately malicious model tries to ask more and can't. This is the extra layer of thinking a requester gets for free: she sees what a *complete* requirement looks like, and what was assumed on her behalf, before committing to any of it.

Two chip taps later, readiness hits 83 and Confirm unlocks. Reviewing the draft, she spots that the glossary missed a system and edits *affected systems* to add it. That edit is the single most valuable byte in the product — more on it below. Then five quality gates run (schema completeness, INVEST, an ambiguity lint that demands measurable anchors, conflict, routing sanity), and the router assigns a queue **with its reasoning in writing**. From the run, verbatim: *Matched 1 signal(s) for "data-platform": "report".* No black-box routing.

What lands in the repo is a ticket a developer can actually work from — this is the top of the real file, `IPR-2026-000001.md`:

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

Every claim carries its provenance and confidence; her original words survive verbatim; every assumption is declared instead of buried. Requester, analyst, reviewer, and developer are looking at the same requirement, each in language they can act on.

**Business users never get technical questions — the system finds the backend itself.** Slots like *affected systems* are marked `askable: false` in the schema (an invariant test enforces that the question composer can never ask them). After confirmation, an enrichment step resolves the business terms against a system-knowledge connector. Try the demo's second scenario — *"I need a report of goods details for product line X with the order info"* — and the routed ticket gains a **System context (auto-discovered)** section: sales orders are `VBAK/VBAP` in the demo SAP S/4HANA system, materials are `MARA`, and there's a custom Z-field, `ZZ_PRIORITY_CODE`, with a type, description, and owning team. Nobody asked the requester a single technical question to get there.

**And that edit she made?** It became an `edit_diffs` row the moment she confirmed — proposed value, corrected value, context. The next intake from a similar context gets her correction injected into its extraction prompt as an exemplar, and the discovered systems land in a knowledge ledger that pre-fills future drafts. A business analyst can sit in the loop where the org wants one — or not; smaller teams go straight to a functional reviewer. Either way the learning compounds: this is model-agnostic improvement that lives in ledgers, not fine-tuned weights, so you can swap the model tomorrow and keep every lesson. Usage is the flywheel.

**Where the ticket goes next.** Tickets write to a local repo or straight to GitHub issues (one config switch); Jira and Azure DevOps are a one-class integration via the same `create_item` protocol, and the roadmap's Builder Agent will attach a second artifact next to the business requirement — a generated implementation scaffold — so an AI coding agent gets exactly the enriched input it needs and a developer reviews two attachments instead of decoding one vague ticket. And the flow runs backwards too: when the assigned team relabels a ticket to a different queue, a webhook feeds that correction into the routing classifier — being wrong is how it gets better.

*(Diagram: the full system in one drawing — `docs/assets/architecture.png` in the repo.)*

**The loops are real, not roadmap.** Every mechanism in that learning rail ships and is tested: corrections become prompt exemplars *and* recalibrate how much the readiness score trusts each kind of inference, per department. Question outcomes reorder what gets asked first. Reroutes retrain routing. Repeated identical corrections surface as glossary proposals a human can accept with one click — the system proposes vocabulary, never installs it. And the corrections ledger doubles as a self-writing eval suite: replay it against the current prompts (`/api/evals/replay`) and you get an accuracy score per slot — regression testing for prompt changes, and per-model benchmarks on *your* domain, with zero hand-written fixtures. A near-duplicate ask gets caught at gate 4 against the org's real history and offered a one-click "attach to the existing requirement" — dedup is where intake tools earn their keep. Intake itself meets people where they already are: one inbound endpoint lets a Slack or Teams bot run the whole flow — numbered answers, then the word "confirm" — while asks are typed on arrival (bug report, data request, new capability) so each gets its own slot schema and question style, and the question budget itself scales with blast radius: trivial asks earn 3 questions, cross-system deadline-driven asks earn up to 9. Enforced in code, as always.

## "But is a local model smart enough?" — the hybrid answer

Let me take the hardest objection head-on, because it's the one I'd raise myself: interpreting what a business user *means* takes real model capability, and on day one a small open-weight model will misread things a frontier model wouldn't. If "run it locally" required pretending otherwise, the pitch would be dead on arrival.

IntakePilot's answer has three layers.

**Layer one: bring any model.** The LLM sits behind a small provider protocol; business logic imports no SDK (a test fails the build if it does). One env var points the system at a deterministic mock (zero-dependency laptop demo), Ollama on your own GPU box, or any OpenAI-compatible endpoint — vLLM, LiteLLM, Azure OpenAI, your internal gateway. If your policy allows a frontier model in the cloud, use it from minute one.

**Layer two: escalation, not either/or.** The configuration most enterprises actually want is hybrid: a local model answers *every* turn, and a stronger model — a cloud frontier endpoint where allowed, or a bigger internal model where not — gets exactly **one attempt when the local model's structured output fails validation twice**. You pay premium tokens only for the hard turns, embeddings never leave the primary, and a fully air-gapped hybrid (small local + big local) works too. This is built and tested, not roadmap: `INTAKEPILOT_LLM_ESCALATION=openai_compat` is the whole setup.

**Layer three — the one that changes the game: daily usage closes the gap.** Every human correction at confirmation becomes an exemplar injected into future extraction prompts; the glossary, precedent index, and system-knowledge base supply the org-specific context that *no* frontier model has. Interpreting "what the business is saying" turns out to be less about raw model IQ and more about knowing that in *your* company "the vendor report" means these two systems, this team, that Z-field. That knowledge accumulates in ledgers on your side of the firewall — so the local model gets measurably smarter on your domain every week, escalations taper toward zero, and your cost curve bends down exactly as your usage goes up. Model-agnostic, because the learning lives in data, not weights: swap the model tomorrow and keep every exemplar.

The security and economics arguments then do the rest. Your business processes — how you handle orders, exceptions, month-end — are core IP, and an intake system sees all of it in employees' own words, all day: in DSAG's research, [data protection ranks second only to cost among cloud concerns for SAP customers](https://www.asug.com/insights/asug-and-dsag-research-shows-customer-perceptions-of-rise-with-sap-cloud-and-sap-s-4hana), and by 2026 [more than half of LLM workloads already run on-premises](https://www.techstoriess.com/open-source-on-premise-llms-deployment-security-cost-and-performance-compared/). Per-token enterprise AI pricing adds up brutally at intake volumes — SAP's own AI Units start around [€7 per unit with allocations heavy users reportedly exhaust within months](https://saplicensingexperts.com/blog/sap-ai-units-explained-the-complete-enterprise-guide-for-2026) — while Apache-2.0 open-weight models ([Qwen, Gemma and friends](https://huggingface.co/blog/daya-shankar/open-source-llm-models-to-run-locally)) keep closing the gap and, on your accumulated context, will eventually be better *for you*. One Docker Compose file deploys the whole stack — Postgres/pgvector, model server, API, UI — on-premises, fully air-gapped, or on any cloud VM. Deliberately boring infrastructure, deliberately portable.

## The SAP elephant in the room

If you live in the SAP world, you know the clock: ECC mainstream maintenance [ends December 31, 2027](https://www.seidor.com/en-us/blog/understanding-sap-ecc-deadlines), and Gartner expects [nearly 17,000 of ~35,000 ECC organizations still to be on it when the deadline hits](https://www.softwareseni.com/what-sap-ecc-end-of-support-actually-means-and-why-17000-companies-are-not-ready/). SAP's answer is RISE — yet in DSAG's surveys [only 12% of members see high value in it, and 42% of 2026 investment still targets S/4HANA *on-premises*](https://www.ibsolution.com/academy/blog_en/dsag-survey-determines-companies-opinion-of-rise-with-sap). The user group has been blunt that [SAP's innovation focus on cloud discriminates against on-premise customers](https://www.constellationr.com/insights/news/dsag-saps-innovation-focus-cloud-discriminates-against-premise-users).

Look at Signavio — genuinely impressive process intelligence, [a Leader in Gartner's Magic Quadrant](https://news.sap.com/2026/05/sap-signavio-gartner-magic-quadrant-process-intelligence-platforms/), now with [Joule as a conversational front end](https://news.sap.com/2026/02/process-conversation-joule-sap-signavio-solutions-generally-available/). All of it cloud-only, all of it metered. Signavio tells you how your processes *run*; nothing in that stack helps the thousands of on-prem and hybrid customers govern how new requirements *enter* — the transformation backlog that the 2027 deadline is about to multiply. Every S/4HANA migration is, at its heart, thousands of requirement conversations: what do we keep, what do we drop, which Z-field still matters and why. That's the upstream gap IntakePilot aims at, and why the demo connector speaks SAP: your requirement doesn't just say "orders" — it knows you mean `VBAK/VBAP` and that `ZZ_PRIORITY_CODE` exists, who owns it, and that someone should decide its fate.

The same logic extends beyond SAP: any enterprise with deep on-prem systems and deep process IP faces the same squeeze — modernization pressure from above, cloud-only AI tooling from vendors, and a security team that (rightly) won't stream internal operations to third-party APIs.

## Honest limits, and what's next

IntakePilot is v0.1 and says so: there's no end-user SSO yet (requirements are session-bound, every admin/ops surface closes with one bearer token, and the GitHub webhook verifies HMAC signatures — but user identity is your reverse proxy's job for now), the Jira target is next up, and the "Builder Agent" that auto-attaches code scaffolds to tickets is specified but not shipped. What *is* shipped is tested hard — 95 tests pin the invariants: the question budget, the never-overwrite-human-input rule, append-only versioning, the duplicate gate, ownership binding, and the no-SDK-in-business-logic rule, including a test where a deliberately malicious LLM tries to break the budget and can't.

The architecture principle underneath it all: **the LLM is a component, never in control.** Deterministic code decides budgets, merges, gates, and routing; the model proposes, code disposes. I think that's the only way AI earns trust in enterprise workflows — and the only way the system keeps working when you swap models underneath it, which, in the age of fast-improving open weights, you will.

The code, architecture diagrams, and a five-minute zero-dependency demo (`make dev` — mock LLM, no downloads) are on GitHub: **[github.com/YOUR-USERNAME/intakepilot]** *(update after pushing)*. If your team drowns in requirements ping-pong — or you're staring down an S/4 migration backlog — I'd genuinely like to hear what would make this useful to you.

---

*Sources: [Atlassian — Agents in Jira](https://community.atlassian.com/forums/Jira-articles/Introducing-Agents-in-Jira/ba-p/3194583) · [DevOps.com — Copilot coding agent for Jira](https://devops.com/github-copilot-coding-agent-for-jira-connects-planning-to-pull-requests-without-leaving-your-workflow/) · [Augment Code — ticket-to-PR quality ceiling](https://www.augmentcode.com/guides/jira-ticket-to-pull-request-automation) · [ASUG/DSAG cloud perception research](https://www.asug.com/insights/asug-and-dsag-research-shows-customer-perceptions-of-rise-with-sap-cloud-and-sap-s-4hana) · [DSAG on RISE value & investment plans](https://www.ibsolution.com/academy/blog_en/dsag-survey-determines-companies-opinion-of-rise-with-sap) · [Constellation — DSAG on cloud-first innovation](https://www.constellationr.com/insights/news/dsag-saps-innovation-focus-cloud-discriminates-against-premise-users) · [SEIDOR — ECC deadlines](https://www.seidor.com/en-us/blog/understanding-sap-ecc-deadlines) · [SoftwareSeni — 17,000 not ready](https://www.softwareseni.com/what-sap-ecc-end-of-support-actually-means-and-why-17000-companies-are-not-ready/) · [SAP Licensing Experts — AI Units](https://saplicensingexperts.com/blog/sap-ai-units-explained-the-complete-enterprise-guide-for-2026) · [SAP News — Signavio in Gartner MQ](https://news.sap.com/2026/05/sap-signavio-gartner-magic-quadrant-process-intelligence-platforms/) · [SAP News — Joule with Signavio GA](https://news.sap.com/2026/02/process-conversation-joule-sap-signavio-solutions-generally-available/) · [TechStoriess — on-prem LLM share](https://www.techstoriess.com/open-source-on-premise-llms-deployment-security-cost-and-performance-compared/) · [Hugging Face — open models to run locally](https://huggingface.co/blog/daya-shankar/open-source-llm-models-to-run-locally)*
