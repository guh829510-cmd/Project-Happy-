# Third-Party License Matrix

**Status:** Pre-implementation review
**Date:** 2026-08-20
**Scope:** (A) upstream projects audited; (B) their dependencies that we might inherit; (C) dependencies proposed for Project Happy itself.
**Companion:** [`docs/research/UPSTREAM_AUDIT.md`](../docs/research/UPSTREAM_AUDIT.md)

---

## How to read this document

| Marker | Meaning |
|---|---|
| ✅ **CLEAR** | Permissive, verified from a primary source, no restriction relevant to us |
| ⚠️ **RESTRICTED** | Verified, but carries a restriction that constrains how we may use it |
| ⛔ **BLOCKED** | Must not enter our codebase or dependency tree |
| ❓ **UNKNOWN — REQUIRES REVIEW** | Could not be resolved to a confident answer from a primary source, or sources conflict. **Blocks adoption until resolved.** |

**Verification standard.** A GitHub license badge is not evidence. Every ✅ and ⚠️ below was read from a `LICENSE` file on disk, the PyPI JSON API (`license` / `license_expression` / classifiers), or the upstream project's own license page. Anything resolved only by inference is ❓.

**Two rules that are not negotiable:**
1. **Library license ≠ service terms.** An MIT client for a paid API grants nothing about the API. Both must be checked.
2. **Top-level license ≠ effective license.** A permissive repo can carry a copyleft or commercial dependency one level down. Two of our four upstreams do.

---

## Part A — Upstream projects

| Project | Declared | **Verified** | Source of truth | NOTICE | Trademark policy | CLA/DCO | Commercial use | Status |
|---|---|---|---|---|---|---|---|---|
| **Paperclip** `5a1ce7ae` | MIT | **MIT** | `LICENSE` on disk, "Copyright (c) 2025 Paperclip AI" | None at root; `ui/public/fonts/NOTICE.md` (Inter, OFL-1.1) | None found | None | Permitted | ✅ **CLEAR** |
| → `packages/adapters/hermes/` | — | **MIT** | Nested `LICENSE`, "Copyright (c) 2026 **Nous Research**" | — | — | — | Permitted, **separate copyright holder** | ⚠️ **RESTRICTED** |
| **Claw-Empire** `5c928b24` (v2.0.4) | Apache-2.0 | **Apache-2.0** | `LICENSE` on disk, "Copyright 2026 GreenSheep01201" | **ABSENT** | None found | None | Apache-2.0 permits — **but see Remotion, Part B** | ⚠️ **RESTRICTED** |
| **FinRobot** `a4a7fe6a` (v1.0.0) | Apache-2.0 (badge) | **CONFLICT** | `LICENSE` + `NOTICE` say Apache-2.0; **`setup.py` says `license="MIT"` + MIT classifier** | **Present, retention required** | **`TRADEMARK_POLICY.md`** (2026-02-15) | None | Source permitted; **name restricted** | ❓ **UNKNOWN — REQUIRES REVIEW** |
| **DeepResearchAgent** `4acd4c70` (v1.0.0) | MIT | **MIT** | `LICENSE` on disk, "Copyright (c) 2025 **AgentOrchestra**" | None | None found | None | Permitted | ✅ **CLEAR** |
| → DeepResearchAgent HEAD `5e3c95d1` | MIT | MIT (own code) | as above | None | — | — | Permitted | ⛔ **BLOCKED** — live-trading capability (see Part B) |

### A.1 Open items in Part A

| ID | Item | Why it is open | Resolution path |
|---|---|---|---|
| **L-01** | FinRobot: `setup.py` MIT vs `LICENSE`/`NOTICE` Apache-2.0 | The repository contradicts its own package metadata. Under Apache-2.0 we owe NOTICE retention and change-statement duties; under MIT we do not | Open an upstream issue with AI4Finance. **Until resolved, assume Apache-2.0** (the stricter reading) and rely on concept-only borrowing so the question stays moot |
| **L-02** | FinRobot trademark scope | Policy forbids "FinRobot" in a product name and forbids implying endorsement | Make **no** branding claim — not even "Built on FinRobot", since we will not be. Cite as prior art only |
| **L-03** | Claw-Empire has no NOTICE | No upstream attribution travels with redistribution | Moot under concept-only reuse. If ever vendored, construct attribution from the LICENSE copyright line |
| **L-04** | DeepResearchAgent copyright reads "AgentOrchestra" | Copyright holder does not match the publishing org (SkyworkAI) | Cosmetic under concept-only reuse; would need clarification before vendoring |

