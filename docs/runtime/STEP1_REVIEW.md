# Step 1 Review — budget enforcement options and governance-code provenance

**Date:** 2026-08-20
**Status:** Investigation only. Nothing implemented, no PostgreSQL added, no code deleted.
**Companion:** [`LLM_SMOKE_TEST.md`](LLM_SMOKE_TEST.md)

All findings below were verified against the installed artifacts and the local
repository, not from documentation. File and line references are to
`litellm==1.97.0` as installed in `runtime/llm/.venv`.

---

# SECTION A — Budget enforcement options

## A.0 What has to be true

The financial boundary is non-negotiable and must cover six limits:

| # | Limit | Natural scope key |
|---|---|---|
| 1 | Per-request token/cost | the request itself |
| 2 | Per-agent budget | `agent_id` |
| 3 | Per-task budget | `task_id` |
| 4 | Daily budget | `date` |
| 5 | Monthly budget | `year-month` |
| 6 | Company-wide autonomous spend | global |

And the required shape is:

```
REQUEST → CHECK AUTHORIZED BUDGET → ALLOW / DENY → LLM → RECORD ACTUAL COST
```

The check must happen **before** the call, and reported cost must not be the
enforcement mechanism. That rules out anything that only reconciles afterwards.

### A.0.1 The fact that makes pre-call enforcement possible

A **hard upper bound on a request's cost is computable offline, before the call**,
because output is capped by `max_tokens`:

```
worst_case = input_tokens × input_price + max_tokens × output_price
```

Every term is available locally. Measured just now, with no network call:

| Call | Result |
|---|---|
| `litellm.token_counter(model, messages)` | `13` input tokens |
| `litellm.get_model_info(model)` | `input_cost_per_token=2e-06`, `output_cost_per_token=1e-05`, `max_output_tokens=128000` |
| Worst case for 13 in / 512 max out | **$0.005146** |
| `litellm.cost_per_token(model, 10, 10)` | `$0.00012` — matches the observed header exactly |

This is the whole basis of Option B. It is a *bound*, not an estimate: actual
cost cannot exceed it provided `max_tokens` is enforced rather than merely
defaulted (Step 1 finding §6.2 — clients can currently override it).

---

## A.1 Option A — LiteLLM + PostgreSQL virtual keys

| Property | Finding |
|---|---|
| **Enforcement point** | `litellm/proxy/auth/auth_checks.py` — key, user, team and project budget checks during authentication |
| **Before the request?** | **Yes.** Auth runs before routing to the provider |
| **Accuracy** | **Lagging.** Spend is flushed in batches every `PROXY_BATCH_WRITE_AT` (**default 10 s**, `constants.py:1506`). LiteLLM's own comment, verbatim: *"The DB row is a LAGGING authoritative floor, not post-request truth… it can exclude this request's just-recorded cost and other buffered spend"* |
| **Failure behaviour** | Configurable via `general_settings.allow_requests_on_db_unavailable`. Default fail-closed; if enabled, requests proceed **unbudgeted** under a fallback identity (`DB_UNAVAILABLE_FALLBACK_USER_ID`). Enforcement is therefore only as available as Postgres |
| **Race behaviour** | Bounded overspend within the flush window. LiteLLM mitigates with in-memory counters and reconciliation, but concurrent requests can transiently exceed a limit before the batch lands |
| **Persistence** | Postgres |
| **Restart recovery** | Yes — survives proxy and host restart |
| **Resources** | Postgres container ≈150–250 MB plus the proxy. Requires Docker or a native install |
| **Complexity** | **Lowest custom code — zero.** Configuration and key provisioning only |
| **Cost** | $0 in software; RAM and operational burden |
| **Low-spec local?** | **Marginal.** Adds a database daemon to a machine we chose SQLite to avoid |

**Covers:** per-key (≈per-agent), team, user, global, and time-windowed budgets.
**Does not cover:** per-request cost bound, per-task budget, or non-LLM spend.

## A.2 Option B — LiteLLM without PostgreSQL + a minimal pre-call gate

