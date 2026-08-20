# Existing Systems Research

**Method:** broad web search across the categories the Chairman specified, followed by **primary verification** — every licence below was read from the project's own `LICENSE` file, fetched over git, not from a badge, a blog, or a comparison article.

**Date of verification:** 2026-08-20. Last-commit dates are from each repository's HEAD on that date.

**Why primary verification mattered:** two widely-repeated claims turned out to be wrong, and both would have been expensive (§3).

---

## 1. Verified licence and activity table

All rows fetched via blobless clone and `git show HEAD:LICENSE`.

| Project | Verified licence | Last commit | Notes |
|---|---|---|---|
| **All-Hands-AI/OpenHands** | **MIT** | 2026-08-20 | Clean. The single strongest component found |
| **assafelovic/gpt-researcher** | **Apache-2.0** | 2026-07-14 | Clean |
| **browser-use/browser-use** | **MIT** | 2026-08-19 | Clean |
| **letta-ai/letta** | **Apache-2.0** | 2026-08-15 | Clean |
| **mem0ai/mem0** | **Apache-2.0** | 2026-08-20 | Clean |
| **temporalio/temporal** | **MIT** | 2026-08-20 | Clean |
| **apache/superset** | **Apache-2.0** | 2026-08-20 | Clean, no open-core asterisk |
| **killbill/killbill** | **Apache-2.0** | 2026-08-19 | Clean |
| **apify/crawlee** | **Apache-2.0** | 2026-08-20 | Clean |
| **coollabsio/coolify** | **Apache-2.0** | 2026-08-20 | Clean |
| **calcom/cal.com** | **MIT** (root) | 2026-08-08 | Has `ee/`; root is MIT |
| **PostHog/posthog** | **MIT core + `ee/` separate** | 2026-08-20 | Split licence, verbatim below |
| **chatwoot/chatwoot** | **MIT core + `enterprise/` separate** | 2026-08-20 | Split licence |
| **activepieces/activepieces** | **MIT core + `packages/ee/` separate** | 2026-08-20 | Split licence |
| **BerriAI/litellm** | **MIT core + `enterprise/` separate** | 2026-08-20 | Split licence |
| **langfuse/langfuse** | **Split; © ClickHouse, Inc.** | 2026-08-20 | Copyright now sits with ClickHouse — ownership changed |
| **growthbook/growthbook** | **Split** | 2026-08-19 | Core + commercial directory |
| **Dokploy/dokploy** | **Split** | 2026-08-19 | Core + commercial |
| **twentyhq/twenty** | **AGPL-3.0** ("mostly") | 2026-08-20 | Network clause — see §4 |
| **getlago/lago** | **AGPL-3.0** | 2026-08-18 | |
| **makeplane/plane** | **AGPL-3.0** | 2026-08-16 | |
| **espocrm/espocrm** | **AGPL-3.0** | 2026-08-18 | |
| **knadh/listmonk** | **AGPL-3.0** | 2026-08-17 | |
| **firecrawl/firecrawl** | **AGPL-3.0** | 2026-08-20 | |
| **searxng/searxng** | **AGPL-3.0** | 2026-08-19 | |
| **go-vikunja/vikunja** | **AGPL-3.0** | 2026-08-20 | |
| **documenso/documenso** | **AGPL-3.0** | 2026-08-19 | |
| **metabase/metabase** | **AGPL-3.0** (+ paid tiers) | 2026-08-20 | `LICENSE-AGPL.txt` |
| **mautic/mautic** | **GPL-3.0** | 2026-08-20 | |
| **odoo/odoo** | **LGPL-3.0** (community) | 2026-08-20 | Enterprise is separate |
| **langgenius/dify** | **Modified Apache-2.0** | 2026-08-20 | "with additional conditions" |
| **n8n-io/n8n** | ⚠️ **Sustainable Use Licence — NOT open source** | 2026-08-20 | §2 |
| **akaunting/akaunting** | ⚠️ **Business Source Licence (BUSL)** | 2026-08-19 | §3 |
| **invoiceninja/invoiceninja** | ⚠️ **Elastic Licence 2.0** | 2026-08-12 | §3 |

