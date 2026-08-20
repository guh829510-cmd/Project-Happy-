# Step 1 — LLM → LiteLLM → cost control → Langfuse

**Purpose:** prove the chain works before anything else is built.
**Date:** 2026-08-20
**Result:** **6 passed, 0 failed, 1 blocked upstream, 2 not verifiable in this environment.**

> **Headline finding, read this first:** LiteLLM 1.97.0's MIT core **enforces no
> spend ceiling without Postgres.** It *observes* cost accurately; it does not
> *cap* it. Three separate mechanisms were tested and all three are inert — root
> cause with file and line numbers in §6. Since cost control was the entire
> reason for adopting LiteLLM first, this is the one thing to decide before Step 2.

---

## 1. Exact versions

All read from the installed artifacts, not from documentation.

| Component | Version | Licence | Source of licence |
|---|---|---|---|
| litellm[proxy] | **1.97.0** | **MIT** | dist metadata `License-Expression: MIT`; repo `LICENSE` is MIT outside `enterprise/` |
| langfuse (SDK) | **2.60.10** | **MIT** | dist metadata `License: MIT` |
| fastapi | **0.120.0** | MIT | pinned — see §2 |
| uvicorn | 0.52.4 | BSD-3-Clause | transitive |
| openai | 2.54.0 | Apache-2.0 | transitive |
| pydantic | 2.13.4 | MIT | transitive |
| Python | 3.11.15 | PSF | system |

Langfuse **server** (not used in this run) is MIT outside `ee/`, `web/src/ee/`
and `worker/src/ee/`; copyright now held by **ClickHouse, Inc.**

**No Docker was used.** LiteLLM runs from a venv; the daemon was unavailable in
this environment anyway. Langfuse server would need Docker — see §5.

## 2. Two version pins that are not preferences

Both were discovered by this test. Without them nothing works.

**`fastapi==0.120.0`** — litellm 1.97.0 imports `get_flat_dependant` from
`fastapi.dependencies.utils`. pip resolves fastapi to 0.141.1 by default, where
that symbol **no longer exists**, and the proxy dies at startup with a
misleading `ModuleNotFoundError: No module named 'proxy_server'` that masks the
real `ImportError`. Verified present in 0.120.0 and 0.121.0, absent in 0.141.1.

**`langfuse==2.60.10` (2.x line, not 3.x/4.x)** — litellm 1.97.0 passes
`sdk_integration=` to the Langfuse constructor, which langfuse 3.x removed:

```
TypeError: Langfuse.__init__() got an unexpected keyword argument 'sdk_integration'
```

LiteLLM catches this as a *non-blocking* error, so the proxy keeps serving and
**silently emits no traces at all**. Verified: 3.14.0 breaks, 2.60.10 works.
This one is dangerous precisely because it fails quietly.

## 3. Configuration

`runtime/llm/config.yaml`, kept outside `src/happy/`:

| Requirement | Setting | Verified |
|---|---|---|
| 5 · single provider | `anthropic/claude-sonnet-5` | ✅ |
| 6 · key from environment | `api_key: os.environ/ANTHROPIC_API_KEY` | ✅ never in code or config |
| 8 · spend ceiling | `litellm_settings.max_budget: 5.00` + `general_settings.max_budget: 5.00` | ⚠️ **both inert — §6** |
| 9 · request timeout | `timeout: 30`, `request_timeout: 30` | ✅ enforced |
| 10 · retry limit | `num_retries: 2`, `allowed_fails: 3` | ✅ enforced |
| 11 · max output tokens | `max_tokens: 512` | ⚠️ default, not a ceiling — §6 |
| 12 · cost metadata | `success_callback`/`failure_callback: ["langfuse"]` | ✅ |

Secrets: `.env.example` holds names only; `.env` is gitignored; the provider key
is resolved by the proxy at runtime and never reaches the client, the config, or
the repository. A scan of everything committed found no credential-shaped strings.

## 4. Results

