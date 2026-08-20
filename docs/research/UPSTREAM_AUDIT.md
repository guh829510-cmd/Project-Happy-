# Upstream Repository Audit

**Status:** Complete — pre-implementation audit
**Date of audit:** 2026-08-20
**Method:** Every repository was **cloned and inspected on disk**. Licenses were read from the actual `LICENSE`/`NOTICE` files, dependencies from actual manifests, and package licensing from the PyPI JSON API. GitHub's license badge was **not** treated as authoritative — and in two cases it was actively misleading (see §2.3 and §3.3).
**No upstream source code has been copied into this repository.**

Companion document: [`legal/THIRD_PARTY_LICENSE_MATRIX.md`](../../legal/THIRD_PARTY_LICENSE_MATRIX.md)

---

## 0. Executive summary

| Project | License (verified) | Verdict |
|---|---|---|
| Paperclip | MIT | **Concept reference only** — Postgres-based, too heavy for the constraint set |
| Claw-Empire | Apache-2.0 | **Concept reference only** — carries a non-OSS runtime dependency (Remotion) |
| FinRobot | Apache-2.0 (**but `setup.py` claims MIT**) | **Concept reference only** — GPL-3.0 dependency in the import graph |
| DeepResearchAgent | MIT | **Concept reference only, and pin v1.0.0 not HEAD** — HEAD is a live-trading system |

**Nothing should be vendored.** Four independent audits converged on the same answer for four different reasons. The details below are the reasons.

### The five findings that changed the plan

1. **FinRobot imports `backtrader`, which is GPL-3.0+.** Not a transitive leaf — a direct `import backtrader as bt` in `finrobot/functional/quantitative.py`. Vendoring FinRobot's quant module into an Apache-2.0 product creates a copyleft conflict.
2. **FinRobot's `setup.py` declares `license="MIT"` while its `LICENSE` file and `NOTICE` are Apache-2.0.** The package metadata and the repository disagree. This is unresolved upstream and is marked `UNKNOWN — REQUIRES REVIEW`.
3. **Claw-Empire (Apache-2.0) depends on Remotion, which is not open source.** `remotion` and `@remotion/cli` are runtime `dependencies`, and `prestart` actively bootstraps the Remotion runtime. Remotion requires a **paid Company License for for-profit organizations with more than 3 employees**. An Apache-2.0 badge concealing a commercial licence gate is exactly the failure mode this audit existed to catch.
4. **DeepResearchAgent's HEAD is no longer a research agent.** v2 added `online_trading_agent`, `intraday_trading_agent`, `interday_trading_agent` and SDKs for **Binance, Hyperliquid and Alpaca** — live order-execution capability. Adopting HEAD would import the exact capability our architecture is built to make impossible. **v1.0.0 (`4acd4c7`) is the clean hierarchical-research architecture** and is the only version worth reading.
5. **DeepResearchAgent vendors LightRAG v1.3.9 (12 MB) with no LICENSE file and no copyright headers.** Upstream LightRAG is MIT, which requires the copyright notice be preserved in redistributions. Vendoring DRA would propagate an apparent attribution defect into our tree.

---

## 1. Paperclip

### 1.1 Identity and pinning

| Field | Value |
|---|---|
| Repository URL | `https://github.com/paperclipai/paperclip` |
| Default branch | `master` |
| **Commit to pin** | `5a1ce7aed8238036dc92dcc944c71e08fe6ebc50` (2026-08-19) |
| Package version | `@paperclipai/server` 0.3.1 |
| Release tags | `canary/*`, `nightly/*` only — **no stable semver tag on the default branch** |

**Pinning note:** the audited HEAD commit references PR **#11748**. This project moves extremely fast and ships canary/nightly builds rather than stable releases. Any reference must be to the exact SHA above; "latest" is meaningless here and a doc written against it will be stale within days.

### 1.2 Technical profile