---

## Part B — Inherited dependency risk (things we must NOT pull in)

These are the reasons "the upstream is permissive" was not a sufficient answer.

### B.1 Blocked — copyleft in the import graph

| Package | License | Where | Why blocked | Status |
|---|---|---|---|---|
| **`backtrader`** | **GPL-3.0-or-later** (PyPI: `GPLv3+`) | **FinRobot** `requirements.txt` → directly imported at `finrobot/functional/quantitative.py` (`import backtrader as bt`); also **DeepResearchAgent** HEAD | Apache-2.0/MIT → GPL-3.0 is one-way. A distributed app importing it is generally a combined work under GPL-3.0. Would impose copyleft on Project Happy | ⛔ |
| **`pymupdf`** | **AGPL-3.0 or commercial** | DeepResearchAgent HEAD (`pymupdf==1.25.3`) | AGPL adds a network-use trigger — fatal for a hosted dashboard. Commercial license otherwise required | ⛔ |

### B.2 Blocked — non-OSS commercial gate

| Package | License | Where | Why blocked | Status |
|---|---|---|---|---|
| **`remotion`, `@remotion/cli`** | **Remotion License — not OSI open source** | **Claw-Empire** runtime `dependencies`; bootstrapped by `prestart` | Free only for individuals, non-profits, evaluation, and for-profits with **≤ 3 employees**; a paid **Company License** is required above that. Also forbids selling derivatives of Remotion. **Undisclosed in the repo's README and absent NOTICE** | ⛔ |

### B.3 Blocked — capability conflict with our safety architecture

Licensing is fine on these; the *capability* is the problem. They are listed here because a license-only review would have passed them.

| Package | License | Where | Why blocked | Status |
|---|---|---|---|---|
| `binance-sdk-spot`, `binance-sdk-derivatives-trading-usds-futures`, `binance-sdk-derivatives-trading-coin-futures`, `binance-connector` | MIT | DeepResearchAgent HEAD | Live exchange order execution. Directly contradicts the T4 deny list | ⛔ |
| `hyperliquid-python-sdk` | MIT | DeepResearchAgent HEAD | Live DEX order execution | ⛔ |
| `alpaca-py` | Apache-2.0 | DeepResearchAgent HEAD, `requirements.txt` ×2 | Live brokerage order execution | ⛔ |
| `browser-use`, `patchright`, `selenium`, `tf-playwright-stealth`, `adbutils` | MIT / various | DeepResearchAgent HEAD; `playwright-mcp` submodule in Claw-Empire | Computer/browser/mobile automation — already excluded by the Open Computer Use decision. Stealth tooling additionally invites ToS violations | ⛔ |
| `posthog`, `lmnr`, OTLP exporters | MIT / Apache-2.0 | DeepResearchAgent HEAD | Default-on telemetry in an agent framework is a data-exfiltration path | ⛔ |

### B.4 Restricted — usable only with care, and not by us for now