Run: `.venv/bin/python scripts/smoke.py`

```
[PASS   ] 13 request through LiteLLM: HTTP 200, reply='Project Happy step one online.'
[PASS   ] 15 cost observable: x-litellm-response-cost=0.00012, usage={'completion_tokens': 10,
           'prompt_tokens': 10, 'total_tokens': 20, ...}
[PASS   ] 11 max_output_tokens applied: completion_tokens=10 (configured default 512)
[PASS   ] 14 Langfuse trace received: 1 ingestion POST(s), 2 event(s), usage/cost present=True
[BLOCKED] 16 exceeded cost limit rejected: litellm 1.97.0 core enforces no spend ceiling
           without Postgres; cost is observable but not capped
[PASS   ]  9 request timeout enforced: upstream slept 6s, 3s timeout -> HTTP 408 after 13.3s
[PASS   ] 17 continues after failure: forced failure -> HTTP 500; next request -> HTTP 200

6 passed, 0 failed, 1 blocked upstream
```

### 4.1 Successful request (13)

`POST /v1/chat/completions` → HTTP 200, `"Project Happy step one online."`,
`prompt_tokens=10`, `completion_tokens=10`.

### 4.2 Trace confirmation (14)

Captured Langfuse ingestion payload, verbatim fields:

```
POST /api/public/ingestion
  type: trace-create       name: litellm-acompletion
  type: generation-create  name: litellm-acompletion
    model:        "anthropic/claude-sonnet-5"
    usage:        {"input": 10, "output": 10, "unit": "TOKENS", "totalCost": 0.00012}
    usageDetails: {"input": 10, "output": 10, "total": 20,
                   "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
```

Four ingestion POSTs were captured across the run — successes carry usage and
`totalCost`; the forced failure produced a trace with no usage, confirming
`failure_callback` fires too. **Cost accounting reaches the observability layer.**

### 4.3 Measured cost (15)

| Source | Value |
|---|---|
| Response header `x-litellm-response-cost` | **0.00012** |
| Langfuse `totalCost` | **0.00012** |
| Second request (4 in / 10 out) | 0.000108 |

The two agree. This is a **real pricing-table lookup** against LiteLLM's cost map
for `anthropic/claude-sonnet-5` on real token counts — arithmetic that is
identical whether the upstream is the stub or the vendor.

### 4.4 Timeout (9)

Upstream made to sleep 6 s, per-request timeout 3 s → **HTTP 408** after 13.3 s.
The 13.3 s is 3 attempts × ~3 s plus backoff, consistent with `num_retries: 2`,
so this single test evidences requirements 9 and 10 together. Proxy log shows
`LiteLLM Retried: 2 times`.

### 4.5 Failure and recovery (17)

Forced upstream 500 → proxy returned 500 after retrying twice; the **next request
returned 200**. Observed status distribution across the run: `2×200, 1×408, 1×500`.
The proxy does not wedge after a failure.

## 5. What this run did NOT prove

Stated plainly, because the point of the step was proof.

| Not verified | Why | What closes it |
|---|---|---|
| **A real Anthropic API call** | No provider key exists in this environment | On your machine: put a real key in `.env`, set `ANTHROPIC_API_BASE=https://api.anthropic.com`, rerun `smoke.py`. Only the endpoint changes — the provider code path, cost table, callbacks and limits are already exercised |
| **The Langfuse UI showing the trace** | Docker daemon unavailable here; ingestion was captured by a local listener instead | Either Langfuse Cloud free tier (set 3 env vars) or `docker compose -f docker-compose.langfuse.yml up` |

**Everything between the client and the provider is real:** the real LiteLLM
proxy, its real `anthropic` provider code path, real token counts, real pricing
lookup, real callbacks, real retry and timeout behaviour. The stub replaces only
the vendor's HTTP endpoint.