| Property | Finding |
|---|---|
| **Enforcement point** | A `CustomLogger.async_pre_call_hook`, invoked by the proxy at `litellm/proxy/utils.py:1442`. **Verified: that code path contains no `prisma_client` reference — it is not gated on a database** |
| **Before the request?** | **Yes**, and it can both reject and *mutate* the request — so the same hook can clamp `max_tokens`, closing Step 1 finding §6.2 |
| **Accuracy** | Cost bound is **exact given token counts**; the residual risk is `token_counter` accuracy. `litellm.token_counter`'s source contains no Anthropic-specific tokenizer branch, so input counting is an approximation for this provider and needs a safety margin. Output is bounded exactly by the clamped `max_tokens` |
| **Failure behaviour** | Ours to define, and it can be **fail-closed by construction**: no authorisation, no call |
| **Race behaviour** | Ours to handle. **Measured below (A.4): zero overspend under 8 concurrent threads** |
| **Persistence** | SQLite file |
| **Restart recovery** | Yes — durable across restarts; WAL survives an unclean stop |
| **Resources** | Effectively zero. No daemon, no container, stdlib `sqlite3` |
| **Complexity** | Small custom code. Estimate ≈200 new lines (A.5) |
| **Cost** | $0 |
| **Low-spec local?** | **Yes** — this is the only option with no additional process |

**Covers:** all six limits, because the scope key is ours to choose.
**Risk:** it is custom code, which the project principle discourages. Size is the mitigation.

## A.3 Option C — provider-native limits + LiteLLM observability

| Property | Finding |
|---|---|
| **Enforcement point** | Anthropic's own infrastructure: organisation and workspace **spend limits**, evaluated on every request; a `POST /v1/organizations/spend_limits` API exists for programmatic management |
| **Before the request?** | **Yes** — the provider rejects it |
| **Accuracy** | **Exact.** It is the billing system itself; nothing to estimate |
| **Failure behaviour** | Hard stop for everything in that workspace. Cannot be bypassed by our bugs — its great virtue |
| **Race behaviour** | Not our problem; provider-side |
| **Persistence / restart** | Provider-side; unaffected by anything we run |
| **Resources** | **Zero** |
| **Complexity** | Console configuration |
| **Cost** | $0 |
| **Low-spec local?** | **Yes** |

**Covers:** monthly organisation and workspace caps — limits 5 and 6.
**Does not cover:** per-request, per-agent, per-task, or daily limits. Granularity
is monthly and the blast radius is total: hitting the cap halts every venture at
once, and clearing it requires a human. It also covers only Anthropic spend —
not Stripe, hosting, domains or any other company cost.

## A.4 The SQLite question, tested rather than asserted

**Can a lightweight SQLite mechanism safely provide pre-call authorisation?**
Measured, using only the standard library:

```
8 threads × 60 attempts, 30c each, limit 1000c
  authorised = 33     spent = 990c    limit = 1000c    OVERSPEND = NO
  theoretical maximum without any race = 33  →  got exactly 33
```

Pattern: WAL mode, `BEGIN IMMEDIATE`, and a single conditional statement —

```sql
UPDATE budget SET spent = spent + :cost
 WHERE scope = :scope AND spent + :cost <= limit;
```

`rowcount == 1` is the authorisation; `rowcount == 0` is the denial. The check
and the decrement are one atomic write, so no two concurrent requests can both
see room that only one can have. This is a well-trodden pattern, not an
invention, and it needs no server, no daemon and no new dependency.

**Answer: yes, and it does not require a large subsystem.**

## A.5 How small can Option B actually be?

The project already contains a `BudgetGuard` (`src/happy/governance/budget_guard.py`,
222 lines — see Section B) implementing `reserve` / `commit` / `release` over
scoped limits, with reservations precisely so two concurrent authorisations
cannot double-spend. It is **in-memory only**, which is its single gap.

| Piece | Status | Estimated new lines |
|---|---|---|
| Scoped reserve/commit/release semantics | **Already exists** | 0 |
| SQLite persistence for that guard | To write | ≈120 |
| LiteLLM `async_pre_call_hook` (estimate → reserve → allow/deny → clamp `max_tokens`) | To write | ≈60 |
| Reconcile actual cost from the response callback | To write | ≈40 |
| **Total new code** | | **≈220 lines** |

That is the honest floor. It is not a budget framework; it is a table, a
conditional `UPDATE`, and one hook.

## A.6 Comparison against the six required limits

| Limit | A (Postgres) | B (pre-call + SQLite) | C (provider) |
|---|---|---|---|
| 1 · Per-request cost | ✗ | **✓** | ✗ |
| 2 · Per-agent | ✓ (per key) | **✓** | ✗ |
| 3 · Per-task | ✗ | **✓** | ✗ |
| 4 · Daily | ✓ (budget_duration) | **✓** | ✗ |
| 5 · Monthly | ✓ | ✓ | **✓** |
| 6 · Company-wide | ✓ (LLM only) | ✓ (LLM only) | **✓ (LLM only, unbypassable)** |
| Enforced before the call | ✓ | ✓ | ✓ |
| Independent of our code being correct | ✗ | ✗ | **✓** |
| Runs on a low-spec machine | marginal | **✓** | **✓** |
| Custom code | none | ≈220 lines | none |

