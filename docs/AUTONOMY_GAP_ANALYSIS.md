# Autonomy Gap Analysis

**Question:** the Chairman wants the AI to run normal operations autonomously, intervening only for major capital, above-limit payments, legal commitments, equity, major strategy, and irreversible high-risk actions. **How much of that is actually achievable, and what stops the rest?**

**Answer up front:** most of it is achievable. The limits that remain are **legal, contractual and financial-infrastructure limits — not technical ones, and not preferences of mine.** Where a limit is real I say what it is and cite why; where the earlier plan was more restrictive than the law requires, I say so and relax it.

---

## 1. A correction to the earlier project position

The earlier `DEVELOPMENT_PLAN.md` treated money movement and contract formation as **permanently prohibited, with no approval path**. Research into the actual legal position shows that was stricter than the law requires, and stricter than the Chairman's objective needs.

**What the law actually says:**

- **AI-formed contracts are valid.** The US ESIGN Act provides that a contract may not be denied legal effect solely because its formation involved the action of an electronic agent. This was settled decades ago. The open question was never validity.
- **The deploying company bears the liability.** California **AB 316, effective 1 January 2026**, precludes a defendant from using an AI system's autonomous operation as a defence. The "the AI did it" defence is foreclosed.
- **Regulators expect bounded authority, not a human on every action.** The Bank of England's Deputy Governor stated (30 June 2026) that requiring a human in the loop for every agent action is unrealistic, particularly in payments.
- **Legal guidance converges on four requirements** for an agent acting for a business: **defined authority** (what, and up to what amount), **attribution** (whose acts these are), **oversight checkpoints** (which actions need a human), and **an evidence trail**.

**So the correct control is not prohibition — it is bounded authority with a record.** That is precisely what the Chairman asked for, and it is what we will build. The revised position:

| Action | Old position | **Revised position** |
|---|---|---|
| Spend money below a Chairman-set limit | Prohibited outright | **Autonomous**, within per-transaction / daily / per-venture caps, fully logged |
| Spend above the limit | Prohibited | **Chairman approval** |
| Accept click-through ToS for a low-cost SaaS tool | Prohibited | **Autonomous below the spend cap**, logged — this is ordinary agency |
| Sign a negotiated contract, lease, employment or debt agreement | Prohibited | **Chairman only** — unchanged |
| Issue equity or securities | Prohibited | **Chairman only** — unchanged |
| Move money out of the business (withdrawals) | Prohibited | **Chairman only** — unchanged |

The liability point cuts both ways and is worth stating plainly: because the Chairman is fully liable for what the system does, the **evidence trail is not bureaucracy — it is the only thing that makes autonomy defensible after the fact.** That is why audit logging is L1 and one of only three things we build ourselves.

---

## 2. What can be fully autonomous today

No legal, contractual or technical obstacle. These should run without asking.

| Capability | Notes |
|---|---|
| Market and competitor research | Public sources, robots.txt respected |
| Idea generation, scoring, ranking | Pure computation over an LLM |
| Writing specs, code, tests | OpenHands; output arrives as pull requests |
| Deploying to preview environments | Disposable by definition |
| Drafting all marketing and sales content | Drafting is not publishing |
| Product analytics, experiments, A/B tests | PostHog |
| Reading email and support inboxes, drafting replies | |
| Updating CRM records, logging activity | |
| Recording ledger entries, reconciliation, reporting | Reading and recording, not moving |
| Monitoring revenue, cost, runway; raising alerts | |
| Running retrospectives, updating priors and memory | |
| Buying/renewing infrastructure below the spend cap | Domains, VPS, API credits — ordinary operations |
| Pricing experiments within a Chairman-set band | Stripe price objects |

## 3. What is genuinely constrained — and by what

These are external facts, not caution. Each names the actual constraint.