| Field | Value |
|---|---|
| Language | TypeScript (ESM) |
| Framework | Node.js ≥ 20, React 19, pnpm 9.15.4 workspaces |
| Architecture | Monorepo: `server` / `ui` / `cli` / `packages/*`, with a pluggable **agent-adapter registry** |
| Database | **PostgreSQL, required.** `DATABASE_URL=postgres://…`; ships `embedded-postgres` 18.1.0-beta.16 (bundled + patched) for local dev; Drizzle ORM + drizzle-kit migrations |
| Authentication | `better-auth` 1.6.28; `BETTER_AUTH_SECRET`; multi-user with authenticated E2E test configs |
| Docker | `Dockerfile` (`node:lts-trixie-slim`) + `docker/`; image installs `gh`, `git`, `ripgrep`, `python3`, `gosu` |
| APIs | REST over `/companies/:companyId/...`; SSE; MCP servers shipped as packages (`mcp-server`, `google-sheets-mcp-server`, `kv-demo-mcp-server`) |

### 1.3 Legal

| Field | Finding |
|---|---|
| LICENSE file | **Present, MIT**, "Copyright (c) 2025 Paperclip AI" |
| Nested LICENSE | **Yes** — `packages/adapters/hermes/LICENSE`, MIT, "Copyright (c) 2026 **Nous Research**" (a different copyright holder inside the same repo) |
| NOTICE file | No root NOTICE. `ui/public/fonts/NOTICE.md` documents bundled **Inter v4.1 under SIL OFL 1.1** — a font-embedding obligation that travels with any UI copied from here |
| Trademark policy | **None found.** "Paperclip" is used as a product name with no stated policy — absence of a policy is not permission; nominative use only |
| Contribution rules | `CONTRIBUTING.md` (190 lines). **No CLA, no DCO, no copyright assignment.** Requires duplicate-PR search, a PR-template checkbox, Greptile score 5/5, Discord #dev discussion for large changes |
| Commercial use | Unrestricted under MIT (attribution required) |

### 1.4 Extension mechanism

Genuinely pluggable, and the most reusable *idea* in the audit:

- `packages/plugins/sdk` + `create-paperclip-plugin` scaffolder.
- Mutable server adapter registry: `registerServerAdapter` / `unregisterServerAdapter` / `requireServerAdapter`, with `adapterType` validation relaxed to accept arbitrary strings so external adapters can register at runtime (`adapter-plugin.md`).
- Built-in adapters for `claude-local`, `codex-local`, `cursor-local`, `cursor-cloud`, `gemini-local`, `grok-local`, `opencode-local`, `pi-local`, `hermes`, `hermes-gateway`, `openclaw-gateway`.
- Sandbox-provider plugins deliberately excluded from the workspace to keep their third-party deps out of the root lockfile.

### 1.5 Transitive dependency risks

- **`embedded-postgres@18.1.0-beta.16` — a beta, patched via `pnpm.patchedDependencies`, and `bundleDependencies`.** Depending on a patched beta database is a maintenance liability we would inherit wholesale.
- **`acpx@0.12.0` also patched.** Two locally-patched third-party packages means upstream and shipped code differ; any audit of ours must audit the patches too.
- `@aws-sdk/client-s3`, `@opentelemetry/api`, `lexical` (pinned 0.49.0 across 10 packages via `overrides`), React 19 forced via `overrides`.
- Very large transitive surface — a full pnpm tree was not resolved during this audit and is marked `UNKNOWN — REQUIRES REVIEW` in the matrix.

### 1.6 Reuse assessment

**Worth reusing (as design, reimplemented):**
- Org-chart-as-data and the company/agent domain split.
- The **mutable adapter registry pattern** — the cleanest expression of our `AgentRuntime` port requirement.
- `PAPERCLIP_TOOL_ACTION_SIGNING_SECRET`: signing tool actions so an action cannot be forged or replayed. This maps directly onto our capability-token design and is worth copying **as a concept**.
- Budget/cost-control and heartbeat scheduling concepts.