| Package | License (verified) | Restriction | Status |
|---|---|---|---|
| **`marker-pdf`** | Code **Apache-2.0**; **model weights: modified AI Pubs Open RAIL-M** | Weights free only under **$5M funding/revenue**; RAIL adds use restrictions. Implies local ML inference (violates no-GPU). **Unpinned in FinRobot**, so the resolved license is not knowable in advance | ❓ **UNKNOWN — REQUIRES REVIEW** |
| **`camelot-py`** | MIT (PyPI, v2.0.0) | Historically required **Ghostscript (AGPL)** as a PDF backend; 1.0+ reportedly moved to pdfium. Backend not verified at the pinned version | ❓ **UNKNOWN — REQUIRES REVIEW** |
| **`TA-Lib`** | **No license metadata on PyPI** | Python wrapper commonly BSD; requires a separately-licensed native C library build (violates low-spec) | ❓ **UNKNOWN — REQUIRES REVIEW** |
| **`pyautogen`** | MIT (Microsoft) | Ecosystem split across `pyautogen` (MIT) / `autogen` (Apache-2.0) / `ag2` (Apache-2.0); which resolves is version-dependent | ❓ **UNKNOWN — REQUIRES REVIEW** |
| **LightRAG (vendored in DRA)** | Upstream **MIT**; **vendored copy has no LICENSE and no copyright headers** | MIT requires the notice be preserved in redistributions. Vendoring DRA propagates the defect | ❓ **UNKNOWN — REQUIRES REVIEW** |
| `embedded-postgres@18.1.0-beta.16` | PostgreSQL License (assumed) | **Beta**, `bundleDependencies`, and **locally patched** by Paperclip. Patched third-party code needs its own audit | ❓ **UNKNOWN — REQUIRES REVIEW** |
| `acpx@0.12.0` | Not verified | **Locally patched** by Paperclip | ❓ **UNKNOWN — REQUIRES REVIEW** |
| `unstructured` | Apache-2.0 (`license_expression`) | Some extras historically carried additional terms; `0.8.1` (FinRobot's pin) is very old | ⚠️ **RESTRICTED** |
| `sharp` | Apache-2.0 | Links **libvips (LGPL-3.0)**; dynamic linking obligations on redistribution | ⚠️ **RESTRICTED** |
| `cairosvg` / `cairocffi` | LGPL-linked native | LGPL relinking obligations | ⚠️ **RESTRICTED** |
| Inter font (Paperclip UI) | **SIL OFL-1.1** | Font redistribution obligations travel with any copied UI | ⚠️ **RESTRICTED** |
| Geist, SmileySans fonts | Own licenses, in vendored LightRAG visualizer | Not reviewed | ❓ **UNKNOWN — REQUIRES REVIEW** |
| `pdfkit` | MIT | Requires external `wkhtmltopdf` binary (upstream archived/unmaintained) | ⚠️ **RESTRICTED** |
| `pptxgenjs` | MIT | Clear license; tied to Claw-Empire's Remotion-adjacent media path | ✅ (avoid by association) |

### B.5 Data sources — library license vs service terms

**The distinction that matters most commercially.** In every row the library is permissive and the service is not.

| Client library | Library license | **Service terms** | Commercial use | Status |
|---|---|---|---|---|
| `yfinance` | **Apache-2.0** (verified) | **Yahoo Finance ToS** — restricts commercial use and redistribution | ❌ Not for a product feature | ⚠️ **RESTRICTED** — private exploration only |
| `sec-api` | **MIT** (classifier) | **Paid commercial SaaS** | Requires paid plan | ⚠️ **RESTRICTED** |
| `finnhub-python` | Permissive | Free tier: rate limits + redistribution limits | Tier-dependent | ⚠️ **RESTRICTED** |
| FMP (Financial Modeling Prep) | client permissive | **FinRobot's own NOTICE labels it "Commercial"** | Requires paid plan | ⚠️ **RESTRICTED** |
| `tushare` | **BSD** (verified) | Points-metered Chinese data service | Tier-dependent | ⚠️ **RESTRICTED** |
| `akshare` | **MIT** (verified) | Scrapes numerous third-party sources | Per-source ToS unknown | ❓ **UNKNOWN — REQUIRES REVIEW** |
| `praw` | **BSD** (verified) | **Reddit API terms — commercially restrictive** | ❌ | ⚠️ **RESTRICTED** |
| Twitter/X API (`TWITTER_BEARER_TOKEN`) | n/a | Paid tiers; restrictive | Requires paid plan | ⚠️ **RESTRICTED** |
| `firecrawl` | **MIT** (verified) | **Paid hosted API**; self-host terms differ | Tier-dependent | ❓ **UNKNOWN — REQUIRES REVIEW** |
| `crawl4ai` | **Apache-2.0** (verified) | Scraping — target-site ToS and robots.txt apply per target | Per-target | ⚠️ **RESTRICTED** |
| **SEC EDGAR** | n/a | Public domain data; requires declared User-Agent + fair-access rate limits | ✅ Permitted | ✅ **CLEAR** |
| Public RSS/Atom, open-data portals | n/a | Per-feed, generally permissive | ✅ Generally permitted | ✅ **CLEAR** |

**Enforcement:** per `DEVELOPMENT_PLAN.md` §7.5, every `DataSource` adapter must declare `license`, `commercial_use`, `redistribute`, `rate_limit`, `attribution_required`, and the policy engine must **block** publication of artifacts derived from any source flagged `redistribute: false`. A ⚠️ row above is only safe because that check exists.

---

## Part C — Project Happy's own proposed dependencies

Licenses below are the commonly published ones for these packages. **Every row is marked ❓ until verified by the automated license check landing in M0** — that check, not this table, is the control. Listing a license here is a plan, not a verification.

### C.1 Runtime

| Package | Expected license | Verified? | Status |
|---|---|---|---|
| Python ≥ 3.11 | PSF-2.0 | Pending M0 | ❓ pending |
| `fastapi` | MIT | Pending M0 | ❓ pending |
| `uvicorn` | BSD-3-Clause | Pending M0 | ❓ pending |
| `pydantic` v2 | MIT | Pending M0 | ❓ pending |
| `sqlalchemy` ≥ 2 | MIT | Pending M0 | ❓ pending |
| `alembic` | MIT | Pending M0 | ❓ pending |
| `jinja2` | BSD-3-Clause | Pending M0 | ❓ pending |
| `httpx` | BSD-3-Clause | Pending M0 | ❓ pending |
| `apscheduler` | MIT | Pending M0 | ❓ pending |
| `pyyaml` | MIT | Pending M0 | ❓ pending |
| `structlog` | MIT / Apache-2.0 dual | Pending M0 | ❓ pending |
| `typer` | MIT | Pending M0 | ❓ pending |
| `tenacity` | Apache-2.0 | Pending M0 | ❓ pending |
| `anthropic` SDK | MIT | Pending M0 | ❓ pending |
| `openai` SDK | Apache-2.0 | Pending M0 | ❓ pending |
| HTMX (vendored static) | BSD-2-Clause (0BSD in recent releases) | Pending M0 | ❓ pending |
| Pico.css or hand-written CSS | MIT | Pending M0 | ❓ pending |

### C.2 Optional extras (never required to boot)

| Package | Expected license | Note | Status |
|---|---|---|---|
| `feedparser` | BSD-2-Clause | RSS ingestion | ❓ pending |
| `selectolax` | MIT | HTML extraction (prefer over BeautifulSoup for speed) | ❓ pending |
| `beautifulsoup4` | MIT | HTML extraction | ❓ pending |
| `sqlite-vec` | Apache-2.0 / MIT dual | Only if lexical retrieval proves insufficient | ❓ pending |

### C.3 Development

| Package | Expected license | Status |
|---|---|---|
| `pytest`, `pytest-asyncio`, `pytest-cov` | MIT | ❓ pending |
| `hypothesis` | MPL-2.0 (**weak copyleft — dev-only, never shipped**) | ⚠️ dev-only |
| `ruff` | MIT | ❓ pending |
| `mypy` | MIT | ❓ pending |
| `pip-audit` | Apache-2.0 | ❓ pending |
| `pip-licenses` | MIT | ❓ pending |

### C.4 Deliberately excluded, with the licensing reason

| Excluded | Reason |
|---|---|
| **Open Computer Use** | **FSL-1.1-Apache-2.0** — Competing Use restriction is unbounded for a venture-building system; plus transitively restricted deps. Already recorded in `DEVELOPMENT_PLAN.md` §7.4 |
| `backtrader`, `pymupdf` | Copyleft (GPL-3.0+, AGPL-3.0) |
| `remotion` | Non-OSS company license |
| `marker-pdf` | RAIL-M weights + revenue threshold + local ML inference |
| PostgreSQL as a *local* requirement | Not licensing — resource cost. Postgres (PostgreSQL License, ✅) remains our VPS target |
| Exchange/brokerage SDKs | Capability conflict with T4 deny list |

---

## Part D — Compliance obligations we would take on

Under **concept-only reuse (the recommended path)**, obligations are minimal — we owe attribution to nobody because we distribute nobody's code. Recorded here so the position is explicit:

| If we... | We must... |
|---|---|
| Vendor Paperclip or DeepResearchAgent code (MIT) | Preserve copyright + permission notice; note **Nous Research** separately for `hermes` |
| Vendor Claw-Empire or FinRobot code (Apache-2.0) | Preserve LICENSE; **state changes made (§4(b))**; retain FinRobot's NOTICE (it requires retention) |
| Copy Paperclip UI including fonts | Comply with **SIL OFL-1.1** for Inter |
| Reference FinRobot by name | Comply with `TRADEMARK_POLICY.md` — **our plan is to make no branding claim at all** |
| Ship LLM-generated financial analysis | Ship an **AI-generated-content disclaimer** (FinRobot's NOTICE sets the precedent; ours matters more because our output drives capital allocation) |
| Publish artifacts derived from restricted data sources | **Blocked by the policy engine** unless the source's `redistribute` flag permits it |

---

## Part E — Open items blocking adoption

Everything marked ❓, consolidated. **None blocks M0–M2**, because the recommended path vendors nothing. Each must be resolved before any decision to vendor the associated component.

| ID | Item | Blocks | Owner action |
|---|---|---|---|
| **L-01** | FinRobot `setup.py` MIT vs LICENSE Apache-2.0 | Any FinRobot code reuse | Upstream issue; assume Apache-2.0 meanwhile |
| **L-05** | `marker-pdf` resolved version + RAIL-M weights | FinRobot RAG/PDF path | Not adopting — closed by exclusion |
| **L-06** | `camelot-py` PDF backend (Ghostscript AGPL?) | Any PDF table extraction | Verify backend at pinned version if ever needed |
| **L-07** | `TA-Lib` license metadata absent | Any TA-Lib use | Not adopting — closed by exclusion |
| **L-08** | `pyautogen` vs `autogen` vs `ag2` | Any AutoGen adoption | Not adopting — closed by exclusion |
| **L-09** | LightRAG vendored without LICENSE | Any DRA vendoring | Report upstream; obtain LICENSE from HKUDS if ever vendored |
| **L-10** | `embedded-postgres` beta + Paperclip patch | Any Paperclip DB reuse | Not adopting — closed by exclusion |
| **L-11** | `acpx@0.12.0` license + patch | Any Paperclip CLI reuse | Not adopting — closed by exclusion |
| **L-12** | `firecrawl` self-host vs hosted terms | Any Firecrawl use | Verify before adoption |
| **L-13** | `akshare` per-source ToS | Any AKShare use | Verify before adoption |
| **L-14** | Paperclip full transitive npm tree | Any Paperclip vendoring | `pnpm licenses list` if ever needed |
| **L-15** | Fonts in vendored LightRAG visualizer | Any DRA vendoring | Closed by exclusion |
| **L-16** | Project Happy's own deps (Part C) | **M0 exit** | **Automated license check in CI — the real control** |

---

## Part F — Maintenance

1. **CI gate (M0):** `pip-licenses` (or `reuse`) runs on every PR. A new dependency without a resolved, allowlisted license **fails the build**.
2. **Allowlist:** MIT, Apache-2.0, BSD-2/3-Clause, PSF, ISC, MPL-2.0 (**dev-only**), PostgreSQL, SIL OFL-1.1 (fonts only).
3. **Denylist:** GPL-2.0/3.0, AGPL-3.0, SSPL, BUSL, FSL, Elastic License, "Commons Clause", any bespoke company-license gate (e.g. Remotion), any RAIL variant.
4. **Review triggers:** adding a dependency; changing our own license; any decision to vendor; upstream relicensing; before any public launch or first revenue.
5. **This document is normative.** If it and a README disagree, this document wins — it was built from primary sources.
