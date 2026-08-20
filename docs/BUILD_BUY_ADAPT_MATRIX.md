# Build / Buy / Adapt Matrix

**Classification, per the Chairman's rule:**

| Class | Meaning | Preference |
|---|---|---|
| **A** | Use existing system unchanged | 1st |
| **B** | Use existing system through its API | 2nd |
| **C** | Fork and modify an existing system | 3rd |
| **D** | Combine multiple existing systems | 4th |
| **E** | Reimplement — only where no suitable system exists | **Last** |

In practice **A and B collapse into one thing** for us: run it as a separate service, unmodified, and talk to it over HTTP. That is both the cheapest integration and the one that keeps AGPL/BUSL/SUL obligations inert (`EXISTING_SYSTEMS_RESEARCH.md` §4).

**Result across 63 capabilities: 3 land in class E.** Everything else is adopted or composed.

---

## 1. First-loop capabilities (L1)

| # | Capability | Class | System | Licence | Why this class |
|---|---|---|---|---|---|
| 5,6,7 | Research / web research / market intel | **A** | GPT Researcher + SearXNG + Crawlee | Apache-2.0 / AGPL / Apache-2.0 | Run unmodified; SearXNG removes per-query search cost |
| 10 | Idea generation | **B** | LLM API directly | n/a | A prompt. Building a framework here would be pure waste |
| 11 | Opportunity evaluation | **B→E(thin)** | LLM + our rubric | n/a | Scoring is ~100 lines; no system does venture rubrics |
| 26,49 | Product / project management | **A** | Plane, or GitHub Issues | AGPL-3.0 | GitHub Issues first — zero new infrastructure |
| 27,28 | Software engineering / autonomous coding | **A** | **OpenHands** | **MIT** | Strongest single component found. Runs headless, sandboxed, MIT |
| 29 | GitHub management | **B** | GitHub REST/MCP | n/a | Hosted API |
| 30 | Testing | **A** | Repo-native + CI | n/a | Whatever the generated repo uses |
| 31 | Deployment | **A** | **Coolify** | **Apache-2.0** | Turns one VPS into a deploy target; permissive |
| 20,21,22 | Email / marketing / content | **D** | Listmonk + LLM | AGPL-3.0 | Listmonk sends; the LLM writes. No marketing "AI platform" needed |
| 17 | CRM | **A** | Twenty *or* EspoCRM | AGPL-3.0 | EspoCRM if we need customisation — configurable without forking |
| 52 | Payments | **B** | **Stripe API** | n/a (ToS) | Never self-host a payment rail |
| 39,44,45 | Analytics / experiments / A-B | **A** | **PostHog** | MIT core | One system, four capabilities |
| 34,35 | Workflow automation / scheduling | **A** | n8n (internal only) *or* Activepieces | SUL / MIT | See §3 on the n8n boundary |
| — | LLM routing + spend caps | **A** | **LiteLLM** | MIT core | Per-key budgets are how the company gets a cost floor |
| — | LLM observability | **A** | **Langfuse** | MIT core | Cannot improve a loop you cannot see |
| 36 | Notifications | **A** | ntfy / Apprise | Apache-2.0 / BSD | Chairman's phone |
| 55 | Security / secrets | **A** | SOPS + age, or Infisical | MPL-2.0 / MIT | No secrets in the database |
| **43** | **Decision making (bounded)** | **E** | **Ours** | — | §2 |
| **62** | **Capital allocation** | **E** | **Ours** | — | §2 |
| **56** | **Audit logging** | **E** | **Ours** | — | §2 |

## 2. The three class-E items — and why only these

Searched explicitly; found workflow-engine approval *steps*, BI dashboards, and venture-studio *methodology documents*. None of them does the following.

| # | Capability | What is genuinely missing | Size |
|---|---|---|---|
| 43 | **Bounded decision loop** | Something that picks one action from a fixed set, under a spend cap, and records why. Workflow engines execute a graph you wrote; they do not choose. | ~400 LOC |
| 62 | **Capital allocation** | "Fund this thesis up to £X; stop at the kill criterion." No product enforces a venture budget with an automatic stop. | ~300 LOC |
| 56 | **Audit trail tied to decisions** | Deployer liability (see gap analysis) requires *defined authority, attribution, oversight checkpoints, evidence*. Application logs are not that. | ~300 LOC |

