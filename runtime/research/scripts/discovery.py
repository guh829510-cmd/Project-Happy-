"""Discovery pipeline: objective -> evidence -> opportunities.

    OBJECTIVE -> sub-queries (LLM) -> search -> crawl -> EVIDENCE
              -> report (LLM) -> OPPORTUNITY CANDIDATES (LLM, ranked)

Uses the systems we already chose, and nothing new:

* **search**  — ddgs (what GPT Researcher itself uses) or a SearXNG instance
* **crawl**   — Crawlee, Apache-2.0, the same BeautifulSoupCrawler proven in
                `docs/runtime/DISCOVERY_RUN.md`
* **LLM**     — the existing LiteLLM proxy behind the existing `SpendGate`.
                There is no second LLM abstraction here: every call goes through
                `_llm()`, which is a thin wrapper over the gate.

Every LLM call reserves its worst-case cost before the provider is contacted and
settles the actual cost afterwards. A budget refusal aborts the run rather than
degrading it.

The pipeline is allowed to conclude that there are no good opportunities. The
prompt says so explicitly, and `--min-opportunities 0` is the default.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "runtime" / "llm" / "scripts"))

from guarded_client import (  # noqa: E402
    MODEL,
    call_proxy,
    cost_of,
    count_input_tokens,
    load_env,
    pricing_for,
)

from happy.governance.budget_store import BudgetStore  # noqa: E402
from happy.governance.errors import BudgetExceeded  # noqa: E402
from happy.governance.spend_gate import SpendGate, Unpriceable  # noqa: E402

MAX_OUTPUT_TOKENS = 2000


# ---------------------------------------------------------------- search ---


@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    snippet: str
    query: str


class SearchBackend(Protocol):
    name: str

    def search(self, query: str, max_results: int) -> list[SearchHit]: ...


class DdgsBackend:
    """DuckDuckGo via `ddgs` — the backend GPT Researcher defaults to."""

    name = "ddgs"

    def search(self, query: str, max_results: int) -> list[SearchHit]:
        from ddgs import DDGS

        rows = list(DDGS().text(query, max_results=max_results))
        return [
            SearchHit(r.get("title", ""), r.get("href", ""), r.get("body", ""), query)
            for r in rows
            if r.get("href")
        ]


class SearxngBackend:
    """A self-hosted SearXNG instance over its JSON API."""

    name = "searxng"

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def search(self, query: str, max_results: int) -> list[SearchHit]:
        import urllib.parse
        import urllib.request

        url = f"{self.base_url}/search?" + urllib.parse.urlencode(
            {"q": query, "format": "json"}
        )
        with urllib.request.urlopen(url, timeout=30) as resp:
            payload = json.loads(resp.read())
        return [
            SearchHit(r.get("title", ""), r.get("url", ""), r.get("content", ""), query)
            for r in payload.get("results", [])[:max_results]
            if r.get("url")
        ]


class FixtureBackend:
    """Reads hits from a JSON file. For proving the pipeline without egress."""

    name = "fixture"

    def __init__(self, path: Path) -> None:
        self._rows = json.loads(Path(path).read_text())

    def search(self, query: str, max_results: int) -> list[SearchHit]:
        return [
            SearchHit(r["title"], r["url"], r.get("snippet", ""), query)
            for r in self._rows
        ][:max_results]


# ----------------------------------------------------------------- crawl ---


@dataclass
class Evidence:
    url: str
    title: str
    text: str
    chars: int
    query: str
    retrieved_at: str


async def crawl(
    urls: list[str], hits: dict[str, SearchHit], max_pages: int
) -> tuple[list[Evidence], list[str]]:
    """Extract text from each URL with Crawlee. Returns (evidence, failures)."""
    from crawlee.crawlers import BeautifulSoupCrawler, BeautifulSoupCrawlingContext

    found: list[Evidence] = []
    failed: list[str] = []
    crawler = BeautifulSoupCrawler(max_requests_per_crawl=max_pages, max_request_retries=1)

    @crawler.router.default_handler
    async def handler(ctx: BeautifulSoupCrawlingContext) -> None:
        text = " ".join(ctx.soup.get_text(" ").split())
        hit = hits.get(ctx.request.url)
        found.append(
            Evidence(
                url=ctx.request.url,
                title=(ctx.soup.title.string if ctx.soup.title else "") or "",
                text=text[:6000],
                chars=len(text),
                query=hit.query if hit else "",
                retrieved_at=datetime.now(UTC).isoformat(),
            )
        )

    @crawler.failed_request_handler
    async def on_fail(ctx: Any, error: Exception) -> None:
        failed.append(f"{ctx.request.url}: {type(error).__name__}")

    await crawler.run(urls[:max_pages])
    return found, failed


# ------------------------------------------------------------------- LLM ---


@dataclass
class Metrics:
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal("0")
    authorised_usd: Decimal = Decimal("0")
    search_calls: int = 0
    search_hits: int = 0
    pages_crawled: int = 0
    pages_failed: int = 0
    failures: list[str] = field(default_factory=list)
    retries: int = 0


class Runner:
    """Holds the gate and the proxy details. Not an LLM abstraction — a caller."""

    def __init__(
        self, store: BudgetStore, base: str, key: str, scopes: dict[str, str]
    ) -> None:
        self.store = store
        self.base = base
        self.key = key
        self.scopes = scopes
        self.gate = SpendGate(store, now=lambda: datetime.now(UTC))
        self.metrics = Metrics()

    def llm(self, prompt: str, *, purpose: str) -> str:
        """One guarded LLM call. Raises on budget refusal — the run stops."""
        messages = [{"role": "user", "content": prompt}]
        outcome = self.gate.call(
            request_id=f"disc_{purpose}_{uuid4().hex[:8]}",
            scopes=self.scopes,
            input_tokens=count_input_tokens(MODEL, messages),
            max_output_tokens=MAX_OUTPUT_TOKENS,
            pricing=pricing_for(MODEL),
            invoke=lambda: call_proxy(self.base, self.key, messages),
            cost_of=cost_of,
        )
        usage = outcome.response.get("usage") or {}
        self.metrics.llm_calls += 1
        self.metrics.input_tokens += int(usage.get("prompt_tokens", 0))
        self.metrics.output_tokens += int(usage.get("completion_tokens", 0))
        self.metrics.cost_usd += outcome.actual_usd
        self.metrics.authorised_usd += outcome.authorised_usd
        return outcome.response["choices"][0]["message"]["content"]


# ------------------------------------------------------------- pipeline ---

SUBQUERY_PROMPT = """You are planning web research for this objective:

{objective}

Write {n} distinct search queries that would surface real evidence: customer
complaints, competitor products, pricing pages, market discussion.
Return ONLY a JSON array of strings. No prose."""

OPPORTUNITY_PROMPT = """You are a venture analyst. Below is evidence gathered from the web
for this objective:

{objective}

EVIDENCE (each item has an id you must cite):
{evidence}

Produce a JSON object with this exact shape:

{{
  "verdict": "opportunities_found" | "no_good_opportunities",
  "reasoning": "why, in 2-4 sentences",
  "opportunities": [
    {{
      "name": "...",
      "customer_problem": "...",
      "target_customer": "...",
      "existing_solutions": ["..."],
      "gap": "...",
      "why_demand": "...",
      "evidence_for": ["E1", "E2"],
      "evidence_against": ["..."],
      "difficulty": "low|medium|high",
      "initial_monthly_cost_usd": 0,
      "first_customers_via": "...",
      "score": 0.0
    }}
  ]
}}

Rules you must follow:
- Cite evidence ids in "evidence_for". An opportunity with no evidence id is invalid.
- "evidence_against" must be genuine counter-evidence or a real risk, never empty filler.
- You ARE allowed and expected to return "no_good_opportunities" with an empty
  list if the evidence does not support any. Do not invent a startup.
- Rank by "score" descending. Be sceptical; most ideas are bad.
Return ONLY the JSON object."""


def parse_json(text: str) -> Any:
    """LLM output is untrusted text. Extract the JSON, or fail loudly."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        cleaned = cleaned[4:] if cleaned.startswith("json") else cleaned
    start = min((i for i in (cleaned.find("{"), cleaned.find("[")) if i >= 0), default=-1)
    if start < 0:
        raise ValueError("no JSON found in model output")
    end = max(cleaned.rfind("}"), cleaned.rfind("]"))
    return json.loads(cleaned[start : end + 1])


