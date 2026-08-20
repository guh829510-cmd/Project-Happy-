"""The capability vocabulary.

Every port operation declares exactly which capabilities it exercises. The
governance kernel grants capabilities to an agent through a scoped, expiring
token; an operation whose declared capabilities exceed the token is refused.

`MONEY_MOVE` is defined but is never declared by any port in this system. It
exists so that the prohibition can be expressed positively and asserted by a
test, rather than merely being absent and therefore unverifiable.
"""

from __future__ import annotations

from enum import StrEnum


class Capability(StrEnum):
    """A discrete power an operation may exercise."""

    NETWORK_READ = "network:read"
    NETWORK_WRITE = "network:write"

    FILESYSTEM_READ = "filesystem:read"
    FILESYSTEM_WRITE = "filesystem:write"

    PROCESS_EXECUTE = "process:execute"

    LLM_INFERENCE = "llm:inference"

    SECRET_READ = "secret:read"

    OUTBOUND_MESSAGE = "comms:outbound_message"
    """Sends something to a person who is not the Chairman."""

    EXTERNAL_PUBLISH = "comms:external_publish"
    """Makes content visible outside the system."""

    REPO_READ = "repo:read"
    REPO_WRITE = "repo:write"

    DEPLOY_PREVIEW = "deploy:preview"
    DEPLOY_PRODUCTION = "deploy:production"

    PERSONAL_DATA_READ = "pii:read"
    PERSONAL_DATA_WRITE = "pii:write"

    MONEY_READ = "money:read"
    """Observe balances and transactions. Never moves value."""

    MONEY_MOVE = "money:move"
    """Move value. Never declared by any port. Present so it can be denied."""


FORBIDDEN_CAPABILITIES: frozenset[Capability] = frozenset({Capability.MONEY_MOVE})
"""Capabilities no port may declare and no token may grant."""
