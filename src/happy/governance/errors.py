"""Governance errors.

Every error here is a refusal or a stop, never a degradation. Nothing in this
module is retryable: if governance cannot decide, the action does not happen.
`ProhibitedAction` deliberately stays in `happy.core.errors` — a T4 refusal is
a property of the domain, not of the kernel that happens to enforce it.
"""

from __future__ import annotations

from decimal import Decimal

from happy.core.errors import HappyError
from happy.core.risk import RiskTier


class GovernanceError(HappyError):
    """Base class for kernel refusals."""


class KillSwitchEngaged(GovernanceError):
    """The global stop is engaged. Nothing executes, at any tier."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"kill switch engaged: {reason}")


class TokenInvalid(GovernanceError):
    """A capability token failed verification."""

    def __init__(self, token_id: str, reason: str) -> None:
        self.token_id = token_id
        self.reason = reason
        super().__init__(f"capability token {token_id!r} is invalid: {reason}")


class CapabilityDenied(GovernanceError):
    """A valid token does not authorise this action."""

    def __init__(self, token_id: str, action: str, reason: str) -> None:
        self.token_id = token_id
        self.action = action
        self.reason = reason
        super().__init__(f"token {token_id!r} may not perform {action!r}: {reason}")


class BudgetExceeded(GovernanceError):
    """The action would take spend past a declared limit."""

    def __init__(
        self,
        scope: str,
        key: str,
        limit: Decimal,
        attempted: Decimal,
    ) -> None:
        self.scope = scope
        self.key = key
        self.limit = limit
        self.attempted = attempted
        super().__init__(
            f"{scope} budget for {key!r} exceeded: {attempted} would pass limit {limit}"
        )


class ApprovalRequired(GovernanceError):
    """The action needs a human decision that has not been made."""

    def __init__(self, approval_id: str, tier: RiskTier, summary: str) -> None:
        self.approval_id = approval_id
        self.tier = tier
        self.summary = summary
        super().__init__(f"{tier.name} approval {approval_id} required for {summary}")


class ApprovalInvalid(GovernanceError):
    """An approval cannot be used: wrong state, expired, or mismatched."""

    def __init__(self, approval_id: str, reason: str) -> None:
        self.approval_id = approval_id
        self.reason = reason
        super().__init__(f"approval {approval_id} unusable: {reason}")


class PolicyDenied(GovernanceError):
    """The policy engine refused the action."""

    def __init__(self, action: str, reason: str) -> None:
        self.action = action
        self.reason = reason
        super().__init__(f"policy denied {action!r}: {reason}")


class AuditChainBroken(GovernanceError):
    """The audit log does not verify. Treat the history as untrustworthy."""

    def __init__(self, seq: int, reason: str) -> None:
        self.seq = seq
        self.reason = reason
        super().__init__(f"audit chain broken at seq {seq}: {reason}")