**On Langfuse self-hosting and your low-spec constraint:** Langfuse v4 self-hosted
is **six containers** — web, worker, ClickHouse, MinIO, Redis, Postgres —
roughly 4 GB RAM. That fails your "lightweight enough" test. The compose file is
committed for the VPS; **Langfuse Cloud's free tier is the recommendation for
local**, and switching is one env var (`LANGFUSE_HOST`).

## 6. Remaining issues

### 6.1 No spend ceiling without Postgres — **decide before Step 2**

Three mechanisms tested, all inert on the MIT core:

| Mechanism | Status | Root cause |
|---|---|---|
| `litellm_settings.max_budget` | **Dead code** | Checked at `utils.py:1317` against `litellm._current_cost`. The counter's only increment (`litellm_logging.py:1897`) is guarded by `isinstance(result, dict) and "content" in result` — a completion returns a `ModelResponse` with `choices`, so it never fires. Confirmed empirically: `_current_cost` stayed `0.0` across repeated calls with `max_budget=1e-07` |
| `general_settings.max_budget` | **Requires a database** | `proxy_server.py:1140`: `if prisma_client is not None and litellm.max_budget > 0` |
| `general_settings.max_request_size_mb` | **Enterprise-only** | `auth_utils.py:793` logs *"this is an enterprise only feature"* and returns `True` — i.e. allows the request. `enterprise/` is outside the MIT core and we excluded it |

**Consequence:** today the proxy reports cost precisely and caps nothing.

**The supported fix, which is integration rather than reinvention:** add Postgres
and use LiteLLM's **virtual keys with per-key `max_budget`** — its documented,
MIT-core mechanism, and the same feature we would rely on in production anyway.
Postgres is one container of roughly 150 MB, unlike Langfuse's six.

**Do not** write a custom budget subsystem. If Postgres is unacceptable locally,
the alternative is a per-tick spend check in the ~1,000-line control layer that
is already planned — using the cost figures LiteLLM already reports correctly.
That is a decision for you, not one to take silently.

### 6.2 `max_tokens` is a default, not a ceiling

A client sending `max_tokens: 999999` is **accepted** (HTTP 200); the configured
512 is a default that callers override. LiteLLM core ships no request-parameter
ceiling. Low impact while we write every caller, but it means the config is not a
guarantee against a future misbehaving component.

### 6.3 Smaller notes

- LiteLLM's startup error masks the real cause: a failed import inside
  `proxy_server` surfaces as `ModuleNotFoundError: No module named 'proxy_server'`.
  When the proxy will not start, read the **first** traceback, not the last.
- A broken Langfuse callback is non-blocking and **silent**. Worth asserting that
  traces arrive, not assuming it.
- `pkill -f`/`pgrep -f` match this session's own shell; `scripts/stop_all.sh`
  stops processes by listening port instead.
- One earlier FAIL in this run was my own test harness, not LiteLLM: a restarted
  stub failed to bind because the old process still held the port, so stale code
  served the request. Fixed by `stop_all.sh` before restart.

## 7. Files added

```
runtime/llm/
├── README.md                     how to run it
├── requirements.txt              pinned, with the reason for each pin
├── config.yaml                   the only LiteLLM configuration
├── .env.example                  names only; .env is gitignored
├── docker-compose.langfuse.yml   optional self-host, for the VPS
└── scripts/
    ├── run_proxy.sh              start the proxy
    ├── stop_all.sh               stop by port
    ├── offline_doubles.py        stub provider + trace capture (verification aid)
    └── smoke.py                  the seven checks above
docs/runtime/LLM_SMOKE_TEST.md    this file
```

No application code was written. `src/happy/` is untouched. The port layer was
not expanded. No new abstractions were introduced.

## 8. Verdict

**LLM → LiteLLM → observability works, and is ready to build on.**
**LLM → LiteLLM → *cost control* does not yet, and needs your decision (§6.1).**

Two things remain for you to run on your own machine: one real provider call, and
Langfuse receiving it. Both are single-command steps with the artefacts committed.

Stopping here as instructed. Not proceeding to Step 2.