Every project above had a commit within the last six weeks. None is abandoned.

---

## 2. n8n — the licence everyone calls open source

`LICENSE.md`, verbatim limitation clause:

> You may use or modify the software **only for your own internal business purposes** or for non-commercial or personal use. You may distribute the software or provide it to others only if you do so free of charge for non-commercial purposes.

Plus: files containing `.ee.` in the filename or `.ee` in the dirname require a paid Enterprise Licence, and **branches other than `master` are not licensed at all**.

**What this means for us — and it is good news, with one boundary:**

| Use | Permitted? |
|---|---|
| Running n8n to automate **our own company's** internal operations | ✅ Yes — this is exactly "internal business purposes" |
| Using n8n to orchestrate work that produces our product | ✅ Yes, while n8n itself is not the thing customers receive |
| Offering an n8n-powered workflow product **to customers** | ❌ No |
| Reselling or hosting n8n for third parties | ❌ No |

So n8n is usable as **internal glue** and unusable as **product**. That distinction generalises, and it is the core of §4.

Alternatives if we would rather avoid the question entirely: **Activepieces** (MIT core), **Temporal** (MIT), **Windmill** (AGPL-3.0).

---

## 3. Two corrections to widely-repeated claims

Both came from comparison articles. Both are wrong. Both would have mattered.

**Akaunting is not GPL-3.0.** Its `LICENSE.txt` opens:

> License text copyright (c) 2020 MariaDB Corporation Ab… **"Business Source License"**

BUSL is a source-available licence with a production-use restriction that converts to open source only after a change date. Adopting it as our accounting system on the belief it was GPL would have been a licensing error discovered late.

**Invoice Ninja is not open source.** Its `LICENSE` opens:

> **Elastic License 2.0 (ELv2)**

ELv2 forbids providing the software to third parties as a managed service and forbids circumventing licence keys. Fine to run internally; not fine as a product component.

**Conclusion:** the accounting/invoicing category is the most licence-hostile area we surveyed. The practical answer is to avoid it — use **Stripe's own invoicing** for revenue and keep our own ledger, rather than self-hosting an accounting package. Kill Bill (Apache-2.0) is the clean fallback if real subscription billing is needed.

---

## 4. The distinction that unlocks almost everything

Copyleft is not a blanket obstacle. AGPL's network clause triggers on **conveying a modified version to users over a network**. Running an unmodified AGPL application as our own internal back office, for our own company, does not trigger source-disclosure obligations to the outside world.

So the decisive question is not "what licence is it?" but **"is this thing our back office, or is it our product?"**

| | Back office (we are the user) | Product (customers are the users) |
|---|---|---|
| Examples | CRM, helpdesk, analytics, BI, email sender, deploy panel, workflow engine | The SaaS a venture sells |
| Acceptable licences | **MIT, Apache-2.0, AGPL, GPL, LGPL, BUSL, ELv2, n8n SUL** — nearly everything | **MIT, Apache-2.0, BSD only** |
| Integration style | Separate service, called over its HTTP API. Unmodified where possible | Our own code |
| Why it works | We are the end user, not a distributor | We distribute, so permissive is required |

Two rules keep this true in practice:

1. **Do not fork back-office software.** Configure it, call its API, leave the source alone. Forking an AGPL CRM and exposing it to customers is where obligations begin.
2. **Never let a back-office component become part of the product surface.** If a venture's users would touch it directly, it is a product component and the permissive-only column applies.

This converts most "licensing problems" into non-problems and satisfies the Chairman's instruction that licensing must not become an excuse to abandon functionality.

---

## 5. Category findings

### 5.1 Autonomous-company projects — the honest assessment

Searched specifically: `autonomous startup`, `AI venture studio`, `AI startup in a box`, `AI employees`, `autonomous software factory`.

Found: **Auto-Co** (14 persona agents driving Claude Code in a bash loop), **VentureNode** (LangGraph + Notion; idea → roadmap), **FounderFlow** (Langflow personas producing documents), **Venture Studio OS** (a documented methodology, not software), plus Paperclip and Claw-Empire from the earlier audit.

