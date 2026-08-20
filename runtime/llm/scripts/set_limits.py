"""Apply the spending policy to the budget store.

The limits are data, versioned here so a change is a reviewable diff rather
than a command someone once ran. The store lives in `data/`, which is
gitignored and does not survive a fresh machine — re-run this after cloning.

The company ceiling sits **below** the Anthropic workspace limit on purpose.
Our guard is meant to stop spending first; the provider limit is the backstop
that still holds if our guard is wrong. If the provider limit ever trips, that
is itself the alarm that the guard failed.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from happy.governance.budget_store import BudgetStore

PROVIDER_MONTHLY_LIMIT = "20.00"
"""The Anthropic workspace limit, for reference. Not enforced by us."""

POLICY: dict[str, str] = {
    # scope      : limit in USD
    "company": "15.00",   # 25% under the provider limit, so we trip first
    "monthly": "15.00",   # same ceiling, expressed per calendar month
    "daily": "1.00",      # one bad day cannot consume the month
    "agent": "5.00",      # a single agent cannot consume the day
    "task": "2.00",       # a single task cannot consume an agent
    "request": "0.50",    # a single call cannot consume a task
}


def keys_for(now: datetime, agent: str, task: str) -> dict[str, str]:
    return {
        "company": "global",
        "monthly": now.strftime("%Y-%m"),
        "daily": now.date().isoformat(),
        "agent": agent,
        "task": task,
        "request": "per-call",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/budget.db")
    ap.add_argument("--agent", default="discovery_researcher")
    ap.add_argument("--task", default="discovery-001")
    args = ap.parse_args()

    store = BudgetStore(args.db)
    now = datetime.now(UTC)
    keys = keys_for(now, args.agent, args.task)

    print(f"store      : {args.db}")
    print(f"audit chain: {store.chain_mode}")
    if store.chain_mode != "hmac-sha256":
        print("  WARNING: HAPPY_AUDIT_HMAC_SECRET is not set; the audit chain is")
        print("           unkeyed and can be recomputed by anyone with write access.")
    print(f"provider backstop (Anthropic workspace, not ours): ${PROVIDER_MONTHLY_LIMIT}/mo")
    print()
    for scope, limit in POLICY.items():
        store.set_limit(scope, keys[scope], limit)
        remaining = store.remaining(scope, keys[scope])
        print(f"  {scope:8} {keys[scope]:24} limit ${limit:>6}  remaining ${remaining}")

    assert float(POLICY["company"]) < float(PROVIDER_MONTHLY_LIMIT), (
        "the company ceiling must stay below the provider limit"
    )
    print()
    print(f"headroom   : provider ${PROVIDER_MONTHLY_LIMIT} - company ${POLICY['company']} = "
          f"${float(PROVIDER_MONTHLY_LIMIT) - float(POLICY['company']):.2f}")
    store.verify_audit()
    print("audit      : verifies")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