**No single option covers everything.** A and B are equivalent in coverage
except that B also gives per-request and per-task limits, at the price of ~220
lines instead of a database. C covers less but is the only one that still holds
when our code is wrong.

---

# SECTION B — Governance code provenance

## B.1 The twelve questions

**1. Which commit introduced it?**
`4b6aa8729f15fe28f8cb9925d905242847b6728f`, "feat(governance): the governance
kernel — deny list, tokens, approvals, audit", 2026-08-20 10:32:50 +0000.
Parent `0b97947` — the documentation commit from the research phase. It is the
only commit touching `src/happy/governance/`.

**2. Which files?** 25 files, +4,824 lines:

| Area | Lines |
|---|---|
| `src/happy/governance/` (13 modules) | **2,460** |
| `tests/unit/governance/` + `tests/policy/test_governed_port_enforcement.py` | **2,078** |
| `src/happy/core/protocols.py` (new — `Clock`, `IdFactory`) | 55 |
| `tests/conftest.py` (modified) | +129 |
| `docs/architecture/adr/` (ADR-0002 + index) | 103 |

**3. Who or what generated it?**
Git records author **and** committer as `Claude <noreply@anthropic.com>`. It is
**AI-generated, not Chairman-authored**. It was produced by a different session
running concurrently with Step 1 and pushed to the same branch; I integrated it
by rebasing rather than discarding another session's work.

**4. What functionality does it provide?**

| Module | Lines | Purpose |
|---|---|---|
| `denylist.py` | 312 | T4 prohibitions as data, whole-word matching |
| `policy.py` | 348 | Composes the enforcement layers |
| `gateway.py` | 371 | Human approval: deny-by-default, expiry, cooling-off, single-use |
| `capability.py` | 229 | HMAC-SHA256 signed scoped tokens |
| `budget_guard.py` | **222** | **Scoped reserve/commit/release — directly relevant to Section A** |
| `audit.py` | 199 | Hash-chained audit log |
| `governed_port.py` | 178 | The mandatory proxy of ADR-0002 |
| `classifier.py` | 160 | Deterministic risk tiering; can only raise |
| `action.py` | 133 | The governed unit |
| `errors.py` | 101 | Governance errors |
| `__init__.py` | 79 | Public surface |
| `kill_switch.py` | 68 | Global stop |
| `hashing.py` | 60 | Canonical digest + secret redaction |

**5. Is any of it currently required?**
**Partly.** `budget_guard`, `audit`, `hashing`, `errors` and `action` are exactly
what Section A's recommendation needs. The remaining ~1,900 lines are not
required by anything that exists today — nothing calls them.

**6. Does it duplicate functionality we have not yet approved?**
It does not duplicate; it **pre-empts**. `FINAL_SYSTEM_COMPOSITION.md` §2.10
budgeted **≈1,000 lines** for the entire control layer. This is **2,460 source
lines — roughly 2.5×** — and it arrived while the standing instruction was
"Do NOT start implementing the CEO, CFO, CRM, research engine, or other custom
subsystems yet."

**7. Does it introduce dependencies?**
**No.** Imports are stdlib (`hashlib`, `hmac`, `json`, `re`, `uuid`, `decimal`,
`datetime`, `enum`, `collections`, `typing`) plus `pydantic`, which was already
a project dependency. **Zero new third-party packages.**

**8. Does it create architectural coupling?**
**Minimal, and in the right direction.**
- Nothing outside `src/happy/governance/` imports it — it is a **leaf**.
- `core` does not import `governance` (only mentions it in docstrings), so the
  inward-only dependency rule of ARCHITECTURE_V2 §2 holds.
- It did add `core/protocols.py`, but that module was already in the planned
  layout, and it is 55 lines of `Clock`/`IdFactory` protocols.

**Removing it would break nothing**, which is the cleanest possible coupling result.

**9. Does it contain security-sensitive logic?**
**Yes — three kinds, and they deserve review before being relied on:**
- HMAC-SHA256 capability tokens with `hmac.compare_digest` and a minimum secret
  length (`capability.py:96–167`);
- a hash-chained audit log with a fixed genesis hash (`hashing.py`, `audit.py`);
- secret redaction applied before anything is written to the audit record.

The intent is sound and the constructions are conventional. Security-sensitive
code that nothing yet calls is not urgent — but it must not be trusted merely
because tests pass.

**10. Does it have tests?** Yes — **235 tests**, 2,078 lines.

