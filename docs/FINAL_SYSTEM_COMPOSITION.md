# Final System Composition

> **What existing systems can we combine to get as close as possible to a fully autonomous AI-run company?**

**Answer:** thirteen existing systems, one hosted API, and about a thousand lines of our own policy code. That combination closes the loop **DISCOVER → VALIDATE → BUILD → MARKET → SELL → REVENUE → MEASURE → IMPROVE** and reaches roughly **87% autonomy** against the Chairman's end-state list.

**Date:** 2026-08-20 · Licences verified from primary sources ([`EXISTING_SYSTEMS_RESEARCH.md`](EXISTING_SYSTEMS_RESEARCH.md))

---

## 1. The stack

```
CHAIRMAN  ─── phone: approvals, alerts, portfolio view
    │
┌───▼──────────────────────────────────────────────────┐
│  OURS (~1,000 LOC)                                   │
│  decision loop · spend caps · approval gateway ·     │
│  audit trail · Chairman console                      │
│  + the existing port layer as integration boundary   │
└───┬──────────────────────────────────────────────────┘
    │ HTTP APIs only — nothing forked, nothing vendored
    ├─ LiteLLM ──── LLM routing + per-key spend caps
    ├─ Langfuse ─── tracing, cost, quality
    ├─ GPT Researcher + SearXNG ─── DISCOVER / VALIDATE
    ├─ OpenHands ── BUILD (PRs only)
    ├─ GitHub ───── code, review, CI
    ├─ Coolify ──── deploy to VPS
    ├─ Listmonk ─── MARKET (email)
    ├─ EspoCRM ──── SELL
    ├─ Stripe ───── REVENUE
    ├─ PostHog ──── MEASURE (analytics, flags, A/B, surveys)
    ├─ Chatwoot ─── support (L2)
    ├─ Metabase ─── profit reporting (L2)
    └─ n8n ──────── scheduling / glue (internal use only)
```

**One rule holds the whole thing together:** every third-party system runs **unmodified, as a separate service, called over HTTP**. We never fork and never vendor. That keeps AGPL, BUSL and n8n's SUL obligations inert, and it means any component can be swapped without touching the others.

---

## 2. Subsystem detail

### 2.1 Autonomous coding — the strongest component

| Field | |
|---|---|
| **CAPABILITY** | Software engineering, autonomous coding (27, 28) |
| **BEST EXISTING SYSTEM** | **OpenHands** |
| **REPOSITORY** | `github.com/All-Hands-AI/OpenHands` |
| **LICENCE** | **MIT** — verified from `LICENSE`, HEAD 2026-08-20 |
| **MATURITY** | High. ~70k stars, 490+ contributors, v1.6.0 shipped Kubernetes support, daily commits |
| **WHAT IT ALREADY DOES** | Reads an issue, plans, writes code, runs commands, executes tests, opens PRs. Sandboxed Docker execution. ~68% SWE-bench Verified with a frontier model |
| **WHAT WE MODIFY** | Nothing. Headless mode, our task text in, PR out |
| **WHAT IT IS MISSING** | No concept of business value or budget — it does not know when a feature is not worth building. Our loop decides that |
| **HOW IT CONNECTS** | Headless CLI / REST; GitHub token scoped to PR creation, never merge |
| **RESOURCES** | Docker + 2–4 GB during a run. **Too heavy to run continuously on the Chairman's machine — run on the VPS or on demand** |
| **LEGAL** | MIT, clean. Generated code needs licence review before shipping |
| **CONFIDENCE** | **High.** Best-evidenced component in the survey |

### 2.2 Research and validation

| Field | |
|---|---|
| **CAPABILITY** | Autonomous research, web research, market and competitor intelligence (5–8) |
| **BEST EXISTING SYSTEM** | **GPT Researcher** + **SearXNG** + **Crawlee** |
| **REPOSITORY** | `assafelovic/gpt-researcher` · `searxng/searxng` · `apify/crawlee` |
| **LICENCE** | Apache-2.0 · AGPL-3.0 · Apache-2.0 — all verified |
| **MATURITY** | High. GPT Researcher ~29k stars, active July 2026; SearXNG and Crawlee both active |
| **WHAT IT ALREADY DOES** | Planner splits a brief into questions, executors crawl in parallel, publisher writes a cited report. SearXNG gives metasearch with no API key or per-query cost |
| **WHAT WE MODIFY** | Nothing. Point GPT Researcher at our SearXNG instance and our LiteLLM endpoint |
| **WHAT IT IS MISSING** | Produces reports, not decisions. No notion of "is this worth capital" — ours |
| **HOW IT CONNECTS** | Python API or HTTP; output stored as evidence with provenance |
| **RESOURCES** | SearXNG ~200 MB; GPT Researcher light. LLM calls dominate cost |
| **LEGAL** | AGPL on SearXNG is inert — internal, unmodified. Respect robots.txt and per-source terms |
| **CONFIDENCE** | **High** for retrieval. **Low** that reports translate into good opportunities — that is the project's real open question |

