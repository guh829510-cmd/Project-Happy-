# Security Review — frozen governance cryptography

**Scope:** `capability.py` (HMAC tokens), `hashing.py` (canonicalisation, chain,
redaction), and the audit chain that uses them.
**Status of the code reviewed:** frozen. Not wired into any execution path.
**Method:** the code was read, then probed with **62 independently written
adversarial tests** (`tests/security/test_crypto_adversarial.py`). The author's
own tests were not used as evidence — where a claim is made in a docstring, the
test attacks the claim.

**Verdict: 6 PASS, 1 FIXED, 4 NEEDS_REVIEW, 0 FAIL.**

One demonstrable defect was found and fixed. The remaining findings are design
limitations that must be resolved before the frozen components are activated —
none of them is exploitable today, because none of the code is reachable.

---

## Summary

| # | Area | Classification |
|---|---|---|
| 1 | HMAC signing | **PASS** |
| 2 | Token construction | **PASS** |
| 3 | Token verification | **PASS** |
| 4 | Timing-safe comparison | **PASS** |
| 5 | Authorisation boundaries | **PASS** |
| 6 | Hash-chain construction | **PASS** |
| 7 | **Canonical serialisation** | **FIXED** — was a real defect |
| 8 | Nonce / replay protection | **NEEDS_REVIEW** |
| 9 | Token revocation | **NEEDS_REVIEW** |
| 10 | Audit chain is unkeyed | **NEEDS_REVIEW** |
| 11 | Secret redaction coverage | **NEEDS_REVIEW** |

---

## 1. HMAC signing — PASS

`hmac.new(secret, canonical_json(payload).encode(), "sha256")`, minimum secret
length 32 bytes enforced at construction.

Verified independently:
- A token minted under one secret does not verify under another.
- The signature is **not** a bare SHA-256 of the payload — an attacker who knows
  the payload cannot recompute it without the key.
- The signature reproduces exactly when the MAC is recomputed from the spec.
- A secret shorter than 32 bytes is refused at construction.

## 2. Token construction — PASS

Minting refuses, at issue time:
- any capability in `FORBIDDEN_CAPABILITIES` (i.e. `MONEY_MOVE`);
- `max_tier = T4` — no token can authorise a prohibited action;
- a non-positive TTL — no non-expiring token exists;
- an empty `port_ids` — a token granting nothing is not minted.

`signing_payload()` **excludes the signature**, avoiding the self-reference bug
where a token signs over its own signature.

**One footgun, recorded not classified as a defect:** an empty `operations` set
means *any* operation on an allowed port. The empty value is the **wider** grant.
That inverts the usual intuition, and a caller who forgets the field gets more
authority than they expected. Worth a rename or an explicit `ANY` sentinel before
activation.

## 3. Token verification — PASS

Verified independently across **ten** signed fields — `subject`, `port_ids`,
`capabilities`, `operations`, `max_tier`, `budget_usd`, `venture_id`, `token_id`,
`expires_at`, `issued_at`. Altering any one invalidates the signature.

Also verified: empty signature rejected; single-character change rejected;
truncated signature rejected; a JSON round-trip still verifies, and an edit made
during that round-trip does not.

Expiry uses `now >= expires_at`, so the token is dead **at** its expiry instant,
not one tick later. Confirmed at the boundary and one microsecond before it.

## 4. Timing-safe comparison — PASS

`hmac.compare_digest` is used for the signature. Everything else compared
(`subject`, `port_id`, `operation`) is non-secret, where variable-time comparison
leaks nothing an attacker does not already hold.

## 5. Authorisation boundaries — PASS

`authorize()` verifies the signature first, then checks subject, port and
operation. A `model_copy` that widens `port_ids` fails verification rather than
succeeding — the check is on the signature, not on trust in the object.
`CapabilityToken` is frozen, so mutation raises.

## 6. Hash-chain construction — PASS

`chain_hash(prev, payload) = SHA256(prev || canonical_json(payload))`.

- The entry hash covers content: different payloads hash differently.
- It covers position: the same payload after a different predecessor differs.
- `prev_hash` is **fixed at 64 hex characters**, so the concatenation is
  unambiguous — a variable-length prefix would allow a boundary-shifting
  collision.
- SHA-256 length extension does not apply: there is no secret prefix, so the
  attack yields nothing an attacker could not compute anyway.

## 7. Canonical serialisation — **FIXED** (was a demonstrable defect)

**The defect.** `canonical_json` used `json.dumps(..., default=str)`. Any value
JSON cannot represent fell through to `str()`. For a `set` or `frozenset`, that
emits Python's `repr`, **whose element order depends on the process hash seed.**

The same logical payload therefore hashed differently in different processes:

```
PYTHONHASHSEED=0      -> b2b00c3e32006738df969441...
PYTHONHASHSEED=1      -> 483472e8e5bc842f81f251c8...
PYTHONHASHSEED=12345  -> b17a005d087b71d9f3840026...
```

**Why it mattered.** `canonical_json` underpins both the token signature and the
audit chain. A seed-dependent digest means a signature valid in one process is
invalid in the next, and an audit chain written by one process fails verification
in another. For a system whose audit log is meant to be exportable evidence, that
is a correctness failure in a security primitive.

