"""Digests and redaction for the audit chain.

Two properties matter here. **Canonical** — the same logical payload must hash
identically across processes and Python versions, so keys are sorted and
separators are fixed. **Safe to export** — audit records are the artifact most
likely to be shared with an accountant, an auditor or a court, so anything
secret-shaped is redacted before it can be written.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

GENESIS_HASH: str = "0" * 64
"""`prev_hash` of the first entry. A chain that starts elsewhere is truncated."""

REDACTED = "[redacted]"

_SECRET_PATTERN = re.compile(
    r"sk-[A-Za-z0-9_\-]{8,}"
    r"|pk_(?:live|test)_[A-Za-z0-9]{8,}"
    r"|ghp_[A-Za-z0-9]{8,}"
    r"|xox[baprs]-[A-Za-z0-9\-]{8,}"
    r"|AKIA[0-9A-Z]{12,}"
    r"|-----BEGIN[A-Z ]*PRIVATE KEY-----"
)


def redact_secrets(text: str) -> str:
    """Replace anything credential-shaped. A guardrail, not a scanner."""
    return _SECRET_PATTERN.sub(REDACTED, text)


def canonical_json(payload: Any) -> str:
    """Deterministic JSON. `default=str` keeps Decimal and datetime hashable."""
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        ensure_ascii=False,
    )


def digest(payload: Any) -> str:
    """SHA-256 of the canonical form of `payload`."""
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def chain_hash(prev_hash: str, payload: Any) -> str:
    """Hash one audit entry into the chain.

    The previous hash is prefixed rather than mixed into the payload, so an
    entry's own content and its position in the history are both covered.
    """
    material = prev_hash + canonical_json(payload)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
