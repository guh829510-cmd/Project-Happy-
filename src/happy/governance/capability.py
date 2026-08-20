"""Capability tokens — scoped, expiring, unforgeable authority.

Enforcement layer 3 (`ARCHITECTURE_V2.md` §5.1). There is no ambient authority
anywhere in the system: an agent holds a token naming the ports it may call,
the capabilities it may exercise, the tier it may reach, the budget it may
spend and the instant it stops being valid. Nothing widens a token at runtime,
which is what makes prompt injection an annoyance rather than a breach — text
in a scraped page can ask for anything and still cannot enlarge the grant.

The token is signed with HMAC-SHA256 over its canonical payload. The signature
matters even in a single-process, local-first system: the token round-trips
through the database and the audit log, and a token whose scope could be edited
in either place would document authority rather than confine it.
"""

from __future__ import annotations

import hmac
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from happy.core.capability import FORBIDDEN_CAPABILITIES, Capability
from happy.core.protocols import Clock, IdFactory
from happy.core.risk import RiskTier
from happy.governance.action import ActionRequest
from happy.governance.errors import CapabilityDenied, TokenInvalid
from happy.governance.hashing import canonical_json

MIN_SECRET_BYTES = 32
"""Anything shorter is not a signing key, whatever it is called."""

DEFAULT_TOKEN_TTL = timedelta(hours=1)
"""Tokens are cheap to reissue. Long-lived authority is the thing to avoid."""


class CapabilityToken(BaseModel):
    """A grant of scoped authority to one agent, for a bounded time."""

    model_config = ConfigDict(frozen=True)

    token_id: str
    subject: str
    """The agent this was issued to. Must equal `ActionRequest.actor`."""
    capabilities: frozenset[Capability]
    port_ids: frozenset[str]
    operations: frozenset[str] = frozenset()
    """Allowed operation names. Empty means any declared op on an allowed port."""
    max_tier: RiskTier = RiskTier.T1
    budget_usd: Decimal = Field(default=Decimal("0"), ge=0)
    """Total spend this token may authorise, enforced by the budget guard."""
    venture_id: str | None = None
    issued_at: datetime
    expires_at: datetime
    signature: str = ""

    def signing_payload(self) -> dict[str, Any]:
        """Everything that is signed. Excludes the signature itself."""
        return {
            "token_id": self.token_id,
            "subject": self.subject,
            "capabilities": sorted(c.value for c in self.capabilities),
            "port_ids": sorted(self.port_ids),
            "operations": sorted(self.operations),
            "max_tier": int(self.max_tier),
            "budget_usd": str(self.budget_usd),
            "venture_id": self.venture_id,
            "issued_at": self.issued_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
        }

    def is_expired(self, now: datetime) -> bool:
        return now >= self.expires_at

    def permits_port(self, port_id: str) -> bool:
        return port_id in self.port_ids

    def permits_operation(self, operation: str) -> bool:
        return not self.operations or operation in self.operations


class TokenIssuer:
    """Mints and verifies capability tokens.

    Deliberately not a port: capability issuance is a kernel function and must
    never be reachable through an adapter. `issue_token` and `grant_capability`
    are also on the T4 deny list, so an agent that finds a way to call this
    class by name is refused before it arrives.
    """

    def __init__(
        self,
        secret: bytes,
        clock: Clock,
        *,
        id_factory: IdFactory | None = None,
    ) -> None:
        if len(secret) < MIN_SECRET_BYTES:
            raise ValueError(
                f"signing secret must be at least {MIN_SECRET_BYTES} bytes, got {len(secret)}"
            )
        self._secret = secret
        self._clock = clock
        self._id_factory: IdFactory = id_factory or _uuid_id

    def sign(self, token: CapabilityToken) -> str:
        material = canonical_json(token.signing_payload()).encode("utf-8")
        return hmac.new(self._secret, material, "sha256").hexdigest()

    def issue(
        self,
        *,
        subject: str,
        capabilities: frozenset[Capability],
        port_ids: frozenset[str],
        operations: frozenset[str] = frozenset(),
        max_tier: RiskTier = RiskTier.T1,
        budget_usd: Decimal = Decimal("0"),
        venture_id: str | None = None,
        ttl: timedelta = DEFAULT_TOKEN_TTL,
    ) -> CapabilityToken:
        """Mint a token.

        Raises:
            ValueError: the grant includes a forbidden capability, reaches T4,
                or has a non-positive lifetime. All three are programming
                errors rather than runtime conditions — there is no token that
                authorises a prohibited action, so one cannot be requested.
        """
        forbidden = capabilities & FORBIDDEN_CAPABILITIES
        if forbidden:
            raise ValueError(
                f"cannot grant forbidden capability {sorted(c.value for c in forbidden)}"
            )
        if max_tier.is_prohibited:
            raise ValueError("no token may grant T4; prohibited actions have no approval path")
        if ttl <= timedelta(0):
            raise ValueError("token lifetime must be positive")
        if not port_ids:
            raise ValueError("a token granting no port authorises nothing; refuse to mint it")

        now = self._clock.now()
        token = CapabilityToken(
            token_id=self._id_factory(),
            subject=subject,
            capabilities=capabilities,
            port_ids=port_ids,
            operations=operations,
            max_tier=max_tier,
            budget_usd=budget_usd,
            venture_id=venture_id,
            issued_at=now,
            expires_at=now + ttl,
        )
        return token.model_copy(update={"signature": self.sign(token)})

    def verify(self, token: CapabilityToken) -> None:
        """Check the signature and the clock.

        Raises:
            TokenInvalid: the token was altered after issue, or has expired.
        """
        expected = self.sign(token)
        if not token.signature or not hmac.compare_digest(expected, token.signature):
            raise TokenInvalid(token.token_id, "signature does not match its scope")
        if token.is_expired(self._clock.now()):
            raise TokenInvalid(token.token_id, f"expired at {token.expires_at.isoformat()}")

    def authorize(
        self,
        token: CapabilityToken,
        request: ActionRequest,
        tier: RiskTier,
    ) -> None:
        """Check that a verified token covers this exact action.

        Raises:
            TokenInvalid: the token itself does not hold up.
            CapabilityDenied: the token is valid but does not reach this action.
        """
        self.verify(token)

        if token.subject != request.actor:
            raise CapabilityDenied(
                token.token_id,
                request.action_id,
                f"issued to {token.subject!r}, presented by {request.actor!r}",
            )
        if not token.permits_port(request.port_id):
            raise CapabilityDenied(
                token.token_id, request.action_id, f"port {request.port_id!r} is not in scope"
            )
        if not token.permits_operation(request.operation):
            raise CapabilityDenied(
                token.token_id,
                request.action_id,
                f"operation {request.operation!r} is not in scope",
            )

        missing = request.capabilities - token.capabilities
        if missing:
            raise CapabilityDenied(
                token.token_id,
                request.action_id,
                f"requires capability {sorted(c.value for c in missing)}",
            )
        if tier > token.max_tier:
            raise CapabilityDenied(
                token.token_id,
                request.action_id,
                f"classified {tier.name}, token reaches only {token.max_tier.name}",
            )
        if (
            token.venture_id is not None
            and request.venture_id is not None
            and token.venture_id != request.venture_id
        ):
            raise CapabilityDenied(
                token.token_id,
                request.action_id,
                f"scoped to venture {token.venture_id!r}, not {request.venture_id!r}",
            )


def _uuid_id() -> str:
    return uuid4().hex