### 2.3 Cost control and observability — adopted first, deliberately

| Field | |
|---|---|
| **CAPABILITY** | LLM routing, spend caps, tracing (not in the original 63; added — see capability map §3) |
| **BEST EXISTING SYSTEM** | **LiteLLM** + **Langfuse** |
| **REPOSITORY** | `BerriAI/litellm` · `langfuse/langfuse` |
| **LICENCE** | Both **MIT core** with a separate `enterprise/` directory. We use only the core |
| **MATURITY** | High, both active 2026-08-20 |
| **WHAT IT ALREADY DOES** | LiteLLM: one OpenAI-compatible endpoint over every provider, per-key/team/user budgets, spend tracking, fallback routing. Langfuse: per-call traces, token and cost accounting, quality evaluation |
| **WHAT WE MODIFY** | Nothing. Config only |
| **WHAT IT IS MISSING** | LiteLLM caps LLM spend but not company spend (Stripe, hosting, ads). That gap is ours |
| **HOW IT CONNECTS** | Every component points at LiteLLM instead of a provider. Langfuse receives traces |
| **RESOURCES** | LiteLLM ~150 MB. Langfuse self-hosted needs Postgres + ClickHouse — **use Langfuse Cloud free tier initially** |
| **LEGAL** | MIT core clean. **Watch:** Langfuse's copyright now sits with ClickHouse, Inc. — track for licence change |
| **CONFIDENCE** | **High.** This is why it is adopted before anything else spends money |

### 2.4 Measurement, experiments, flags

| Field | |
|---|---|
| **CAPABILITY** | Analytics, experimentation, A/B testing, surveys (39, 44, 45) |
| **BEST EXISTING SYSTEM** | **PostHog** |
| **REPOSITORY** | `PostHog/posthog` |
| **LICENCE** | **MIT core**, `ee/` under a separate enterprise licence. Verified verbatim |
| **MATURITY** | High, active daily |
| **WHAT IT ALREADY DOES** | Product analytics, feature flags, A/B experiments, surveys, session replay, error tracking — four of our capabilities in one system |
| **WHAT WE MODIFY** | Nothing |
| **WHAT IT IS MISSING** | Measures the product, not the company. Portfolio-level economics stay in our ledger |
| **HOW IT CONNECTS** | SDK in shipped products; REST for reading results back into the loop |
| **RESOURCES** | **Self-hosting needs ClickHouse + Kafka + Redis — out of scope for a low-spec machine.** Start on PostHog Cloud's free tier; self-host only if volume justifies it |
| **LEGAL** | MIT core clean. Avoid `ee/` |
| **CONFIDENCE** | **High** |

### 2.5 CRM and email

| Field | |
|---|---|
| **CAPABILITY** | CRM, email automation, marketing (17, 20, 21) |
| **BEST EXISTING SYSTEM** | **EspoCRM** (or Twenty) + **Listmonk** |
| **REPOSITORY** | `espocrm/espocrm` · `knadh/listmonk` |
| **LICENCE** | Both **AGPL-3.0**, verified |
| **MATURITY** | EspoCRM: mature, active 2026-08-18. Listmonk: mature, active, single Go binary |
| **WHAT IT ALREADY DOES** | EspoCRM: contacts, deals, activity, full REST API, **~90% configurable from the admin panel without forking** — which is precisely our rule. Listmonk: lists, campaigns, templates, transactional send, bounce handling |
| **WHAT WE MODIFY** | Nothing. Configure through the admin UI |
| **WHAT IT IS MISSING** | Neither decides who to contact or what to say. The LLM writes; our loop decides; the approval gateway releases |
| **HOW IT CONNECTS** | REST both ways |
| **RESOURCES** | EspoCRM: PHP + MySQL, ~500 MB. Listmonk: ~100 MB + Postgres |
| **LEGAL** | AGPL inert while unmodified and internal. **Real constraint is anti-spam law, not the licence** — consent, disclosure, opt-out |
| **CONFIDENCE** | **High** technically; **medium** on outreach effectiveness within lawful channels |

### 2.6 Revenue

