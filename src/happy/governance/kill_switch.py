"""The global stop.

One switch, engaged by the Chairman or by the kernel itself, that halts every
action at every tier — including reads. Fail closed means fail closed: a system
that keeps doing "the safe parts" while something is visibly wrong is a system
still doing things nobody is watching.

Only a human releases it. `release_kill_switch` is on the T4 deny list, so no
agent can reach this class by naming it.
"""

from __future__ import annotations

from datetime import datetime

from happy.governance.audit import AuditChain, AuditDecision
from happy.governance.errors import KillSwitchEngaged


class KillSwitch:
    """Process-wide halt with an audited reason."""

    def __init__(self, audit: AuditChain | None = None) -> None:
        self._audit = audit
        self._reason: str | None = None
        self._engaged_at: datetime | None = None

    @property
    def engaged(self) -> bool:
        return self._reason is not None

    @property
    def reason(self) -> str | None:
        return self._reason

    @property
    def engaged_at(self) -> datetime | None:
        return self._engaged_at

    def engage(self, reason: str) -> None:
        """Stop everything. Engaging an already-engaged switch keeps the first
        reason: the original cause is the one worth investigating."""
        if self._reason is not None:
            return
        self._reason = reason
        if self._audit is not None:
            event = self._audit.record(AuditDecision.KILL_SWITCH_ENGAGED, reason)
            self._engaged_at = event.recorded_at

    def release(self, actor: str, reason: str) -> None:
        """Resume. Named `actor` because only a person may call this."""
        if self._reason is None:
            return
        self._reason = None
        self._engaged_at = None
        if self._audit is not None:
            self._audit.record(
                AuditDecision.KILL_SWITCH_RELEASED,
                f"released by {actor}: {reason}",
                actor=actor,
            )

    def assert_clear(self) -> None:
        """Raises:
        KillSwitchEngaged: the switch is engaged. There is no bypass argument.
        """
        if self._reason is not None:
            raise KillSwitchEngaged(self._reason)
