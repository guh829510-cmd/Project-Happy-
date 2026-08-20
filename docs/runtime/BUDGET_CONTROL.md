# Budget Control

**Two independent controls, with different jobs.**

| | Our guard | Anthropic workspace limit |
|---|---|---|
| **Purpose** | Precise application-level authorisation | Protection against bugs in our application |
| **Granularity** | Per-request, agent, task, daily, monthly, company | Monthly, per workspace/organisation |
| **Enforced by** | Our SQLite store, before LiteLLM is called | Anthropic, on every request |
| **Fails if** | Our code is wrong | Anthropic is wrong |
| **Blast radius** | One request refused | Every request in the workspace refused |

Neither replaces the other. The guard is the authority on what may be spent;
the provider limit is the thing that still holds when the guard is broken.

---

## 1. The path

```
REQUEST
  → estimate worst-case cost      (litellm.token_counter + get_model_info)
  → reserve against 6 limits      (one BEGIN IMMEDIATE transaction)
  → ALLOW / DENY                  ← denial stops here; provider never contacted
  → LiteLLM proxy
  → Anthropic                     ← workspace spend limit applies here
  → actual cost
  → settle / release              (same transaction discipline)
  → audit (hash-chained)
  → Langfuse trace
```

## 2. Why the estimate is a bound, not a guess

```
worst_case = input_tokens × (1 + margin) × input_price
           + max_output_tokens × output_price
```

Output cannot exceed `max_output_tokens` because the gate sends that value.
Input is measured with `litellm.token_counter` and inflated by a **25% margin**,
because that function has no Anthropic-specific tokenizer and may undercount.
Both terms bound from above, so the reservation cannot be too small.

If either term is unavailable — no price for the model, no token count — there
is no bound, and **no bound means no call** (`Unpriceable`).

Measured on the live path: 12 input tokens, 64 max output tokens →
**bound $0.000670**, actual **$0.000116**. The reservation held 5.8× the eventual
cost for the duration of the call, then released the difference.

## 3. The six limits

Every reservation is checked against all applicable scopes **in one transaction**.
Any one of them refusing refuses the request.

| Scope | Key example | Refuses when |
|---|---|---|
| `request` | `smoke` | a single call is too expensive |
| `agent` | `research_analyst` | one agent has spent its allowance |
| `task` | `task-1` | one unit of work has cost too much |
| `daily` | `2026-08-20` | today's spend is exhausted |
| `monthly` | `2026-08` | this month's spend is exhausted |
| `company` | `global` | the autonomous spending ceiling is reached |

**A scope with no declared limit denies.** No limit is not permission.

## 4. Guarantees, and how each is obtained

| Requirement | How |
|---|---|
| Estimate before the call | `estimate_max_cost()` is pure; nothing has been sent |
| `max_tokens` as the output bound | The gate sends it; the bound uses the same value |
| Conservative input margin | 25%, applied before pricing |
| Reserve the maximum first | `reserve()` holds the bound across every scope |
| Failed reservation → no call | `invoke` is only reached after `reserve()` returns |
| Record actual cost | `settle()` writes the real figure |
| Release the unused hold | `settle()` subtracts the reservation, adds the actual |
| Failed call → hold released | `except BaseException` → `release()`, then re-raise |
| Concurrency safe | `BEGIN IMMEDIATE`; check and increment are one write |
| Survives restart | SQLite WAL; reserved amounts are rows, not memory |
| Never negative | `CHECK (… >= 0)` plus `MAX(0, …)` on every decrement |
| No bypass of an authorised request | `request_id` is `UNIQUE`; a reservation settles once |
| Everything audited | Hash-chained rows written in the same transaction |

### 4.1 Where the money is held during a call

A reservation holds the **worst case** from authorisation until settlement.
Concurrent callers see the held amount as already spent, so the sum of
authorised spend can never exceed a limit even mid-flight. The unused portion
returns at settlement.

### 4.2 What happens when things go wrong

