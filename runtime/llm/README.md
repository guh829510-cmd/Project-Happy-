# Step 1 runtime — LiteLLM + Langfuse

Third-party runtime, deliberately kept **outside** `src/happy/`. Nothing here
imports our application code and our application code does not import this.

    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt
    cp .env.example .env          # then fill in .env — never commit it
    ./scripts/run_proxy.sh        # proxy on :4000

Verify without spending money or holding a provider key:

    .venv/bin/python scripts/offline_doubles.py &   # stub provider + trace capture
    ANTHROPIC_API_BASE=http://127.0.0.1:8090 \
    LANGFUSE_HOST=http://127.0.0.1:8091 ./scripts/run_proxy.sh &
    .venv/bin/python scripts/smoke.py

    ./scripts/stop_all.sh

Results and known limitations: `docs/runtime/LLM_SMOKE_TEST.md`.
Read the spend-ceiling finding there before relying on this for cost control.
