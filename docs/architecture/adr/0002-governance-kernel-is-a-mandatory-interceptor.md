# ADR-0002 — The governance kernel is a mandatory interceptor

**Status:** Accepted — load-bearing
**Date:** 2026-08-20
**Implements:** `ARCHITECTURE_V2.md` §5, `DEVELOPMENT_PLAN.md` §8, milestone M1

## Context

The system delegates work to LLM-driven departments. Those departments must
reach the outside world — models, feeds, repositories, mail — and every one of
those reaches is an opportunity for the system to do something the Chairman did
not intend, whether through a prompt injected into a scraped page, a chain of
individually-reasonable steps ending somewhere unreasonable, or an ordinary bug.

The obvious design is to give each department its adapters and to check risky
calls before making them. It fails for a boring reason: the check is optional in
practice. Any new code path, any refactor, any adapter added in a hurry can omit
it, and nothing fails loudly when it does. Safety that depends on every future
caller remembering is not safety.

The second obvious design is to instruct the model not to do dangerous things.
That is enforcement layer 5 in §5.1, listed last, and defeated by anyone who can
get text into the model's context.

## Decision

**A department is never handed a raw adapter.** Every capability a department
holds is a `GovernedPort` wrapping an adapter, constructed only in the
composition root. The proxy resolves a call by:

1. refusing outright if the operation is one the port declares prohibited, or is
   not declared at all;
2. building an `ActionRequest` from the port's own static declaration, carrying
   a digest of the arguments rather than the arguments;
3. asking the policy engine, which applies — in this order — the kill switch,
   the T4 deny list, deterministic risk classification, the capability token,
   the approval gateway, and the budget guard;
4. executing only on an allow, then settling the reservation with what the call
   actually cost and recording the outcome in the hash-chained audit log.

Three properties follow, and each is asserted by a test rather than documented
and hoped for:

- **T4 has no approval path.** `ApprovalGateway.submit` raises rather than
  filing a prohibited action, so no interface can render one with an Approve
  button. The refusal is `ProhibitedAction`, which is deliberately not a
  `PortError` and so is not swallowed by generic adapter error handling.
- **Authority is never ambient.** A token names the ports, operations,
  capabilities, tier, venture, budget and expiry it grants, and is HMAC-signed
  so scope edited in storage fails verification. Nothing widens a token at
  runtime.
- **Refusals are recorded.** A denied or prohibited attempt writes an audit
  entry exactly as an executed one does, because the attempts are the part worth
  reviewing.

## Consequences

**What this buys.** Adding a capability means writing a port and an adapter; it
does not mean remembering to add a check, and forgetting is not possible in the
direction that matters — an ungoverned adapter simply is not reachable from a
department. Classification is deterministic and one-way: a model may raise a
tier through an advisory and can never lower one.

**What it costs.** Every call carries a policy decision and an audit write. The
proxy resolves operations dynamically, so a mistyped operation name is caught at
call time rather than by a type checker — mitigated by the descriptor being the
single source of truth and by contract tests over the registry.

**What it does not do.** It is not a sandbox. Python has no private attributes,
and code running in this process could import an adapter and call it directly.
The guarantee is over the object graph — departments receive proxies — which is
why the composition root is the only place an adapter may be constructed, and
why that rule is enforced by review and by ADR rather than by the runtime.

**Where it fails closed.** If governance cannot decide — the kill switch is
engaged, a token cannot be verified, an approval cannot be resolved — the action
does not happen. There is no degraded mode in which work proceeds unchecked.

## Alternatives considered

**Decorators on adapter methods.** Rejected: opt-in per method, and an adapter
that forgets the decorator is silently ungoverned.

**Checks inside each adapter.** Rejected: puts enforcement in the layer with the
most churn and the least review, and duplicates the rules once per vendor.

**A separate out-of-process policy service.** Rejected for now: real isolation,
but it buys little against an in-process caller that could bypass the network
call anyway, and it contradicts the local-first, low-spec constraint. Worth
revisiting if untrusted third-party adapters are ever loaded.
