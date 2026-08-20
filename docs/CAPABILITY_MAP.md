# Capability Map

**Objective (fixed, Chairman-set):** operate a functioning autonomous business.
**Not the objective:** build an impressive AI framework.

**Date:** 2026-08-20
**Companions:** [`EXISTING_SYSTEMS_RESEARCH.md`](EXISTING_SYSTEMS_RESEARCH.md) · [`BUILD_BUY_ADAPT_MATRIX.md`](BUILD_BUY_ADAPT_MATRIX.md) · [`AUTONOMY_GAP_ANALYSIS.md`](AUTONOMY_GAP_ANALYSIS.md) · [`FINAL_SYSTEM_COMPOSITION.md`](FINAL_SYSTEM_COMPOSITION.md)

---

## 0. How to read this

63 capabilities were specified. We are **not building 63 subsystems**. This map exists to answer one question per capability: *does working software already exist that we can run or call?*

Every capability is tagged:

| Tag | Meaning |
|---|---|
| **L1** | Required for the **first complete business loop**. Nothing ships without it. |
| **L2** | Required once the first venture has customers. |
| **L3** | Required at portfolio scale (multiple ventures). |
| **CH** | **Chairman-only.** Cannot or must not be automated — see `AUTONOMY_GAP_ANALYSIS.md`. |

The first loop is: **DISCOVER → VALIDATE → BUILD → MARKET → SELL → REVENUE → MEASURE → IMPROVE.**

Only **17 of 63** capabilities are L1. That is the whole point of this document.

---

## 1. The first loop (L1) — the minimum viable company

| # | Capability | Loop phase | Existing system exists? |
|---|---|---|---|
| 6 | Web research | DISCOVER | Yes — GPT Researcher, SearXNG, Firecrawl/Crawlee |
| 7 | Market intelligence | DISCOVER | Yes — same research stack |
| 9 | Customer discovery | DISCOVER | Partial — research stack + manual channels |
| 10 | Idea generation | DISCOVER | Yes — LLM directly; no framework needed |
| 11 | Opportunity evaluation | VALIDATE | Partial — scoring is thin glue over an LLM |
| 44 | Experimentation | VALIDATE / IMPROVE | Yes — PostHog experiments |
| 26 | Product management | BUILD | Yes — Plane / GitHub Issues |
| 27–28 | Software engineering / autonomous coding | BUILD | **Yes — OpenHands (MIT), strongest single component** |
| 29 | GitHub management | BUILD | Yes — GitHub MCP / API |
| 30 | Testing | BUILD | Yes — repo-native CI |
| 31 | Deployment | BUILD | Yes — Coolify (Apache-2.0) |
| 22 | Content generation | MARKET | Yes — LLM directly |
| 20 | Email automation | MARKET | Yes — Listmonk / Mautic |
| 17 | CRM | SELL | Yes — Twenty / EspoCRM |
| 52 | Payments | REVENUE | Yes — Stripe API (hosted; no licence question) |
| 39 | Analytics | MEASURE | Yes — PostHog (MIT core) |
| 34 | Workflow automation | glue | Yes — n8n / Windmill / Temporal / Activepieces |

**Plus three that hold it together and have no off-the-shelf answer for our shape:**

| # | Capability | Why it is L1 |
|---|---|---|
| 43 | Decision making (bounded, budgeted) | The loop needs something that decides what to do next under a capital limit |
| 62 | Capital allocation | The Chairman funds ventures; something must allocate and stop |
| 56 | Audit logging | Deployer liability (§ `AUTONOMY_GAP_ANALYSIS`) makes an evidence trail non-optional |

---

## 2. Full capability map

### 2.1 Executive and orchestration

| # | Capability | Tier | Notes |
|---|---|---|---|
| 1 | CEO / executive agent | L1 | Thin planner over a bounded action set. Candidates exist but are demos, not operating systems |
| 2 | Company orchestration | L1 | Workflow engine + our policy layer |
| 3 | Agent management | L2 | Config, not a subsystem |
| 4 | Multi-agent collaboration | L2 | **Deliberately deferred.** Single competent agent per task beats a committee at our scale |
| 43 | Decision making | L1 | Bounded action set + policy tiers |
| 48 | Employee/agent management | L3 | Only meaningful with many concurrent agents |
| 49 | Project management | L1 | Plane / GitHub Issues |
| 35 | Scheduling | L1 | cron / systemd timer / workflow engine |
| 36 | Notifications | L1 | ntfy / Apprise / Telegram |

### 2.2 Discovery and intelligence

| # | Capability | Tier | Notes |
|---|---|---|---|
| 5 | Autonomous research | L1 | GPT Researcher (Apache-2.0) |
| 6 | Web research | L1 | SearXNG + Firecrawl/Crawlee |
| 7 | Market intelligence | L1 | Research stack + public data |
| 8 | Competitor intelligence | L2 | Scheduled re-runs of the research stack + changedetection.io |
| 9 | Customer discovery | L1 | Research + direct outreach; the weakest automated link |
| 10 | Idea generation | L1 | LLM. **Do not build a framework for this** |
| 11 | Opportunity evaluation | L1 | Rubric + LLM scoring; thin |
| 57 | Investor research | L3 | Not needed while self-funded |
| 58 | Fundraising preparation | CH/L3 | Chairman-led by necessity |

### 2.3 Product and engineering

| # | Capability | Tier | Notes |
|---|---|---|---|
| 26 | Product management | L1 | Plane (AGPL) or GitHub Issues |
| 27 | Software engineering | L1 | OpenHands |
| 28 | Autonomous coding | L1 | OpenHands; Aider as fallback |
| 29 | GitHub management | L1 | GitHub API/MCP |
| 30 | Testing | L1 | Repo-native (pytest/vitest) + CI |
| 31 | Deployment | L1 | Coolify |
| 32 | Browser automation | L2 | browser-use / Playwright MCP (both permissive) |
| 33 | Computer use | L3 | Avoid. High risk, low marginal value for a SaaS venture |

