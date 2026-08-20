"""The guarded path: budget gate in front, LiteLLM behind.

    REQUEST -> estimate -> reserve -> ALLOW/DENY -> LiteLLM -> provider
            -> actual cost -> settle -> audit -> Langfuse

This is the only sanctioned route to the provider. The LiteLLM master key lives
here and nowhere else, so there is no path that reaches the model without first
passing the reservation.

Run the real end-to-end test (Part 3):

    cp .env.example .env      # then put a real ANTHROPIC_API_KEY in .env
    ./scripts/run_proxy.sh &
    .venv/bin/python scripts/guarded_client.py --real

Without --real it runs against the local stub and spends nothing.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

import litellm  # noqa: E402

from happy.governance.budget_store import BudgetStore  # noqa: E402
from happy.governance.errors import BudgetExceeded  # noqa: E402
from happy.governance.spend_gate import Pricing, SpendGate, Unpriceable  # noqa: E402

MODEL = "anthropic/claude-sonnet-5"
PROXY_MODEL = "chat"
MAX_OUTPUT_TOKENS = 64
"""Deliberately small. The test proves plumbing, not capability."""


def load_env(path: Path) -> None:
    """Read .env without printing anything from it."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def pricing_for(model: str) -> Pricing | None:
    """Look up per-token prices locally. None means we cannot bound the cost."""
    try:
        info = litellm.get_model_info(model)
        return Pricing(
            Decimal(str(info["input_cost_per_token"])),
            Decimal(str(info["output_cost_per_token"])),
        )
    except Exception:
        return None


def count_input_tokens(model: str, messages: list[dict]) -> int | None:
    """Measure input tokens locally. None means we cannot bound the cost."""
    try:
        return int(litellm.token_counter(model=model, messages=messages))
    except Exception:
        return None


def call_proxy(base: str, key: str, messages: list[dict]) -> dict:
    body = {
        "model": PROXY_MODEL,
        "messages": messages,
        "max_tokens": MAX_OUTPUT_TOKENS,
    }
    req = urllib.request.Request(
        f"{base}/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read())
        payload["_response_cost_header"] = resp.headers.get("x-litellm-response-cost")
        return payload


def cost_of(response: dict) -> str | None:
    """Prefer LiteLLM's computed cost; fall back to recomputing from usage."""
    header = response.get("_response_cost_header")
    if header not in (None, ""):
        return header
    usage = response.get("usage") or {}
    p_in, p_out = litellm.cost_per_token(
        model=MODEL,
        prompt_tokens=int(usage.get("prompt_tokens", 0)),
        completion_tokens=int(usage.get("completion_tokens", 0)),
    )
    return str(Decimal(str(p_in)) + Decimal(str(p_out)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--real", action="store_true", help="use the real provider")
    ap.add_argument("--db", default=str(REPO / "data" / "budget.db"))
    ap.add_argument("--base", default="http://127.0.0.1:4000")
    ap.add_argument("--company-limit", default="1.00")
    ap.add_argument(
        "--set-limits",
        action="store_true",
        help="create missing limits on a fresh store; never raises an existing one",
    )
    args = ap.parse_args()

    here = Path(__file__).resolve().parent.parent
    load_env(here / ".env")
    key = os.environ.get("LITELLM_MASTER_KEY")
    if not key:
        print("LITELLM_MASTER_KEY is not set (put it in runtime/llm/.env)")
        return 2
    if args.real and not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set; cannot run the real provider test")
        return 2

    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    store = BudgetStore(args.db)
    today = datetime.now(UTC)
    scopes = {
        "request": "smoke",
        "agent": "step1_probe",
        "task": "step1_real_provider_test",
        "daily": today.date().isoformat(),
        "monthly": today.strftime("%Y-%m"),
        "company": "global",
    }
    # A caller must not be able to widen its own ceiling. Limits are policy,
    # set by scripts/set_limits.py; this client only consumes them. --set-limits
    # is for a fresh store, and it still refuses to raise an existing limit.
    for scope, key_name in scopes.items():
        current = store.remaining(scope, key_name)
        if current is None:
            if not args.set_limits:
                print(
                    f"no limit declared for {scope}:{key_name}. "
                    "Run scripts/set_limits.py first, or pass --set-limits."
                )
                return 2
            store.set_limit(scope, key_name, args.company_limit)

    gate = SpendGate(store, now=lambda: datetime.now(UTC))
    messages = [{"role": "user", "content": "Reply with exactly: ok"}]

    input_tokens = count_input_tokens(MODEL, messages)
    pricing = pricing_for(MODEL)
    request_id = f"req_{uuid4().hex[:12]}"

    print(f"model              : {MODEL}")
    print(f"input tokens       : {input_tokens}")
    print(f"max output tokens  : {MAX_OUTPUT_TOKENS}")
    print(f"provider           : {'REAL Anthropic' if args.real else 'local stub'}")

    try:
        outcome = gate.call(
            request_id=request_id,
            scopes=scopes,
            input_tokens=input_tokens,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            pricing=pricing,
            invoke=lambda: call_proxy(args.base, key, messages),
            cost_of=cost_of,
        )
    except Unpriceable as exc:
        print(f"DENIED (unpriceable): {exc}")
        return 1
    except BudgetExceeded as exc:
        print(f"DENIED (budget): {exc}")
        return 1
    except urllib.error.HTTPError as exc:
        print(f"call failed HTTP {exc.code}; reservation released")
        print(f"open reservations  : {store.open_reservations()}")
        return 1

    reply = outcome.response["choices"][0]["message"]["content"]
    print(f"reply              : {reply!r}")
    print(f"authorised (bound) : ${outcome.authorised_usd}")
    print(f"actual cost        : ${outcome.actual_usd}")
    print(f"company committed  : ${store.committed('company', 'global')}")
    print(f"company remaining  : ${store.remaining('company', 'global')}")
    print(f"open reservations  : {store.open_reservations()}")
    store.verify_audit()
    print(f"audit entries      : {len(store.audit_entries())} (chain verifies)")
    for entry in store.audit_entries()[-2:]:
        print(f"  seq={entry['seq']} {entry['event']:16} {entry['detail'][:52]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
