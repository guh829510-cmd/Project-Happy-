# Discovery Phase — execution report

**Date:** 2026-08-20
**Result:** the pipeline is **built and executes end to end**. The real-data run
you asked for **did not happen**, for two environmental reasons that are
documented, evidenced, and not architectural.

> **Read this first.** This container has **no outbound web access** and **no
> Anthropic API key**. Phases 3–5 (real research, real opportunities, real cost)
> therefore could not be executed here. Everything else was executed: the
> components were installed and run, two real upstream bugs were found and
> fixed, and the full pipeline was proven end to end against local doubles with
> real Crawlee extraction, the real LiteLLM proxy, and the real budget guard.

---

## 1. What blocks the real run

### 1.1 Web egress is policy-denied

Not a misconfiguration on our side. The agent proxy rejects `CONNECT` for every
general host:

```
duckduckgo.com   -> 000    connect_rejected: gateway answered 403 to CONNECT
google.com       -> 000    connect_rejected: gateway answered 403 to CONNECT
bing.com         -> 000    connect_rejected: gateway answered 403 to CONNECT
wikipedia.org    -> 000    connect_rejected: gateway answered 403 to CONNECT
news.ycombinator -> 000    connect_rejected: gateway answered 403 to CONNECT
```

Only `pypi.org`, `files.pythonhosted.org`, npm, and the git proxy are reachable
(the proxy's own `noProxy` list). Confirmed through the tools themselves, not
just curl:

```
crawlee    : crawlee.errors.ProxyError            (real external site)
ddgs       : DDGSException: ProxyError('403 Forbidden')
```

### 1.2 No LLM credential

`ANTHROPIC_API_KEY` is unset and `runtime/llm/.env` does not exist. Every LLM
call in the run below went to the local stub.

**Neither is a design problem.** Both are one-line fixes on a machine with
network and a key.

---

## 2. Phase 1 — verification and actual execution

### 2.1 Versions and licences, re-verified from primary sources

| Component | Version | Repo `LICENSE` | Dist metadata | Ran? |
|---|---|---|---|---|
| **Crawlee** | `crawlee==1.9.2` | Apache-2.0 | `Apache-2.0` | ✅ **yes** |
| **GPT Researcher** | `gpt-researcher==0.16.0` | Apache-2.0 | ⚠️ `MIT` | ⚠️ partly |
| **SearXNG** | repo HEAD 2026-08-20 | AGPL-3.0 | `0.0.0.dev0` (placeholder) | ❌ no |
| ddgs (search backend) | `ddgs==9.15.0` | MIT | MIT | ⚠️ blocked |

**Two licensing findings:**

1. **GPT Researcher's repo says Apache-2.0, its PyPI metadata says MIT.** The
   same self-contradiction pattern we found in FinRobot. Recorded as
   `UNKNOWN — REQUIRES REVIEW`; moot while we run it as a separate service and
   copy none of its code.
2. **It depends on `pymupdf` 1.28.2 — *"Dual Licensed - GNU AFFERO GPL 3.0 or
   Artifex Commercial License"***. AGPL is now in the research dependency tree.
   Inert under our back-office rule (we run it unmodified, as our own user), but
   it must never become part of a product surface.

### 2.2 Crawlee — **executed, works**

Real `BeautifulSoupCrawler` against a local page:

```
requests_finished  1        requests_failed  0
request_avg_finished_duration  139.9ms
extracted: title, 170 chars of text, 2 links
```

Against a real external site: `crawlee.errors.ProxyError` — the extraction code
is fine, the network is not.

### 2.3 GPT Researcher — **two real upstream bugs found**

It did not run out of the box. Both defects are in the released package **and in
upstream HEAD**.

**Bug 1 — the package does not import.**

```
NameError: name 'Any' is not defined
  gpt_researcher/actions/query_processing.py:6
```

`Any`, `Dict`, `List` and `Optional` are used but never imported. Fixed by adding
the import; recorded in `runtime/research/patches/`.

**Bug 2 — declared dependency does not match the import.**

```
ImportError: Unable to import ddgs. Please install with `pip install -U ddgs`
```

It declares `duckduckgo-search` but imports `ddgs` (the renamed project). Fixed
by installing `ddgs`.

After both fixes it **imports, constructs, and begins researching** —
`🔍 Starting the research task` / `🌐 Browsing the web` — then stops at the
search step for the egress reason above. That is as far as this environment goes.

### 2.4 SearXNG — **not run**

Needs Docker (daemon down here) **and** egress to upstream engines (blocked).
The PyPI `searxng` package is a `0.0.0.dev0` placeholder, not the application.
`SearxngBackend` is implemented against its JSON API and is selected with
`--backend searxng`, but it has not been exercised.

---

## 3. Phase 2 — the pipeline, and it runs

`runtime/research/scripts/discovery.py`, 431 lines:

```
OBJECTIVE -> sub-queries (LLM) -> search -> crawl -> EVIDENCE
          -> opportunities (LLM, ranked, evidence-cited)
```

Search is pluggable — `ddgs`, `searxng`, or `fixture` — behind one small
protocol. Crawling is Crawlee. **Every LLM call goes through the existing
`SpendGate` and the existing LiteLLM proxy; there is no second LLM abstraction.**

### 3.1 Executed run (local doubles, real Crawlee, real proxy, real guard)

```
objective : Find software opportunities startable with very low capital, operable by
            a small autonomous AI team, with identifiable paying customers...
search    : fixture   budget: $1.00
search    : 4 calls, 3 unique urls
crawl     : 3 extracted, 0 failed
verdict   : opportunities_found  (1 opportunities)
cost      : $0.003516000 actual / $0.041608000 authorised
```

**Measured metrics (Phase 5 shape, real numbers for this run):**

| Metric | Value |
|---|---|
| LLM calls | 2 |
| Input / output tokens | 758 / 200 |
| Actual cost | **$0.003516** |
| Authorised (reserved) | $0.041608 |
| Search calls / hits | 4 / 12 |
| Pages crawled / failed | 3 / 0 |
| Retries | 0 |
| Failures | none |
| Duration | 6.7 s |

### 3.2 Three independent records agree

| Source | Cost |
|---|---|
| Report metrics | $0.003516 |
| Budget-guard settled | $0.003516 |
| Langfuse traces (`0.00064 + 0.002876`) | **$0.003516** |

**Budget-guard audit** — `chain_mode: hmac-sha256`, chain verifies:

```
seq=1 reserve.granted   20210000 nano   held against 6 scope(s)
seq=2 settle              640000 nano   settled
seq=3 reserve.granted   21398000 nano   held against 6 scope(s)
seq=4 settle             2876000 nano   settled
company settled: $0.003516   remaining: $0.996484
```

**Evidence is referenced**, and each opportunity cites ids:

```
E1 What freelancers pay for admin tools        214 chars
E2 Existing invoice reminder tools             271 chars
E3 Late payments are the top freelancer …      379 chars

Invoice chase automation for solo freelancers
  evidence_for: ['E1']   evidence_against: ['Incumbent tools ship reminders already.']
  difficulty=medium  cost=$25/mo  score=0.62
```

### 3.3 The system can say no

You required that the pipeline be allowed to conclude there is nothing worth
doing. The prompt states it explicitly, and the path is **exercised**:

```
verdict      : no_good_opportunities
opportunities: 0
evidence kept: 3        (evidence is retained even when the verdict is negative)
```

---

## 4. What is NOT delivered

Stated plainly, because the stop condition asks for it.

| Stop condition | Status |
|---|---|
| 1. A real research run | ❌ **Not delivered** — no egress, no API key |
| 2. Evidence-backed opportunity candidates | ⚠️ Mechanism proven; evidence is from local fixtures |
| 3. A ranked top 3 | ❌ Not delivered — needs real evidence |
| 4. Validation plans (Phase 4) | ❌ **Not attempted.** Writing them from fixture data would be fabrication |
| 5. Actual LLM cost measurements | ✅ Delivered — real metering, stub provider |
| 6. Langfuse traces | ✅ Delivered — 2 generations with cost |
| 7. Budget-guard records | ✅ Delivered — HMAC chain, verifies |
| 8. Reproducible execution instructions | ✅ Below |

**I did not write Phase 4 validation plans.** With no real evidence, they would
have been invented — the exact failure the objective warns against. The pipeline
that produces them is ready; the input is not.

---

## 5. Reproducing this — and finishing it

### 5.1 Offline (works anywhere, spends nothing)

```bash
cd runtime/llm && ./scripts/stop_all.sh
HAPPY_STUB_VERDICT=none .venv/bin/python scripts/offline_doubles.py &   # omit env for the positive path
ANTHROPIC_API_BASE=http://127.0.0.1:8090 LANGFUSE_HOST=http://127.0.0.1:8091 \
  ANTHROPIC_API_KEY=stub LITELLM_MASTER_KEY=sk-local-dev-change-me ./scripts/run_proxy.sh &

cd ../.. && export HAPPY_AUDIT_HMAC_SECRET=$(openssl rand -hex 32)
runtime/research/.venv/bin/python runtime/research/scripts/discovery.py \
  --objective "…" --backend fixture --db data/discovery.db \
  --out data/discovery_report.json --budget 1.00
```

### 5.2 The real run, on a machine with network and a key

```bash
# 1. credentials — never committed
cp runtime/llm/.env.example runtime/llm/.env
#    put a real ANTHROPIC_API_KEY in it, scoped to the $20 workspace
export HAPPY_AUDIT_HMAC_SECRET=$(openssl rand -hex 32)   # keep this outside the repo

# 2. research runtime (Python 3.12 — 0.16.0 requires >=3.12)
/usr/bin/python3.12 -m venv runtime/research/.venv
runtime/research/.venv/bin/pip install -r runtime/research/requirements.txt

# 3. proxy
cd runtime/llm && ./scripts/run_proxy.sh & cd ../..

# 4. the real run
runtime/research/.venv/bin/python runtime/research/scripts/discovery.py \
  --objective "Find software/business opportunities that can be started with very low
               capital, operated initially by a small autonomous AI team, have
               identifiable paying customers, and a realistic path to profitability." \
  --backend ddgs --queries 5 --results-per-query 6 --max-pages 12 \
  --budget 2.00 --db data/budget.db --out data/discovery_report.json
```

Optional SearXNG instead of DuckDuckGo (avoids rate limits, AGPL, run unmodified):

```bash
docker run -d -p 8888:8080 searxng/searxng
… --backend searxng --searxng-url http://127.0.0.1:8888
```

---

## 6. Chairman actions still outstanding

1. **Set the Anthropic workspace spend limit to $20.** I cannot — it is a Claude
   Console action requiring your account. Our company limit must then be set
   **below** it so our guard trips first.
2. **Provide an API key** scoped to that workspace, in `runtime/llm/.env`.
3. **Generate and store `HAPPY_AUDIT_HMAC_SECRET`** outside the repository. Without
   it the audit chain silently degrades to the unkeyed, recomputable form —
   `store.chain_mode` reports which is in force.

## 7. Audit chain — keyed, as instructed

The head is now HMAC-SHA256 with an externally held secret
(`$HAPPY_AUDIT_HMAC_SECRET`), keeping the corrected canonical hashing. No
external notarisation was built.

Proven, and the difference matters:

| Chain | Attacker with DB write access recomputes every hash | Result |
|---|---|---|
| `sha256` (no secret) | succeeds | **forgery NOT detected** |
| `hmac-sha256` (secret held) | cannot — no key | **forgery detected** |

Wrong secret is rejected; a secret under 32 bytes is refused; the secret never
appears in the database file. Nine tests cover it.

**Limitations, unchanged:** the secret lives on the same machine as the database,
so an attacker who takes the host takes both. That is what external notarisation
would fix, and you deferred it deliberately.