| Area | The real constraint | What we can still do |
|---|---|---|
| **Company formation** | Incorporation requires an identified natural person; registries do not accept an AI as incorporator | AI prepares everything; Chairman signs |
| **Bank account** | KYC/AML requires identity verification of a human beneficial owner. No bank onboards an agent | Chairman opens it; AI gets **read-only** access plus a limited-authority card |
| **Payment processing (Stripe)** | Account is held by a legal person; ToS assign responsibility to the account holder. Automation abuse or high disputes → freeze, which halts revenue entirely | AI operates the account via API within limits; Chairman owns it. **Treat account health as a top operational risk** |
| **Employment** | Employment contracts are negotiated commitments with statutory duties | Contractors via marketplaces, Chairman-approved |
| **Cold outreach** | GDPR/PECR, CAN-SPAM, CASL: consent, disclosure, opt-out, sender identification. **Purchased lists are not lawful bases** | Inbound, opt-in, content marketing, and warm outreach to consenting contacts |
| **Platform automation limits** | LinkedIn, Google, Meta ToS forbid automated account actions. Tools exist (e.g. stealth automation) — using them risks permanent bans | Official APIs only. Never use anti-detection tooling |
| **Automated decisions about people** | GDPR Art. 22 restricts solely-automated decisions with legal/significant effects | Keep humans in decisions affecting individuals (hiring, credit, exclusion) |
| **Financial/medical/legal advice as product** | Regulated activity in most jurisdictions | Avoid these verticals for venture #1 |
| **Tax filing** | Requires a responsible person's signature | AI prepares; accountant and Chairman file |

## 4. The autonomy gap, quantified

Against the Chairman's 30-item end-state list:

| Band | Count | Items |
|---|---|---|
| **Fully autonomous** | **21** | Discovery, research, customer problems, idea generation, evaluation, product design, building software, engineering management, marketing creation, support, operations, revenue/cost monitoring, pricing optimisation, experiments, agent management, knowledge, learning, competitor monitoring, new opportunities, day-to-day ops, financial reporting |
| **Autonomous within limits** | **5** | Finding customers (lawful channels only), sales (self-serve yes; negotiated no), managing finances (record + spend below cap), creating products, reinvesting profits (rule-based, below cap) |
| **Chairman-gated** | **4** | Creating new ventures (legal entity), capital above limits, legal commitments, profit withdrawal |

**≈70% fully autonomous, ≈87% autonomous or near-autonomous.** The residual 13% is where the law puts a natural person, and no amount of engineering removes it.

Importantly: **none of the gated items is in the first business loop.** Venture #1 can run as a product line under the Chairman's existing legal entity, so incorporation is not on the critical path.

## 5. The gaps that are ours to close

Not legal — just missing software. These are the three class-E builds.

| Gap | Why nothing off the shelf does it |
|---|---|
| **Spend authority with hard caps** | LiteLLM caps *LLM* spend well. Nothing caps *company* spend across Stripe, hosting, domains and ads with one policy |
| **Approval gateway with tiers and expiry** | Workflow engines have approval steps; none has risk tiers, cooling-off, deny-by-default expiry and a signed record |
| **Decision record tied to evidence and cost** | The artefact that answers "why did the company do this, on what evidence, at what cost, under which policy" — the exact thing deployer liability requires |

## 6. The real risks to autonomy — ranked by likelihood, not drama

The failure modes that actually end autonomous companies:

| Rank | Risk | Why it is first | Mitigation |
|---|---|---|---|
| 1 | **Stripe/email account suspension** | Revenue and customer contact stop instantly. Triggered by disputes, spam complaints, or ToS-violating automation | Conservative sending, real opt-in, dispute monitoring as a first-class metric, no grey-area automation |
| 2 | **Runaway spend** | Faster than any other failure. An agent loop can spend a month's budget in an hour | Hard caps at every level; LiteLLM per-key budgets; tick-bounded execution |
| 3 | **Nothing anyone wants** | The most likely quiet failure: the loop runs, produces, and no one pays | Kill criteria defined before each experiment; revenue as the only real metric |
| 4 | **Prompt injection via scraped content** | Research reads hostile pages by design | Fetched content is data, never instructions; capability tokens; approval for outward actions |
| 5 | **Legal exposure from outreach** | GDPR/CAN-SPAM penalties, and reputational damage | Lawful channels only; disclosure; honour opt-outs |
| 6 | **Silent degradation** | Loop keeps running while quality collapses | Langfuse tracing; retrospectives; Chairman console |

Note what is *not* in the top three: the AI doing something dramatic and illegal. The realistic risks are **getting banned, overspending, and building something nobody wants** — ordinary business failure modes, which is what an autonomous business should expect.

## 7. Bottom line

The Chairman's target end-state is **achievable to roughly 87%** with existing software plus about a thousand lines of policy code. The residual is fixed by law, not by engineering.

The earlier absolute prohibition on money movement was stricter than necessary and is replaced by **bounded spend authority with hard caps and an evidence trail** — which is both what the Chairman asked for and what current legal guidance actually recommends.

Two limits stay absolute, and they are the Chairman's own: **legal commitments beyond routine click-through terms, and withdrawal of money from the business.**