| Situation | Behaviour |
|---|---|
| Provider returns no cost, a negative, `NaN`, `inf`, or garbage | Settles at the **full reserved amount**. Charging ourselves the maximum we authorised is the only safe reading of a response we cannot believe |
| Provider charges more than we bounded | Recorded as an `overrun` in the audit; the limit is now breached, so further reservations refuse |
| Call raises (HTTP error, timeout, crash mid-flight) | Hold released in full; a call that never reached the provider must not consume budget |
| Process dies between reserve and settle | The hold **stays** until its TTL (default 15 min), then `expire_stale()` reclaims it. A crash costs headroom, never control |
| The same request is authorised twice | Refused — `request_id` is unique |
| A cost below one nanodollar | Rounds **up** to 1. Rounding to zero would let unlimited requests through a finite budget |

## 5. Measured evidence

**Concurrency — the headline invariant.**

```
8 workers × 60 attempts, $0.05 each, limit $1.00
authorised          = 20        (theoretical maximum = 20)
committed           = $1.000000000
AUTHORIZED <= LIMIT = True
audit entries       = 480       (20 granted + 460 denied), chain verifies
```

Not one authorisation over the limit, and not one wasted below it.

**Denial does not reach the provider.** With the limit set below the bound, the
client refused and the proxy's request count did not move.

**End-to-end, through the real LiteLLM proxy:**

```
input tokens       : 12
max output tokens  : 64
authorised (bound) : $0.000670000
actual cost        : $0.000116000
company remaining  : $0.999884000
open reservations  : ()
audit entries      : 2 (chain verifies)
Langfuse trace     : totalCost 0.000116   ← matches the settled figure
```

**649 tests pass**, including 57 adversarial budget tests. `ruff` and
`mypy --strict` clean.

## 6. The provider backstop

Anthropic evaluates spend limits at **organisation and workspace level on every
request**. A workspace limit may be set lower than the organisation's, and
`POST /v1/organizations/spend_limits` exists for programmatic management.

**Set it, and set it low.** Recommended: a workspace dedicated to this system,
with a monthly limit slightly above the company-wide limit configured in our
guard. Then:

- if our guard works, the provider limit is never reached;
- if our guard has a bug, the provider limit stops the bleeding at a known
  number;
- if the provider limit is hit, that is itself the alarm that the guard failed.

**What the backstop does not do:** it is monthly, so it cannot express a daily,
per-agent or per-task limit; it covers only Anthropic, not Stripe, hosting or
domains; and recovering from it needs a human. It is a circuit breaker of last
resort, not a budget.

### 6.1 Configuration checklist (Chairman)

1. Create a workspace in the Claude Console dedicated to this system.
2. Set its monthly spend limit — start at **$20**.
3. Issue an API key **scoped to that workspace**, not an organisation-wide key.
4. Put that key in `runtime/llm/.env`. Never anywhere else.
5. Set the guard's company limit **below** the workspace limit, so our control
   trips first and the provider limit stays an emergency.

## 7. Operating it

```bash
# configure limits (once)
python - <<'EOF'
from happy.governance.budget_store import BudgetStore
s = BudgetStore("data/budget.db")
s.set_limit("company", "global",     "20.00")
s.set_limit("monthly", "2026-08",    "20.00")
s.set_limit("daily",   "2026-08-20",  "2.00")
EOF

# inspect
python -c "
from happy.governance.budget_store import BudgetStore
s = BudgetStore('data/budget.db')
print('remaining today:', s.remaining('daily','2026-08-20'))
print('open holds     :', s.open_reservations())
s.verify_audit(); print('audit verifies')"
```

Reclaim holds orphaned by a crash with `store.expire_stale(datetime.now(UTC))`.

## 8. Known limitations

1. **`token_counter` is approximate for Anthropic** — no provider-specific
   tokenizer exists in LiteLLM. Mitigated by the 25% margin, which makes the
   bound conservative rather than wrong. If real traffic shows the margin is
   too tight, raise it; it costs headroom, not correctness.
2. **The guard covers LLM spend only.** Stripe, hosting and domain costs are
   not yet gated. They will need the same treatment before the company
   transacts.
3. **Enforcement depends on holding the LiteLLM key.** The guard is authoritative
   because it is the only holder of the proxy key. If that key ever leaks into
   another component, that component bypasses the guard.
4. **The audit chain is unkeyed** — tamper-evident against corruption and
   careless edits, not against an attacker with write access who recomputes it.
   See `docs/security/GOVERNANCE_CRYPTO_REVIEW.md`.