**Do NOT reuse:**
- The entire persistence layer. **Postgres is a hard requirement here and a hard non-requirement for us.** `embedded-postgres` alone would blow the low-spec budget.
- `better-auth` multi-user auth — we are single-operator.
- The React 19 + Vite + Storybook + Playwright UI stack (no build chain on a low-spec machine).
- The Docker image (installs `gh`, `git`, `python3` into an agent-accessible container).
- Nothing under `packages/adapters/hermes/` without carrying the Nous Research copyright.

---

## 2. Claw-Empire

### 2.1 Identity and pinning

| Field | Value |
|---|---|
| Repository URL | `https://github.com/GreenSheep01201/claw-empire` |
| Default branch | `main` |
| **Commit to pin** | `5c928b24ffa55b403fe7c5521d4ac3ac49516137` (tag **v2.0.4**, 2026-03-13) |
| HEAD at audit | `66a24ea7df2435ef897c48c147deb7ec572c01c2` (2026-03-17, "Merge PR #66 branch into dev ancestry") |
| npm package name | `climpire` v2.0.4 |

**Provenance warning:** several near-identical forks exist (`saaddooo/claw-empire`, `pairojvrh/openclaw-empire`, `danielpinx/zclaw-empire`) with the same README. `GreenSheep01201` is the copyright holder named in the Apache-2.0 appendix and is treated as canonical. **Do not cite a fork.**

### 2.2 Technical profile

| Field | Value |
|---|---|
| Language | TypeScript 5.9 |
| Framework | Node.js **≥ 22**, Express 5, React 19, Vite 7, Tailwind 4, PixiJS 8, `ws` |
| Architecture | Single app: `server/` (config, db, gateway, messenger, modules, oauth, scripts, security, ws) + `src/` React client |
| Database | **SQLite via Node 22's built-in `node:sqlite` (`DatabaseSync`)** — zero native modules, zero external DB. `DB_PATH=/app/data/claw-empire.sqlite` |
| Authentication | OAuth token storage encrypted at rest via `OAUTH_ENCRYPTION_SECRET`; webhook HMAC (`INBOX_WEBHOOK_SECRET`) |
| Docker | `Dockerfile` + `docker-compose.yml` with `no-new-privileges:true`, non-root UID/GID 10001, volume-mounted `./data`; also `deploy/` systemd unit + nginx conf |
| APIs | REST with a **checked-in OpenAPI contract** (`docs/openapi.json`, `openapi:check` in CI), Swagger UI, WebSocket |

### 2.3 Legal — the headline finding

| Field | Finding |
|---|---|
| LICENSE file | **Present, Apache-2.0**, "Copyright 2026 GreenSheep01201 (seowongil@gmail.com)" |
| NOTICE file | **ABSENT.** Apache-2.0 §4(d) only compels a NOTICE if the original work has one — but its absence means **no upstream attribution travels with redistribution**, and we would have to construct attribution ourselves |
| Trademark policy | None found |
| Contribution rules | `CONTRIBUTING.md` — PRs to `dev` (not `main`), 1 approval, CI green, squash-merge. **No CLA/DCO** |
| Commercial use | Apache-2.0 permits it — **but see below** |

> ### ⚠️ Remotion: a non-OSS dependency inside an Apache-2.0 repository
>
> `package.json` lists `remotion@^4.0.429` and `@remotion/cli@^4.0.429` as **runtime `dependencies`**, and `prestart` runs `scripts/ensure-remotion-runtime.mjs`, which bootstraps the Remotion CLI on every start.
>
> **Remotion is not open source.** It is free only for individuals, non-profits, evaluation, and for-profit organizations with **up to 3 employees**. Beyond that a paid **Company License** is required. Remotion additionally forbids copying or modifying its code to sell a derivative.
>
> Neither the README nor a NOTICE file discloses this. The Apache-2.0 badge describes Claw-Empire's own code and says nothing about what running it obliges you to buy.
>
> **Consequence for us:** if Project Happy ever grows past 3 employees, any Remotion-derived path becomes a licensing liability. Since the video/slide generation feature is worthless to us anyway, the mitigation is trivial — **do not adopt any Claw-Empire code path that touches Remotion, `@remotion/cli`, or `pptxgenjs`-driven media generation.**