**Every one of them stops before revenue.** They generate plans, documents, roadmaps and landing pages. None discovers a paying customer, takes money, or reports profit. The gap between "simulates a company" and "operates a business" is the entire distance we care about, and no existing project crosses it.

**Implication:** there is no system to adopt at the *top* of the stack. There are excellent systems for every *layer beneath* it. Our build should be the thin executive layer, and nothing else.

### 5.2 Agent frameworks

LangGraph (production-grade, stateful, human-in-the-loop checkpoints), CrewAI (fast to start), **Microsoft moved AutoGen to maintenance mode** in favour of Microsoft Agent Framework — a caution against betting on framework fashion.

**Finding:** we do not need a multi-agent framework for the first loop. One competent agent per task, invoked by a workflow engine, is simpler and cheaper. Revisit only if a concrete task fails without it.

### 5.3 Coding agents — the strongest category

**OpenHands (MIT)** is the clear pick: ~70k stars, 490+ contributors, sandboxed Docker execution, Kubernetes support, ~68% SWE-bench Verified with a frontier model, active daily. Aider (Apache-2.0) is a capable pair-programmer but not an autonomous task runner. This capability is genuinely solved.

### 5.4 Research

GPT Researcher (Apache-2.0) — planner/executor/publisher split, mature, actively maintained. Pair with **SearXNG** (AGPL, self-hosted meta-search, no API key) to avoid per-query search costs, and **Crawlee** (Apache-2.0) or Firecrawl (AGPL) for extraction.

### 5.5 Analytics, experimentation, flags

**PostHog** covers analytics + feature flags + A/B tests + surveys + session replay in one MIT-core system. Using one system for four capabilities is the highest-leverage consolidation available. Caveat: the full self-hosted stack (ClickHouse, Kafka, Redis) is heavy — PostHog Cloud's free tier is the pragmatic start.

### 5.6 CRM, support, email

Twenty (AGPL, modern) or EspoCRM (AGPL, ~90% configurable without forking — notable, since not forking is exactly our rule). Chatwoot (MIT core) for support. Listmonk (AGPL, light) for sending; Mautic (GPL) only if full automation flows are needed.

### 5.7 Money

**Do not self-host a payment rail.** Stripe's API is hosted, ToS-governed, and has no licence question. Kill Bill (Apache-2.0) is the clean self-hosted option if usage-based billing is needed later; Lago is AGPL and equally fine as back office.

### 5.8 Infrastructure

Coolify (Apache-2.0, ~57k stars, 280+ one-click services, multi-server) turns a plain VPS into a deploy target. LiteLLM (MIT core) for provider routing and per-key spend caps. Langfuse (MIT core) for tracing — noting its copyright now sits with ClickHouse, Inc., which is a governance change worth tracking.

---

## 6. Ranking, deliberately not by stars

Applied to every candidate, in the Chairman's order: functional completeness → evidence it works → maturity → activity → integration capability → licence → resource cost → security → modifiability → commercial viability.

Stars were used only as a weak tie-breaker. What actually decided rankings:

- **An HTTP API** beats a bigger project without one. Integration capability is the whole game when the plan is composition.
- **Configurable without forking** (EspoCRM) beats more features requiring a fork, because forking is what creates licence obligations.
- **One system covering four capabilities** (PostHog) beats four best-in-class systems, because every integration is a failure point we must operate.
- **Resource cost is a hard filter**, not a preference — several otherwise-strong candidates (Superset on Kubernetes, full self-hosted PostHog) are ruled out for the first loop on memory alone.

---

## 7. What we found no adequate existing system for

Searched, found nothing suitable:

| Need | Why nothing fits |
|---|---|
| **Bounded capital allocation across ventures** | Venture-studio tooling is spreadsheets and methodology docs. No software enforces "spend up to £X on this thesis, then stop" |
| **Tiered approval gateway with an evidence trail** | Workflow engines have approval *steps*; none has risk tiers, spend caps and a tamper-evident record tied to a decision |
| **A Chairman console over a portfolio** | BI tools show data; none models "which ventures are alive, what did they cost, what did we learn" |

These three are the build list. They are small, they are glue, and they are the only place our own code earns its keep.