| Field | |
|---|---|
| **CAPABILITY** | Payments, invoicing, subscriptions (51, 52) |
| **BEST EXISTING SYSTEM** | **Stripe** (hosted API). Kill Bill (Apache-2.0) held in reserve |
| **REPOSITORY** | n/a — hosted. `killbill/killbill` if self-hosting is ever needed |
| **LICENCE** | Commercial ToS. No open-source question |
| **MATURITY** | Highest of anything in this document |
| **WHAT IT ALREADY DOES** | Checkout, subscriptions, invoicing, tax, dunning, disputes, payouts, full API, official MCP server |
| **WHAT WE MODIFY** | Nothing |
| **WHAT IT IS MISSING** | Nothing we need |
| **HOW IT CONNECTS** | API with a **restricted key**: create prices and charges within caps; **payouts and account changes excluded from the key's scope** — enforced by Stripe, not by our code |
| **RESOURCES** | None |
| **LEGAL** | **The most important row here.** Account is held by the Chairman as a legal person. Automation abuse or high dispute rates cause suspension, which stops revenue outright. Treat account health as a top-tier metric |
| **CONFIDENCE** | **High** on the technology; **medium** on operational risk, which is why §2.10 exists |

### 2.7 Deployment

| Field | |
|---|---|
| **CAPABILITY** | Deployment, infrastructure (31) |
| **BEST EXISTING SYSTEM** | **Coolify** |
| **REPOSITORY** | `coollabsio/coolify` |
| **LICENCE** | **Apache-2.0**, verified — the cleanest licence in its category |
| **MATURITY** | High. ~57k stars, 280+ one-click services, multi-server, active |
| **WHAT IT ALREADY DOES** | Turns a plain VPS into a Heroku-style target: git-push deploys, Docker Compose, TLS, databases, backups |
| **WHAT WE MODIFY** | Nothing |
| **WHAT IT IS MISSING** | No approval concept — our gateway sits in front for production deploys |
| **HOW IT CONNECTS** | REST API + webhooks |
| **RESOURCES** | ~1 GB on the VPS. Not on the Chairman's machine |
| **LEGAL** | Apache-2.0, clean |
| **CONFIDENCE** | **High** |

### 2.8 Scheduling and glue

| Field | |
|---|---|
| **CAPABILITY** | Workflow automation, scheduling (34, 35) |
| **BEST EXISTING SYSTEM** | **n8n** — *internal use only*. **Activepieces** (MIT) as the swap |
| **REPOSITORY** | `n8n-io/n8n` · `activepieces/activepieces` |
| **LICENCE** | ⚠️ n8n: **Sustainable Use Licence — not open source.** Permits use "only for your own internal business purposes"; forbids providing it to others. `.ee` files need a paid licence; non-`master` branches are unlicensed. Activepieces: **MIT core** + `packages/ee/` |
| **MATURITY** | Both high and active |
| **WHAT IT ALREADY DOES** | Scheduled triggers, 400+ integrations, retries, error branches, webhooks, native AI nodes |
| **WHAT WE MODIFY** | Nothing |
| **WHAT IT IS MISSING** | Executes graphs; does not *decide*. Our loop chooses; n8n runs the plumbing |
| **HOW IT CONNECTS** | Webhooks in both directions |
| **RESOURCES** | ~500 MB. VPS, not local |
| **LEGAL** | **Bright line: n8n may automate our own operations; it may never be part of anything customers receive.** If that ever feels tight, switch to Activepieces — the swap is cheap because we never fork |
| **CONFIDENCE** | **High**, with the boundary observed. **Defer to step 7** — cron is enough until then |

### 2.9 Support and BI (L2)

| Field | |
|---|---|
| **CAPABILITY** | Customer support, BI, profit reporting (25, 40, 63) |
| **BEST EXISTING SYSTEM** | **Chatwoot** + **Metabase** |
| **LICENCE** | Chatwoot **MIT core** + `enterprise/`; Metabase **AGPL-3.0** (paid tiers exist) |
| **MATURITY** | Both high and active |
| **WHAT IT ALREADY DOES** | Chatwoot: omnichannel inbox, live chat, help centre, automations. Metabase: SQL-free dashboards over our ledger |
| **WHAT WE MODIFY** | Nothing |
| **WHAT IT IS MISSING** | Chatwoot's AI features are in `enterprise/` — we drive replies through our own LLM path instead |
| **RESOURCES** | Chatwoot: Rails + Postgres + Redis, ~1 GB. Metabase: JVM, ~1 GB. **Both VPS-only** |
| **LEGAL** | Support inboxes contain personal data — retention and erasure obligations apply |
| **CONFIDENCE** | **High**, deferred until there are customers to support |

### 2.10 What we build — and only this

