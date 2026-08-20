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
        reply = "Project Happy step one online."
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
    threading.Thread(target=provider.serve_forever, daemon=True).start()
    threading.Thread(target=langfuse.serve_forever, daemon=True).start()
    print("provider stub :8090   langfuse capture :8091", flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
