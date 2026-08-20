"""Local test doubles so Step 1 can be verified without spending money.

Two servers, both stdlib-only:

  * an Anthropic Messages API stub on :8090 — LiteLLM's real `anthropic`
    provider code path calls it, so everything except the vendor itself is
    exercised for real;
  * a Langfuse ingestion capture on :8091 — accepts what LiteLLM's Langfuse
    callback actually emits and writes it to disk so the trace can be read.

This is a verification aid, not part of the system. Production points
LiteLLM at the real provider and the real Langfuse by changing two env vars.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

CAPTURE = Path(__file__).parent / "captured_traces.jsonl"


def _words(messages: list[dict]) -> int:
    total = 0
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            total += len(c.split())
        elif isinstance(c, list):
            total += sum(len(str(p.get("text", "")).split()) for p in c)
    return total


class AnthropicStub(BaseHTTPRequestHandler):
    """Minimal Anthropic Messages API. Returns real token counts."""

    def log_message(self, *a):  # silence
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or "{}")

        # A request carrying the marker makes the upstream fail, so failure
        # handling can be tested deterministically.
        text = json.dumps(body.get("messages", []))
        if "FORCE_SLOW" in text:
            import time as _t

            _t.sleep(6)

        if "FORCE_UPSTREAM_FAILURE" in text:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "type": "error",
                        "error": {"type": "api_error", "message": "stub: forced failure"},
                    }
                ).encode()
            )
            return

        in_tok = max(1, _words(body.get("messages", [])) * 2)
        reply = _stub_reply(text)
        out_tok = max(1, len(reply.split()) * 2)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(
            json.dumps(
                {
                    "id": "msg_stub_0001",
                    "type": "message",
                    "role": "assistant",
                    "model": body.get("model", "claude-sonnet-5"),
                    "content": [{"type": "text", "text": reply}],
                    "stop_reason": "end_turn",
                    "stop_sequence": None,
                    "usage": {"input_tokens": in_tok, "output_tokens": out_tok},
                }
            ).encode()
        )


SUBQUERIES = json.dumps(
    [
        "freelancers chasing late invoices complaints",
        "small agency invoice reminder tools pricing",
        "late payment b2b freelancers statistics",
        "invoice chasing automation competitors",
    ]
)

OPPORTUNITIES = json.dumps(
    {
        "verdict": "opportunities_found",
        "reasoning": "Stub response used for offline pipeline verification only.",
        "opportunities": [
            {
                "name": "Invoice chase automation for solo freelancers",
                "customer_problem": "Hours lost each month chasing unpaid invoices.",
                "target_customer": "Solo freelancers billing 5-20 clients monthly.",
                "existing_solutions": ["Manual email", "Full accounting suites"],
                "gap": "Accounting suites are too heavy; manual chasing does not scale.",
                "why_demand": "Reported 4-6 hours per month spent chasing.",
                "evidence_for": ["E1"],
                "evidence_against": ["Incumbent invoicing tools ship reminders already."],
                "difficulty": "medium",
                "initial_monthly_cost_usd": 25,
                "first_customers_via": "Freelancer communities and niche newsletters.",
                "score": 0.62,
            }
        ],
    }
)

FIXTURE_PAGES = {
    "/late-payments": (
        "Late payments are the top freelancer complaint",
        "Independent contractors report spending four to six hours a month chasing "
        "unpaid invoices. Respondents said reminders are the single most requested "
        "feature. Several said existing accounting suites are far too heavy for a "
        "one-person business and that they abandoned them within a month.",
    ),
    "/competitors": (
        "Existing invoice reminder tools",
        "Incumbent invoicing products already include automated reminders as part of "
        "a broader accounting suite. Standalone reminder tools exist but are priced "
        "per seat and target agencies rather than solo operators.",
    ),
    "/pricing": (
        "What freelancers pay for admin tools",
        "Survey respondents reported paying between five and fifteen dollars a month "
        "for administrative tooling, and resisting anything above twenty.",
    ),
}


NO_OPPORTUNITIES = json.dumps(
    {
        "verdict": "no_good_opportunities",
        "reasoning": "The evidence describes a crowded category with incumbent "
        "products already shipping the feature and a price ceiling below "
        "sustainable unit economics. Stub response for offline verification.",
        "opportunities": [],
    }
)


def _stub_reply(prompt_text: str) -> str:
    """Return something shaped like what each prompt asks for.

    `HAPPY_STUB_VERDICT=none` makes the analysis step return the negative
    verdict, so the "no good opportunities" path can be exercised offline.
    """
    lowered = prompt_text.lower()
    if "search queries" in lowered or "sub-queries" in lowered:
        return SUBQUERIES
    if "venture analyst" in lowered:
        if os.environ.get("HAPPY_STUB_VERDICT") == "none":
            return NO_OPPORTUNITIES
        return OPPORTUNITIES
    return "Project Happy step one online."


class FixtureSite(BaseHTTPRequestHandler):
    """Static pages so Crawlee extraction can be exercised without egress."""

    def log_message(self, *a):
        pass

    def do_GET(self):
        title, body = FIXTURE_PAGES.get(
            self.path, ("Not found", "no such fixture page")
        )
        html = (
            f"<!doctype html><html><head><title>{title}</title></head>"
            f"<body><h1>{title}</h1><p>{body}</p></body></html>"
        ).encode()
        self.send_response(200 if self.path in FIXTURE_PAGES else 404)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(html)


class LangfuseCapture(BaseHTTPRequestHandler):
    """Accepts Langfuse ingestion batches and records them."""

    def log_message(self, *a):
        pass

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError:
            payload = {"unparsed": raw.decode(errors="replace")[:2000]}
        with CAPTURE.open("a") as fh:
            fh.write(json.dumps({"path": self.path, "payload": payload}) + "\n")
        self.send_response(207)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"successes":[],"errors":[]}')

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")


def main() -> None:
    CAPTURE.unlink(missing_ok=True)
    provider = HTTPServer(("127.0.0.1", 8090), AnthropicStub)
    langfuse = HTTPServer(("127.0.0.1", 8091), LangfuseCapture)
    fixtures = HTTPServer(("127.0.0.1", 8099), FixtureSite)
    for server in (provider, langfuse, fixtures):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    print(
        "provider stub :8090   langfuse capture :8091   fixture site :8099",
        flush=True,
    )
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
