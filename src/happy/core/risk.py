"""Risk tiers.

The ordering is meaningful: a higher tier is strictly more constrained. Code
may raise a tier; nothing in the system may lower one.
"""

from __future__ import annotations

from enum import IntEnum


class RiskTier(IntEnum):
    """How an action is handled by the governance kernel."""

    T0 = 0
    """Read-only, internal, free or negligible cost. Auto-execute, logged."""

    T1 = 1
    """Internal write, or metered spend within budget. Auto-execute, logged."""

    T2 = 2
    """Externally visible, or above the cost threshold. Human approval required."""

    T3 = 3
    """Irreversible, financial, legal or identity-bearing.

    Human approval plus typed confirmation plus a cooling-off period.
    """

    T4 = 4
    """Prohibited. Denied in code. No approval path exists."""

    @property
    def requires_approval(self) -> bool:
        """True when a human must approve before the action may proceed."""
        return self in (RiskTier.T2, RiskTier.T3)

    @property
    def is_prohibited(self) -> bool:
        """True when no approval can authorise the action."""
        return self is RiskTier.T4

    @property
    def auto_executable(self) -> bool:
        """True when the runtime may execute without blocking on a human."""
        return self in (RiskTier.T0, RiskTier.T1)

    def raised_to(self, other: RiskTier) -> RiskTier:
        """Return the stricter of two tiers.

        This is the only sanctioned way to combine tiers. There is deliberately
        no `lowered_to`.
        """
        return self if self >= other else other