**~1,000 lines total.** That is the entire justified build. It is glue and policy, not a framework, not a database, not an orchestrator, not a memory system.

**The port layer already committed** (`src/happy/core/ports/`) is reclassified: it is no longer a framework to grow, it is the **anti-corruption layer** between these ~1,000 lines and a dozen third-party APIs — typed contracts, risk tiers and per-source licence metadata. It stays because it is the integration boundary, and it does not expand.

## 3. Class assignments that carry a condition

| System | Class | Condition |
|---|---|---|
| **n8n** | A | **Internal operations only.** SUL permits "own internal business purposes"; it forbids providing it to others. Never part of a customer-facing product. Swap to Activepieces (MIT) if this ever feels tight |
| **Twenty / EspoCRM / Plane / Listmonk / Vikunja / Documenso / Firecrawl / SearXNG** | A | **Run unmodified as a separate service.** Do not fork. AGPL obligations stay inert while we are the user, not a distributor |
| **PostHog / Chatwoot / LiteLLM / Langfuse / Activepieces / GrowthBook** | A | **Do not use the `ee/` or `enterprise/` directories.** MIT applies to everything outside them |
| **Metabase** | A | AGPL core is sufficient; do not depend on paid-tier features |
| **Odoo** | A/D | LGPL-3 community only. Attractive because CRM + accounting + invoicing in one, but heavy — evaluate only if we outgrow the light stack |
| **Akaunting / Invoice Ninja** | **Rejected** | BUSL and ELv2 respectively. Use Stripe Invoicing + our own ledger instead |
| **Dify / Langfuse** | A | Watch governance: Dify is "modified Apache-2.0 with additional conditions"; Langfuse's copyright now sits with ClickHouse, Inc. |

## 4. Deliberately not adopted

| Rejected | Class it would have been | Why not |
|---|---|---|
| Multi-agent framework (CrewAI / LangGraph / AutoGen) | A | Not on the critical path to revenue. One agent per task is simpler and cheaper. **AutoGen is in maintenance mode** — a warning about framework fashion |
| Knowledge graph (capability 42) | A | Retrieval over a few thousand internal records does not need a graph. Postgres FTS first |
| Computer-use agent (capability 33) | A | High risk, high cost, low marginal value for a SaaS venture. Browser automation (browser-use, MIT) covers the real cases |
| Self-hosted accounting | A | Licence-hostile category; Stripe + our ledger is smaller and cleaner |
| Custom orchestrator, database, memory system, LLM infrastructure | E | Explicitly forbidden by the Chairman's rule, and rightly — existing systems are better than anything we would write |
| Presentation generation (capability 38) | A | Nobody is reading a deck. Skip |

## 5. Adoption order

Ordered by *what unblocks revenue soonest*, not by architectural tidiness. Each row is independently useful, so the sequence can stop anywhere and still leave something working.

| Step | Adopt | Unblocks | Runs where |
|---|---|---|---|
| 1 | LiteLLM + Langfuse | Cost floor and visibility before anything else spends money | Local |
| 2 | The ~1,000 lines (decision loop, budget, audit) + Chairman console | Anything can be authorised and recorded | Local |
| 3 | GPT Researcher + SearXNG | DISCOVER + VALIDATE | Local |
| 4 | OpenHands + GitHub + Coolify | BUILD | Local agent, VPS deploy |
| 5 | Stripe + PostHog Cloud (free tier) | REVENUE + MEASURE | Hosted |
| 6 | Listmonk + a CRM | MARKET + SELL | VPS |
| 7 | n8n or Activepieces | Replaces our glue with a real scheduler | VPS |

**Steps 1–5 close the loop.** Steps 6–7 make it repeatable.

Note the ordering choice: **cost control comes before capability.** An autonomous system that cannot cap its own spend has no floor under its losses, and that failure mode arrives faster than any other.
