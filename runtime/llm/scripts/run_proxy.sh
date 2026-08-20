#!/usr/bin/env bash
# Start the LiteLLM proxy. Loads .env if present; never echoes secret values.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"
if [ -f .env ]; then set -a; . ./.env; set +a; fi
: "${ANTHROPIC_API_KEY:?set ANTHROPIC_API_KEY in .env}"
: "${LITELLM_MASTER_KEY:?set LITELLM_MASTER_KEY in .env}"
export ANTHROPIC_API_BASE="${ANTHROPIC_API_BASE:-https://api.anthropic.com}"
exec .venv/bin/litellm --config "${1:-config.yaml}" --port "${2:-4000}" --num_workers 1