async def run(args: argparse.Namespace) -> int:
    started = time.time()
    load_env(REPO / "runtime" / "llm" / ".env")
    import os

    key = os.environ.get("LITELLM_MASTER_KEY")
    if not key:
        print("LITELLM_MASTER_KEY not set (runtime/llm/.env)")
        return 2

    store = BudgetStore(args.db)
    today = datetime.now(UTC)
    scopes = {
        "request": "discovery",
        "agent": "discovery_researcher",
        "task": args.task_id,
        "daily": today.date().isoformat(),
        "monthly": today.strftime("%Y-%m"),
        "company": "global",
    }
    # Limits are policy (runtime/llm/scripts/set_limits.py). A run consumes them
    # and must not be able to widen its own ceiling; --set-limits only fills in
    # scopes that do not exist yet, on a fresh store.
    for scope, name in scopes.items():
        if store.remaining(scope, name) is None:
            if not args.set_limits:
                print(
                    f"no limit declared for {scope}:{name}. "
                    "Run runtime/llm/scripts/set_limits.py first, or pass --set-limits."
                )
                return 2
            store.set_limit(scope, name, args.budget)

    if args.backend == "fixture":
        backend: SearchBackend = FixtureBackend(Path(args.fixture))
    elif args.backend == "searxng":
        backend = SearxngBackend(args.searxng_url)
    else:
        backend = DdgsBackend()

    runner = Runner(store, args.base, key, scopes)
    m = runner.metrics
    print(f"objective : {args.objective}")
    print(f"search    : {backend.name}   budget: ${args.budget}   db: {args.db}")

    try:
        raw = runner.llm(
            SUBQUERY_PROMPT.format(objective=args.objective, n=args.queries),
            purpose="subqueries",
        )
        queries = [str(q) for q in parse_json(raw)][: args.queries]
    except (BudgetExceeded, Unpriceable) as exc:
        print(f"ABORTED before search: {exc}")
        return 1
    print(f"sub-queries: {queries}")

    hits: dict[str, SearchHit] = {}
    for q in queries:
        try:
            for hit in backend.search(q, args.results_per_query):
                m.search_hits += 1
                hits.setdefault(hit.url, hit)
        except Exception as exc:
            m.failures.append(f"search({q!r}): {type(exc).__name__}: {exc}")
        m.search_calls += 1
    print(f"search    : {m.search_calls} calls, {len(hits)} unique urls")
    if not hits:
        print("no search results — cannot gather evidence")
        print(json.dumps({"metrics": _metrics_dict(m, started)}, indent=2))
        return 1

    evidence, failed = await crawl(list(hits), hits, args.max_pages)
    m.pages_crawled = len(evidence)
    m.pages_failed = len(failed)
    m.failures.extend(failed)
    print(f"crawl     : {m.pages_crawled} extracted, {m.pages_failed} failed")
    if not evidence:
        print("no pages extracted — cannot produce evidence-backed opportunities")
        print(json.dumps({"metrics": _metrics_dict(m, started)}, indent=2))
        return 1

    blocks = []
    for i, ev in enumerate(evidence, 1):
        blocks.append(f"[E{i}] {ev.title} <{ev.url}>\n{ev.text[:1500]}")
    try:
        raw = runner.llm(
            OPPORTUNITY_PROMPT.format(
                objective=args.objective, evidence="\n\n".join(blocks)
            ),
            purpose="opportunities",
        )
        result = parse_json(raw)
    except (BudgetExceeded, Unpriceable) as exc:
        print(f"ABORTED before analysis: {exc}")
        return 1

    out = {
        "objective": args.objective,
        "verdict": result.get("verdict"),
        "reasoning": result.get("reasoning"),
        "opportunities": result.get("opportunities", []),
        "evidence": [
            {"id": f"E{i}", **asdict(ev)} for i, ev in enumerate(evidence, 1)
        ],
        "metrics": _metrics_dict(m, started),
        "audit": {
            "chain_mode": store.chain_mode,
            "entries": len(store.audit_entries()),
        },
    }
    store.verify_audit()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2, default=str))
    print(f"verdict   : {out['verdict']}  ({len(out['opportunities'])} opportunities)")
    print(f"cost      : ${m.cost_usd} actual / ${m.authorised_usd} authorised")
    print(f"written   : {args.out}")
    return 0


def _metrics_dict(m: Metrics, started: float) -> dict[str, Any]:
    return {
        "llm_calls": m.llm_calls,
        "input_tokens": m.input_tokens,
        "output_tokens": m.output_tokens,
        "actual_cost_usd": str(m.cost_usd),
        "authorised_cost_usd": str(m.authorised_usd),
        "search_calls": m.search_calls,
        "search_hits": m.search_hits,
        "pages_crawled": m.pages_crawled,
        "pages_failed": m.pages_failed,
        "retries": m.retries,
        "failures": m.failures,
        "duration_seconds": round(time.time() - started, 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--objective", required=True)
    ap.add_argument("--backend", choices=["ddgs", "searxng", "fixture"], default="ddgs")
    ap.add_argument("--fixture", default=str(HERE / "fixtures" / "search_results.json"))
    ap.add_argument("--searxng-url", default="http://127.0.0.1:8888")
    ap.add_argument("--queries", type=int, default=4)
    ap.add_argument("--results-per-query", type=int, default=5)
    ap.add_argument("--max-pages", type=int, default=8)
    ap.add_argument("--budget", default="1.00")
    ap.add_argument(
        "--set-limits",
        action="store_true",
        help="create missing limits on a fresh store; never raises an existing one",
    )
    ap.add_argument("--db", default=str(REPO / "data" / "budget.db"))
    ap.add_argument("--base", default="http://127.0.0.1:4000")
    ap.add_argument("--task-id", default="discovery-001")
    ap.add_argument("--out", default=str(REPO / "data" / "discovery_report.json"))
    return asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
