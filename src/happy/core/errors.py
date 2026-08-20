"""Domain errors.

`ProhibitedAction` is deliberately not a subclass of anything catchable by
generic port error handling. A prohibited action is not a failure to be
retried or degraded around; it is a refusal.
"""

from __future__ import annotations


class HappyError(Exception):
    """Base class for all domain errors."""


class PortError(HappyError):
    """A capability port failed to satisfy its contract."""


class ProhibitedAction(HappyError):
    """A T4 action was attempted.

    There is no approval path for this error. Governance cannot escalate it to
    the Chairman, because T4 actions have no approval workflow by design. The
    only resolution is that the action is not performed.
    """

    def __init__(self, action: str, reason: str) -> None:
        self.action = action
        self.reason = reason
        super().__init__(f"prohibited action {action!r}: {reason}")


class UsageNotPermitted(HappyError):
    """A source's terms do not permit the intended use of its data."""

    def __init__(self, source: str, intent: str, reason: str) -> None:
        self.source = source
        self.intent = intent
        self.reason = reason
        super().__init__(f"source {source!r} may not be used for {intent!r}: {reason}")


class MetadataIncomplete(HappyError):
    """Required provenance or terms metadata is missing or unverified."""