**11. Does it pass the existing suite?**
**Yes.** Full suite **530 passed** (295 pre-existing + 235 new), `ruff` clean,
`mypy --strict` clean across 36 source files. It required no change to my Step 1
work. The only integration friction was `pytest-asyncio` missing from my
environment — a declared dev dependency, not a defect.

**12. Does it violate the "minimum custom code" principle?**
**Yes, on scope and timing; no, on quality.** It is 2.5× the approved budget for
the control layer, written before any capability needed it, in a project whose
stated first principle is to integrate rather than build. That it is well-made,
dependency-free and well-tested does not make it requested.

## B.2 Summary judgement

| Dimension | Assessment |
|---|---|
| Quality | High — no new dependencies, leaf module, 235 tests, lint and strict typing clean |
| Correctness of direction | Consistent with ARCHITECTURE_V2, which the Chairman approved |
| Authorisation | **Not requested.** Contradicts the explicit "Step 1 only" instruction |
| Volume | 2,460 source lines against a ~1,000-line budget for the *whole* control layer |
| Risk of keeping | Invites building on unapproved scope; security-sensitive code unreviewed |
| Risk of deleting | Loses ~480 lines that Section A's recommendation would otherwise rewrite |
| Cost of keeping | Near zero — nothing imports it, no dependencies, no runtime cost |

---

# SECTION C — Recommendation

## C.1 Budget enforcement: **B as the mechanism, C as the backstop. Not A.**

**Adopt Option B** (pre-call gate + SQLite) **and Option C** (Anthropic workspace
spend limit) together. They fail in different ways, which is the point.

**Why not A:** it buys nothing B does not, costs a database daemon on a low-spec
machine, misses per-request and per-task limits entirely, and its accuracy is
explicitly lagging — LiteLLM's own source calls the spend row a *"LAGGING
authoritative floor, not post-request truth."* Adding Postgres to get a weaker
guarantee than a conditional `UPDATE` already provides is the wrong trade.

**Why B:** it is the only option that enforces all six limits before the call. The
worst-case bound is real arithmetic on locally-available numbers, the atomic
`UPDATE` is proven race-safe here, it is fail-closed by construction, and it
needs no new process. The same hook also clamps `max_tokens`, closing Step 1
finding §6.2.

**Why C alongside it:** every other layer depends on our code being correct.
The Anthropic workspace cap does not. It is free, takes minutes in the console,
and is the only control that still holds when we have a bug. **Set it now,
regardless of what else is decided** — it is the cheapest risk reduction available.

**Do not** trust LiteLLM's reported cost as enforcement, per your instruction. Use
it only to reconcile the reservation afterwards — reserve the bound before, settle
the actual after.

**Two things I would want you to know before deciding:**
1. `token_counter` has no Anthropic-specific tokenizer path, so input counts are
   approximate for this provider. Mitigation is a safety margin (e.g. +20%) on
   the input estimate, which makes the bound conservative rather than wrong.
2. This is ~220 lines of custom code. It is the smallest option that meets a
   non-negotiable requirement, but it is custom code, and I would rather say so
   plainly than present it as free.

## C.2 Governance code: **retain, freeze, do not build on it.**

Not deleting, not adopting. Specifically:

**Retain and use now (≈480 lines)** — `budget_guard`, `audit`, `hashing`,
`errors`, `action`. These are precisely what C.1 needs. Reusing `BudgetGuard`
rather than rewriting reserve/commit/release is the "integration over
reinvention" principle applied to our own tree.

**Freeze (≈1,900 lines)** — `denylist`, `classifier`, `capability`, `gateway`,
`policy`, `governed_port`, `kill_switch`. Keep them in the tree: they cost
nothing, nothing imports them, and removing them destroys work that will
plausibly be wanted. But **do not extend them, do not wire them in, and do not
treat their existence as approval for the scope they represent.** Each module
gets re-evaluated when a real capability needs it — the same build/buy/adapt test
everything else faces.

**Before any of the frozen code is relied on**, the HMAC token and hash-chain
implementations need a deliberate security review. Passing tests written by the
same author that wrote the code is not that review.

**On process:** a second session pushing 4,824 unrequested lines to your branch
during a "Step 1 only" instruction is worth preventing, not just correcting.
If concurrent sessions continue, they need explicit scope boundaries — otherwise
this recurs and the "minimum custom code" principle erodes one well-written
commit at a time.

## C.3 What I would do next, on your word

1. Set the Anthropic workspace spend limit (minutes, free, no code).
2. Implement the ~220-line pre-call gate reusing the existing `BudgetGuard`.
3. Re-run the Step 1 smoke test with check 16 expected to **PASS**.

Nothing has been implemented. No PostgreSQL added. No code deleted. No new
frameworks or architecture. Stopping here for your decision.