**Why it was not yet exploitable.** `signing_payload()` sorts its collections
into lists before hashing, so no token ever reached the defective path. The
exposure was latent — `digest()` and `chain_hash()` accept arbitrary payloads,
and the first caller to pass a set would have hit it.

**The fix.** A `_canonical_default` that sorts sets into JSON arrays, falling
back to `str()` for everything else:

```
PYTHONHASHSEED=0/1/12345 -> 21d208cdbc4cf741da84bd70...   (identical)
canonical_json({"s": {"b","a"}})  ->  {"s":["a","b"]}
```

Fixed in `hashing.py`. Three regression tests guard it, including one that
re-runs the digest in subprocesses under three different hash seeds. All 235
pre-existing governance tests still pass, so the fix changed no intended
behaviour.

**Also verified as correct:** key ordering does not affect the digest; `1` and
`"1"` are distinguished; `None` and `"None"` are distinguished; nesting is not
flattened; `Decimal("1.0")` and `Decimal("1.00")` sign differently (they are
different grants); Unicode is stable.

## 8. Nonce / replay protection — **NEEDS_REVIEW**

**There is none.** No nonce, no `jti` registry, no used-token state. Verification
is a pure function of (payload, secret, clock).

Demonstrated: the same token verifies **100 times in a row** without refusal.

A token captured from the database, a log file, or an audit export can be
replayed until it expires. The only mitigation is the one-hour default TTL,
which bounds the window but does not close it.

**Assessment.** For a single-operator, single-process, local-first system this
may be an acceptable design choice — there is no network attacker and no
multi-tenant boundary. It is **not** acceptable once tokens cross a process
boundary, are persisted, or appear in an exported audit record, all of which the
architecture intends.

**Before activation, decide:** add a used-token registry (a table and a unique
constraint — the same pattern the budget store already uses for `request_id`), or
document explicitly that tokens are bearer credentials whose exposure equals
their authority.

## 9. Token revocation — **NEEDS_REVIEW**

`TokenIssuer` has no `revoke` and no `is_revoked`. A token known to be leaked
cannot be withdrawn; the only remedy is rotating the signing secret, which
invalidates **every** outstanding token at once.

Not a defect in a system with no live tokens. It is a gap that must be closed
before an agent holds a token that matters, and it is the same table that would
solve finding 8.

## 10. Audit chain is unkeyed — **NEEDS_REVIEW**

`chain_hash` uses no secret. Anyone who can write to the audit store can alter an
entry and **recompute every hash after it**, producing a chain that verifies
perfectly.

Demonstrated: a forged three-entry chain is internally consistent and passes a
naive verifier; only comparison against an external witness reveals the change.

**What the chain actually gives you:** detection of corruption, partial writes,
careless edits and deletions. That is genuinely useful and it is what the code
claims — the docstrings say "tamper-evident", not "tamper-proof".

**What it does not give you:** protection against an attacker with write access,
which includes any process running as the same user.

**Before the audit log is treated as evidence**, one of: HMAC the chain with the
same signing secret; periodically publish the head hash somewhere append-only; or
state plainly in the export that the chain proves integrity only against
non-adversarial corruption. **This matters more than the other findings**,
because deployer liability (`AUTONOMY_GAP_ANALYSIS.md`) makes the audit trail the
artefact we would actually rely on.

## 11. Secret redaction coverage — **NEEDS_REVIEW**

`redact_secrets` matches six patterns: `sk-…`, `pk_live/test_…`, `ghp_…`,
`xox[baprs]-…`, `AKIA…`, and PEM private-key headers. All six were verified to
redact correctly.

Verified **not** redacted:

| Shape | Example |
|---|---|
| JWT | `eyJhbGciOiJIUzI1NiJ9.…` |
| Google API key | `AIzaSy…` |
| DigitalOcean token | `dop_v1_…` |
| Password in a DSN | `postgres://user:hunter2@host/db` |
| Bare hex or base64 blob | 64 hex characters |

The function's own docstring says "a guardrail, not a scanner", so this is a
documented limit rather than a broken promise. It is recorded because audit
records are the artefact most likely to be exported, and anything not on the list
travels with them. The DSN case is the one most likely to occur in practice.

---

## What was fixed, and what was deliberately not

**Fixed:** finding 7 only — a demonstrable defect in a primitive that the new
budget store now depends on. One function, three regression tests, no behaviour
change to anything that previously worked.

**Not fixed, deliberately:** findings 8–11 are design decisions, not bugs.
Changing them means adding a token registry, re-keying the audit chain, or
expanding redaction — all of which would extend frozen components that Part 6 of
the current instruction places out of bounds. They are recorded here so the
decision is yours and is made before, not after, activation.

## Activation checklist

Before any frozen component is wired in:

- [ ] Decide on replay protection (finding 8) — registry, or documented acceptance
- [ ] Decide on revocation (finding 9) — same mechanism as 8
- [ ] **Decide how the audit chain is anchored (finding 10)** — the highest-value item
- [ ] Extend redaction, or accept its limits in writing (finding 11)
- [ ] Rename or sentinel the empty-`operations`-means-any footgun (§2)
- [ ] Confirm the signing secret comes from the environment and is ≥32 bytes

## Reproducing this review

```bash
PYTHONPATH=src python -m pytest tests/security/test_crypto_adversarial.py -v
```

62 tests. Those named `test_DEFECT_*` assert defective behaviour deliberately, so
that a future fix makes them fail and forces the finding to be revisited.