| Field | |
|---|---|
| **CAPABILITY** | Bounded decision loop (43), capital allocation (62), audit trail (56), Chairman console |
| **BEST EXISTING SYSTEM** | **None.** Searched venture-studio tooling, workflow engines, BI, agent frameworks |
| **WHY NOTHING FITS** | Workflow engines have approval *steps*, not risk tiers with spend caps and expiry. BI shows data, it does not allocate capital. Venture-studio "OS" projects are methodology documents. Autonomous-company projects (Auto-Co, VentureNode, FounderFlow, Paperclip, Claw-Empire) **all stop before revenue** — they produce plans and landing pages, never a paying customer |
| **WHAT WE BUILD** | ~1,000 lines: pick one action from a bounded set under a budget; enforce per-transaction/daily/venture caps; escalate above-limit and legally significant actions; write a hash-chained decision record tying action → evidence → cost → policy version; render a phone-usable console |
| **WHAT WE REUSE** | The committed port layer (`src/happy/core/ports/`) becomes the **anti-corruption layer** — typed contracts, risk tiers, per-source licence metadata across a dozen third-party APIs. It stays at its current size; it does not grow into a framework |
| **HOW IT CONNECTS** | Calls every system above over HTTP. Holds no vendor logic itself |
| **RESOURCES** | Runs on the Chairman's low-spec machine. SQLite, one process, tick-based |
| **LEGAL** | **This is the liability control.** Deployer liability requires defined authority, attribution, oversight checkpoints and an evidence trail — this component is all four |
| **CONFIDENCE** | **High** that it is small. **High** that it is necessary. It is the only thing here nobody else has built |

---

## 3. Where each piece runs

| Location | Systems | Why |
|---|---|---|
| **Chairman's machine** | Our ~1,000 lines + SQLite + console | Tick-based, zero idle cost |
| **Hosted, free/cheap tier** | Stripe, PostHog Cloud, Langfuse Cloud, GitHub, LLM APIs | No ops burden, no licence questions |
| **One VPS (~$5–20/mo)** | Coolify, SearXNG, Listmonk, EspoCRM, LiteLLM, later n8n/Chatwoot/Metabase | Too heavy for local; Coolify deploys the rest |
| **On demand** | OpenHands | 2–4 GB per run; started for a task, stopped after |

The Chairman's low-spec constraint is preserved: **only our own thin layer runs locally.** Everything heavy is hosted or on the VPS.

---

## 4. First loop — concretely

| Phase | System | Autonomous? |
|---|---|---|
| DISCOVER | GPT Researcher + SearXNG | ✅ |
| VALIDATE | Research + landing page + PostHog survey | ✅ |
| BUILD | OpenHands → GitHub PR → CI → Coolify preview | ✅ (production deploy gated) |
| MARKET | LLM content + Listmonk | ✅ draft; ⚠️ send gated initially |
| SELL | EspoCRM + Stripe Checkout | ✅ self-serve |
| REVENUE | Stripe | ✅ collect; ❌ withdrawal is Chairman-only |
| MEASURE | PostHog + our ledger | ✅ |
| IMPROVE | PostHog experiments + retrospective | ✅ |

**Chairman touchpoints in the whole loop: four.** Spend above cap, production deploy of venture #1, first outbound send, and profit withdrawal. Everything else runs.

---

## 5. Honest confidence

| Claim | Confidence | Basis |
|---|---|---|
| These systems exist, work, are actively maintained, and licences are as stated | **High** | Every licence read from its own `LICENSE` file at HEAD |
| They can be composed over HTTP without forking | **High** | All expose REST APIs; composition is the mainstream way they are used |
| The composition can execute the full loop mechanically | **Medium-high** | Each phase is proven individually; the joins are unproven |
| ~1,000 lines is enough for the control layer | **Medium** | Plausible from scope; will be wrong in detail |
| **The loop will discover a business anyone pays for** | **Low** | Unchanged from the first plan. This is the project's real risk, and no amount of tooling addresses it |

The last row is the honest one. The stack is not the hard part — **all of this is assembly of things that already work.** Whether an autonomous loop finds a business worth running is unproven by anyone, including every autonomous-company project surveyed. The composition above is designed so that finding out is cheap and stopping is cheap.

---

## 6. Next executable step

Per the standing rule that every phase ends with something runnable:

**Step 1 — LiteLLM + Langfuse + a cost ceiling, running locally, with one real LLM call traced end to end.**

Small, executable today, and it means nothing that follows can spend money without being capped and visible. No new architecture, no new abstractions — a config file, a container, and a smoke test.

Awaiting the Chairman's go-ahead on the composition before starting.