### 2.4 Extension mechanism

- Git **submodules**: `tools/ppt_team_agent` (author's own) and `tools/playwright-mcp` (Microsoft, Apache-2.0). Submodules mean `git clone` without `--recurse-submodules` yields an incomplete tree — and pulls a browser-automation MCP server we have deliberately excluded.
- Skills library with a canonical-migration script; `templates/AGENTS-empire.md`.
- Task packs / department scope resolver (`server/modules/workflow/packs/`).

### 2.5 Reuse assessment

**Worth reusing (as design):**
- **`node:sqlite` + volume-mounted data + systemd/nginx deploy** — the closest match in the entire audit to our local-first, cheap-VPS target. The deployment shape is worth studying directly.
- **`scripts/verify-security-audit-log.mjs`** — an upstream that ships a *verifier* for its own audit log has independently arrived at our hash-chain requirement. Strong validation of that design choice.
- **OpenAPI contract checked into CI** (`openapi:check`) — good discipline, cheap to adopt.
- Department/role/levelling model, meeting and handoff patterns, `no-new-privileges` + non-root container hardening.

**Do NOT reuse:**
- **Anything touching Remotion** (§2.3).
- PixiJS pixel-art office UI — pure cost on a low-spec machine.
- The submodules, particularly `playwright-mcp`.
- `@remotion/cli`, `remotion`, `pptxgenjs`, `sharp`, `swagger-ui-express` as runtime deps.

---

## 3. FinRobot

### 3.1 Identity and pinning

| Field | Value |
|---|---|
| Repository URL | `https://github.com/AI4Finance-Foundation/FinRobot` |
| Default branch | `master` |
| HEAD at audit | `01ed408326f1d4ec2460596dee10858faf0f69af` (2026-07-27, "Update README.md") |
| **Commit to pin** | `a4a7fe6ace8f04b99188c9f6587e12ea86299bc1` (tag **v1.0.0**, 2026-03-20) — a tagged release is preferable to a docs-only HEAD |
| Other tags | `desktop-v0.1.0` |
| `setup.py` version | 0.1.5 (**does not match the v1.0.0 tag**) |

### 3.2 Technical profile

| Field | Value |
|---|---|
| Language | Python |
| Python requirement | `setup.py`: `>=3.10, <3.12` — **but the `Dockerfile` uses `python:3.13-slim`.** Directly contradictory |
| Framework | AutoGen (`pyautogen>=0.2.19`) multi-agent; LangChain 0.1.20; FastAPI + SQLAlchemy + Jinja2 in the newer `finrobot_equity` web app |
| Architecture | Layered: Financial AI Agents → LLM Algorithms → LLMOps/DataOps → multi-source foundation models. Code: `agents/` (`agent_library.py`, `workflow.py`, `prompts.py`), `data_source/`, `functional/`, `toolkits.py` |
| Database | None in core. `finrobot_equity` uses SQLAlchemy 2.x + `pg8000` (Postgres, for Cloud SQL) |
| Authentication | `bcrypt` password hashing in the equity web app; API keys via `config_api_keys` and `OAI_CONFIG_LIST` **as plaintext JSON files in the repo root** |
| Docker | `Dockerfile` → `uvicorn finrobot_equity.web_app.main:app`; installs `build-essential` to compile numpy from source. Also `deploy.sh`, `deploy.gcloud.sh` |
| Submodule | `FinNLP` → `https://github.com/AI4Finance-Foundation/FinNLP` |

**Required third-party API keys:** `FINNHUB_API_KEY`, `FMP_API_KEY`, `SEC_API_KEY`, `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `TWITTER_BEARER_TOKEN`, plus OpenAI/Azure OpenAI.

### 3.3 Legal — the most complicated of the four

| Field | Finding |
|---|---|
| LICENSE file | **Present, Apache-2.0**, "Copyright 2026 AI4Finance Foundation" |
| **License conflict** | `setup.py` declares `license="MIT"` **and** the classifier `License :: OSI Approved :: MIT License`, while `LICENSE` and `NOTICE` both say Apache-2.0. → **`UNKNOWN — REQUIRES REVIEW`** |
| NOTICE file | **Present and substantive.** Asserts the FinRobot™ trademark, requires "Redistributions of this software must retain this NOTICE file", lists third-party software, and carries an **AI-generated-content disclaimer**: reports "should not be considered as professional financial advice" |
| **Trademark policy** | **`TRADEMARK_POLICY.md`, effective 2026-02-15 — the only real trademark policy in this audit.** See below |
| Contribution rules | No `CONTRIBUTING.md` at root |
| Commercial use | Source: permitted under Apache-2.0. Trademark: restricted |

**Trademark policy — binding constraints on us:**
- Permitted: "Built on FinRobot", "Powered by FinRobot", "Compatible with FinRobot".
- **Prohibited:** using "FinRobot" in our product/company/service name; presenting a modified version as official; removing attribution and rebranding; implying endorsement or partnership; registering confusingly similar domains or handles.
- Derivative works must state they are derivative and **rename if core functionality is substantially modified**.
- Their own example of acceptable form: `"XQuant Platform – built on FinRobot (Apache 2.0)"`.

Since we plan concept-level borrowing and **no code reuse**, the clean position is to make **no FinRobot branding claim at all** — do not even say "built on FinRobot", because we will not be built on it. Cite it in this audit as prior art and stop there.

### 3.4 Transitive dependency risks — the GPL problem

> ### ⚠️ `backtrader` is GPL-3.0-or-later and is directly imported
>
> `requirements.txt` lists `backtrader`. It is not dormant: `finrobot/functional/quantitative.py` contains
> `import backtrader as bt` and `from backtrader.strategies import SMA_CrossOver`.
>
> Apache-2.0 and GPL-3.0 are **one-way compatible**: Apache-2.0 code may be incorporated into a GPL-3.0 work, not the reverse. A distributed Python application that imports `backtrader` is generally treated as a combined work subject to GPL-3.0.
>
> **Consequence:** vendoring FinRobot's `functional/quantitative.py` — or anything importing it — into Project Happy would put copyleft obligations on our codebase. Our own quantitative work must be written from scratch against a permissively licensed stack.

Further dependency problems in `requirements.txt`:

- **Internally inconsistent pins.** `numpy` appears unpinned *and* as `numpy==1.26.4`; `pandas` unpinned *and* `pandas==2.0.3`. `pandas==2.0.3` also contradicts `requirements-equity.txt`'s `pandas>=2.0.0,<3.0.0` resolution intent.
- **Stale, CVE-prone pins:** `aiohttp==3.8.5`, `Requests==2.31.0`, `nltk==3.8.1`, `langchain==0.1.20`, `starlette==0.37.2`, `unstructured==0.8.1`.
- **`marker-pdf`, unpinned.** Current 2.0.0 is Apache-2.0 for code, but its **model weights are under a modified AI Pubs Open RAIL-M license, free only below $5M funding/revenue**, and it implies local ML inference — a direct violation of our no-GPU constraint. Unpinned means the resolved license is not knowable in advance → `UNKNOWN — REQUIRES REVIEW`.
- **Commercial data services behind permissive client libraries:** `sec_api` (MIT client, paid SaaS), `tushare` (BSD client, points-metered Chinese service), `finnhub-python`, FMP (the NOTICE itself labels FMP "Commercial").
- **`yfinance`** — Apache-2.0 library, but Yahoo Finance ToS restricts commercial use and redistribution.
- **`praw`** — BSD library against Reddit's API, whose terms are now commercially restrictive.
- `pyautogen` — MIT (Microsoft), but the AutoGen/AG2 ecosystem has split across `pyautogen` / `autogen` / `ag2` with differing licenses (`autogen` and `ag2` are Apache-2.0). Which package resolves matters → flagged in the matrix.
- `pdfkit` requires the external `wkhtmltopdf` binary (unmaintained/archived upstream).

### 3.5 Reuse assessment

**Worth reusing (as design):**
- The **financial chain-of-thought decomposition** and agent/tool separation — this is the genuinely valuable idea.
- `data_source/` **module boundary shape** (one module per provider: `finnhub_utils`, `fmp_utils`, `yfinance_utils`, `sec_utils`, `reddit_utils`) — validates our `DataSource` port design, including per-source metadata.
- Equity research report structure.
- The **AI-generated-content disclaimer** in their NOTICE — we should ship an equivalent, and ours matters more because our output feeds capital-allocation decisions.

**Do NOT reuse:**
- **`finrobot/functional/quantitative.py` and anything importing it** (GPL-3.0 via backtrader).
- `requirements.txt` wholesale — inconsistent, stale, and heavy.
- `marker_sec_src/` (marker-pdf: RAIL-M weights + local ML inference).
- Plaintext `config_api_keys` / `OAI_CONFIG_LIST` credential files in the repo root — an anti-pattern we must not copy.
- The AutoGen runtime as our orchestration engine.
- `finrobot_equity`'s Postgres/Cloud-SQL deployment path.
- The FinRobot name, logo, or any branding.

---

## 4. DeepResearchAgent

### 4.1 Identity and pinning — version choice is the whole story

| Field | Value |
|---|---|
| Repository URL | `https://github.com/SkyworkAI/DeepResearchAgent` |
| Default branch | `main` |
| HEAD at audit | `5e3c95d14266f8c4aa6a5deae1fe165c7cd1b87b` (2026-05-04) |
| **Commit to pin** | **`4acd4c704ea109743f9c6390e2116923f4055693` (tag v1.0.0, 2025-09-29)** |
| v2.0.0 | `9b9f77c4c40a25561563dec4091c51570bef9371` (2026-02-24) — **do not use** |

> ### ⚠️ v2 turned a research agent into a trading system
>
> **v1.0.0 agents:** `planning_agent`, `deep_researcher_agent`, `deep_analyzer_agent`, `browser_use_agent`, `general_agent`. Clean hierarchical planner→specialist decomposition. Poetry-managed (`pyproject.toml` + `poetry.lock`). No vendored third-party trees.
>
> **HEAD agents:** the above plus `online_trading_agent`, `offline_trading_agent`, `intraday_trading_agent`, `interday_trading_agent`, `trading_strategy_agent`, `esg_agent`, `anthropic_mobile_agent`, `operator_browser_agent`, `debate_manager`.
>
> **HEAD dependencies include `binance-sdk-spot`, `binance-sdk-derivatives-trading-usds-futures`, `binance-sdk-derivatives-trading-coin-futures`, `binance-connector`, `hyperliquid-python-sdk`, `alpaca-py`.** These are order-execution SDKs for live exchanges and brokerages.
>
> This is the precise capability our T4 deny list exists to make structurally impossible. Reading HEAD for architectural inspiration risks importing patterns built around an execution capability we must never have. **Pin v1.0.0 and read only that.**

### 4.2 Technical profile (v1.0.0, the version we reference)

| Field | Value |
|---|---|
| Language | Python 3.11 |
| Framework | LangChain / LangGraph, `mmengine` config system |
| Architecture | Hierarchical multi-agent: a top-level planning agent decomposes tasks to specialist sub-agents; per-agent YAML prompt files (`prompts/*.yaml`) |
| Database | **None required** — filesystem + in-process memory; `nano-vectordb` / `faiss-cpu` appear at HEAD |
| Authentication | None (single-user tool). API keys via `.env`: `OPENROUTER_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY` (+ `*_API_BASE` overrides) |
| Docker | **No Dockerfile.** Conda `environment.yml` + `requirements.txt` |
| GPU | **`environment.yml` pins `pytorch=2.5.1`, `torchvision`, `torchaudio`, `libtorch=2.5.1`** (with `cpuonly=2.0`), plus `transformers`. Heavy regardless of CPU-only |

### 4.3 Legal

| Field | Finding |
|---|---|
| LICENSE file | **Present, MIT** — "Copyright (c) 2025 **AgentOrchestra**" (note: neither "SkyworkAI" nor "DeepResearchAgent"; the project was renamed and the copyright line was not updated) |
| NOTICE file | Absent (not required for MIT) |
| Trademark policy | None found |
| Contribution rules | No `CONTRIBUTING.md`; no CLA/DCO |
| Commercial use | Unrestricted under MIT (attribution required) |
| **Vendored code** | **`src/tool/esg_tools/lightrag/` — LightRAG v1.3.9 (HKUDS), 12 MB, `__author__ = "Zirui Guo"`. No LICENSE file, no copyright headers found.** Upstream LightRAG is MIT and requires the notice be preserved → **apparent MIT attribution defect**, and one we would inherit by vendoring. `UNKNOWN — REQUIRES REVIEW` |
| Other bundled assets | `LICENSE - Geist.txt`, `LICENSE - SmileySans.txt` (fonts, inside the vendored LightRAG visualizer) |

### 4.4 Transitive dependency risks (HEAD)

The HEAD `requirements.txt` is one of the largest surfaces audited, and much of it is disqualifying for us:

- **Local ML stack:** `torch`, `torchvision`, `torchaudio`, `torchmetrics`, `transformers==4.36.2` — violates the no-GPU / low-spec constraint outright, and `transformers==4.36.2` is an old hard pin.
- **Financial/trading execution:** Binance ×4, Hyperliquid, Alpaca, `TA-lib` (needs a native C library build), `backtrader` (**GPL-3.0+, again**), `empyrical`, `akshare`, `tushare`.
- **Browser/mobile automation:** `browser-use`, `playwright`, `patchright`, `selenium`, `tf-playwright-stealth`, `adbutils`, `screeninfo`. Stealth/anti-detection tooling carries its own ToS-violation exposure.
- **Telemetry that phones home:** `posthog`, `lmnr`, and OpenTelemetry OTLP exporters. **Any adoption would need these audited and disabled** — an agent framework with default-on analytics is a data-exfiltration path.
- **Commercial SaaS clients:** `firecrawl` (MIT client, paid API), `crawl4ai`, Azure Document Intelligence, `groq`, `ollama`.
- `camelot-py` (PDF tables — historically required Ghostscript, AGPL; 1.0+ moved to pdfium → `UNKNOWN — REQUIRES REVIEW`), `cairosvg`/`cairocffi` (LGPL-linked native), `pymupdf` (**AGPL-3.0 or commercial** → flagged), `unstructured`, `markitdown[all]`.
- `environment.yml` ends with `prefix: /Users/wentaozhang/opt/anaconda3/envs/agentworld` — a developer's local path, i.e. the file is a machine dump, not a curated manifest. Treat all its pins as *observed*, not *intended*.

### 4.5 Reuse assessment

**Worth reusing (as design, from v1.0.0 only):**
- **Hierarchical planner → specialist decomposition.** The single most directly applicable idea in the audit for our CEO loop and department model.
- **Prompts as versioned YAML files next to each agent** (`prompts/*.yaml`) — clean separation of prompt from code, diffable and reviewable. Adopt this convention.
- Memory-system module boundary (`src/memory/`) separating general memory from task-specific memory.
- Provider-agnostic model layer with `*_API_BASE` overrides — validates our `LLMProvider` port.
- The `registry.py` pattern for agent/tool registration.

**Do NOT reuse:**
- **Every trading agent and every exchange/brokerage SDK.** Non-negotiable.
- The vendored LightRAG tree (attribution defect + 12 MB + a graph-RAG stack we do not need).
- `torch`/`transformers`/local-inference paths.
- Browser and mobile automation agents (also consistent with the Open Computer Use exclusion already recorded in `DEVELOPMENT_PLAN.md`).
- `posthog`/`lmnr` telemetry.
- `environment.yml` in any form.

---

## 5. Cross-cutting conclusions

### 5.1 What the audit changed about our plan

| Plan assumption | Audit result |
|---|---|
| "All four upstreams are permissive and mutually compatible" | **True at the top level, materially incomplete underneath.** Two carry non-permissive obligations one level down (backtrader GPL-3.0; Remotion commercial) |
| DeepResearchAgent = hierarchical research architecture | **True of v1.0.0 only.** HEAD is a trading system |
| FinRobot = Apache-2.0 | **Disputed by its own `setup.py`.** Unresolved |
| Concept-level borrowing is sufficient | **Confirmed, and now clearly the only safe option** — for four independent reasons |

### 5.2 Patterns worth adopting that we had not planned

1. **Signed tool actions** (Paperclip's `TOOL_ACTION_SIGNING_SECRET`) — strengthens our capability tokens against forgery and replay.
2. **A shipped audit-log verifier** (Claw-Empire's `audit:verify`) — independent confirmation of our hash-chain design; make `happy audit verify` a first-class command, not a test helper.
3. **Prompts as versioned YAML beside each agent** (DeepResearchAgent v1) — adopt directly.
4. **OpenAPI contract checked in CI** (Claw-Empire's `openapi:check`) — cheap, catches drift.
5. **An AI-generated-content disclaimer** (FinRobot's NOTICE) — ours must be more prominent, since our output drives capital allocation.

### 5.3 Anti-patterns to avoid

1. Plaintext credential files in the repo root (FinRobot).
2. Machine-dumped environment manifests (DeepResearchAgent).
3. Undisclosed commercially-restricted runtime dependencies (Claw-Empire/Remotion).
4. Vendoring third-party trees without their LICENSE (DeepResearchAgent/LightRAG).
5. Package metadata that contradicts the LICENSE file (FinRobot).
6. Default-on telemetry in an agent framework (DeepResearchAgent).

### 5.4 If we ever do vendor — conditions

Beyond the rules already in `DEVELOPMENT_PLAN.md` §7.2:
1. Full transitive license resolution first (`pnpm licenses list` / `pip-licenses`), not a spot check.
2. No file whose import graph reaches a copyleft package.
3. Every vendored tree gets its upstream LICENSE — and if upstream omitted one, we obtain it from the true origin (as LightRAG would require).
4. Patched dependencies are audited as modified third-party code.
5. Pin by SHA, never by tag or range.

---

## 6. Audit provenance

| Repository | Clone SHA | Verified from disk |
|---|---|---|
| paperclipai/paperclip | `5a1ce7ae` | LICENSE, nested hermes LICENSE, fonts NOTICE, CONTRIBUTING, package.json ×3, pnpm-workspace, Dockerfile, .env.example, adapter-plugin.md |
| GreenSheep01201/claw-empire | `66a24ea7` | LICENSE, CONTRIBUTING, package.json, .gitmodules, docker-compose.yml, .env.example, server tree, ensure-remotion-runtime.mjs |
| AI4Finance-Foundation/FinRobot | `01ed4083` | LICENSE, **NOTICE**, **TRADEMARK_POLICY.md**, setup.py, requirements.txt, requirements-equity.txt, Dockerfile, config_api_keys, OAI_CONFIG_LIST, source grep for backtrader/marker |
| SkyworkAI/DeepResearchAgent | `5e3c95d1` + `v1.0.0` tree | LICENSE, requirements.txt, environment.yml, .env.template, src/ tree, vendored lightrag tree, v1.0.0 vs HEAD diff |

Package licensing was verified via the **PyPI JSON API** (`license`, `license_expression`, and classifier fields) rather than from README badges. Remotion, LightRAG and marker-pdf licenses were read from their own upstream sources.

**No upstream source code was copied into this repository. The clones live outside the project tree and are not committed.**
