"""Ambient-effect protocols: time and randomness.

Nothing in the domain reads a clock or a random source directly. Both are
injected, which is what makes governance — token expiry, approval cooling-off,
budget periods, audit timestamps — testable without waiting for real time to
pass, and reproducible when a decision is reconstructed months later.

The concrete implementations deliberately live outside `core`: a clock that
reads the host is an effect, and `core` has none. Tests inject a frozen clock;
the composition root injects a system clock.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Protocol, TypeVar, runtime_checkable

T_co = TypeVar("T_co", covariant=True)


@runtime_checkable
class Clock(Protocol):
    """The only sanctioned source of 'now'."""

    def now(self) -> datetime:
        """Timezone-aware current instant. Naive datetimes are a bug."""
        ...

    def today(self) -> date:
        """Current date, in the same zone as `now`."""
        ...


@runtime_checkable
class Random(Protocol):
    """The only sanctioned source of non-determinism."""

    def random(self) -> float:
        """A float in [0.0, 1.0)."""
        ...

    def choice(self, seq: Sequence[T_co]) -> T_co:
        """One element of a non-empty sequence."""
        ...


class IdFactory(Protocol):
    """Produces opaque identifiers for tokens, approvals and reservations.

    Injected for the same reason as the clock: an identifier that appears in an
    audit record must be reproducible in a test that asserts on that record.
    """

    def __call__(self) -> str: ...