### 2.4 Go-to-market

| # | Capability | Tier | Notes |
|---|---|---|---|
| 21 | Marketing | L1 | LLM + Listmonk |
| 22 | Content generation | L1 | LLM directly |
| 23 | SEO | L2 | Content + technical checks; no self-hosted system worth adopting |
| 24 | Social media | L2 | Postiz (AGPL) or direct APIs |
| 18 | Lead generation | L2 | **Legally constrained** — see gap analysis |
| 19 | Outbound sales | L2 | Constrained by anti-spam law and platform ToS |
| 20 | Email automation | L1 | Listmonk (AGPL) — transactional + campaigns |
| 17 | CRM | L1 | Twenty (AGPL) or EspoCRM (AGPL) |
| 25 | Customer support | L2 | Chatwoot (MIT core + `enterprise/`) |

### 2.5 Money

| # | Capability | Tier | Notes |
|---|---|---|---|
| 52 | Payments | L1 | **Stripe API.** Do not self-host a payment rail |
| 51 | Invoicing | L2 | Stripe Invoicing, or Kill Bill (Apache-2.0) |
| 12 | Financial analysis | L1 | Small amount of our own code over ledger data |
| 13 | Accounting | L2 | **Licensing is hostile here** — see research doc |
| 14 | Bookkeeping | L2 | Same |
| 15 | Budgeting | L1 | Our own; it is the capital-allocation rule set |
| 16 | Forecasting | L2 | Simple models over real revenue data |
| 46 | Pricing optimization | L2 | PostHog experiments + Stripe price objects |
| 47 | Revenue optimization | L2 | Same |
| 62 | Capital allocation | L1 | **Ours.** No existing system does bounded venture funding |
| 63 | Profit reporting | L2 | Metabase / Superset over the ledger |
| 50 | Procurement | CH | Subscriptions are financial commitments |

### 2.6 Measurement and learning

| # | Capability | Tier | Notes |
|---|---|---|---|
| 39 | Analytics | L1 | PostHog |
| 40 | Business intelligence | L2 | Metabase (AGPL) or Superset (Apache-2.0) |
| 44 | Experimentation | L1 | PostHog |
| 45 | A/B testing | L1 | PostHog or GrowthBook |
| 41 | Company memory | L2 | Letta / mem0 (both Apache-2.0), or Postgres + FTS |
| 42 | Knowledge graph | L3 | **Probably never.** Retrieval over a few thousand records does not need a graph |
| 11 | Learning from outcomes | L2 | Structured retrospectives writing back to memory |

### 2.7 Governance, legal, risk

| # | Capability | Tier | Notes |
|---|---|---|---|
| 56 | Audit logging | L1 | **Ours** — liability makes this load-bearing |
| 55 | Security | L1 | Secrets management, egress control, least privilege |
| 54 | Compliance monitoring | L2 | Checklists + alerts, not a product |
| 53 | Legal/document workflows | CH/L2 | Documenso (AGPL) for signature *workflow*; the Chairman signs |
| 37 | Document generation | L2 | Pandoc / python-docx |
| 38 | Presentation generation | L3 | Low value. Avoid |

### 2.8 Portfolio

| # | Capability | Tier | Notes |
|---|---|---|---|
| 59 | Portfolio management | L3 | Meaningful only at venture ≥ 2 |
| 60 | Venture creation | L3/CH | Software venture: automatable. Legal entity: Chairman |
| 61 | Venture shutdown | L3 | Automatable for software; Chairman for obligations |

---

## 3. Capabilities the brief did not list but the goal requires

Discovered while mapping. Without these the loop does not close.

| Capability | Tier | Why it is required |
|---|---|---|
| **LLM cost control and routing** | **L1** | An autonomous company that cannot cap its own inference spend has no cost floor. LiteLLM |
| **LLM observability / tracing** | **L1** | You cannot debug or improve a loop you cannot see. Langfuse |
| **Secrets management** | **L1** | Many services, many credentials, one agent. Leakage is the top security risk |
| **Domain + DNS + email deliverability** | **L1** | A venture with no domain and unauthenticated email cannot sell. SPF/DKIM/DMARC is a hard prerequisite for capability 20 |
| **Legal entity + banking** | **CH** | Prerequisite for capability 52. Chairman-only, KYC-bound |
| **Backup and disaster recovery** | **L1** | The company's entire state is in a handful of databases |
| **Human escalation channel** | **L1** | The approval path must work on a phone, or autonomy stalls |
| **Idempotency / replay safety** | **L1** | An agent retrying a charge or an email send twice is a real, expensive failure mode |
| **Rate-limit and ToS compliance per integration** | **L1** | A banned Stripe or email account halts revenue entirely |

---

## 4. What this map concludes

1. **Existing software covers most of it.** Of 63 capabilities, roughly 45 have a credible existing system; ~9 need only thin glue over an LLM; **fewer than 6 require anything we would call building.**
2. **The genuine gap is not capability — it is control.** No existing system does *bounded authority over a portfolio with capital limits and an evidence trail*. That is the only thing worth building, and it is small.
3. **The binding constraints are legal and commercial, not technical.** Payment ToS, anti-spam law, deployer liability and platform terms limit autonomy far more than any missing repository does.
4. **Multi-agent collaboration is deferred on purpose.** It is where this class of project usually burns its time, and it is not on the critical path to revenue.
