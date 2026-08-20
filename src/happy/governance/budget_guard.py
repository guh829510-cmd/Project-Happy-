"""Budget accounting — cost as a governed resource.

Runaway spend is the failure mode most likely to actually occur: a loop that
re-asks a model, a research task that fans out, a retry that never gives up.
The guard prices every action **before** it runs and refuses the ones that
would take spend past a declared limit.

Reservations rather than plain counters: an action's cost is held against every
limit that applies from the moment it is authorised until it settles. Two
actions authorised concurrently therefore cannot each see room that only one of
them can have.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from happy.core.protocols import Clock, IdFactory
from happy.governance.action import ActionRequest
from happy.governance.capability import CapabilityToken
from happy.governance.errors import BudgetExceeded

ScopeKey = tuple[str, str]
"""A (scope, key) pair, e.g. ('agent_daily', 'research_analyst:2026-08-20')."""


class BudgetLimits(BaseModel):
    """Spend ceilings. `None` means unlimited — used sparingly and never for
    the global scopes, which are the last line before a surprising invoice."""

    model_config = ConfigDict(frozen=True)

    per_action_usd: Decimal | None = Decimal("2.00")
    per_task_usd: Decimal | None = Decimal("5.00")
    per_agent_daily_usd: Decimal | None = Decimal("10.00")
    per_venture_daily_usd: Decimal | None = Decimal("25.00")
    global_daily_usd: Decimal | None = Decimal("50.00")
    global_monthly_usd: Decimal | None = Decimal("300.00")


class Reservation(BaseModel):
    """Cost held against every applicable limit until the action settles."""

    model_config = ConfigDict(frozen=True)

    reservation_id: str
    action_id: str
    amount_usd: Decimal = Field(ge=0)
    scopes: tuple[ScopeKey, ...]
    created_at: datetime


class BudgetBreach(BaseModel):
    """A limit that actual spend passed after the fact.

    Reservations use estimates, and an estimate can be wrong. A breach is not
    refused — the money is already gone — it is reported, so the caller can stop
    the system rather than discover it in a monthly bill.
    """

    model_config = ConfigDict(frozen=True)

    scope: str
    key: str
    limit: Decimal
    spent: Decimal


class BudgetGuard:
    """In-memory spend accounting.

    State lives here for now; M2 moves it behind a repository so it survives a
    restart. The interface is written so that move changes nothing for callers.
    """

    def __init__(
        self,
        limits: BudgetLimits,
        clock: Clock,
        *,
        id_factory: IdFactory | None = None,
    ) -> None:
        self._limits = limits
        self._clock = clock
        self._id_factory: IdFactory = id_factory or _uuid_id
        self._spent: dict[ScopeKey, Decimal] = {}
        self._reserved: dict[ScopeKey, Decimal] = {}
        self._limit_of: dict[ScopeKey, Decimal] = {}
        self._open: dict[str, Reservation] = {}

    @property
    def limits(self) -> BudgetLimits:
        return self._limits

    def spent(self, scope: str, key: str) -> Decimal:
        return self._spent.get((scope, key), Decimal("0"))

    def reserved(self, scope: str, key: str) -> Decimal:
        return self._reserved.get((scope, key), Decimal("0"))

    def committed_and_held(self, scope: str, key: str) -> Decimal:
        return self.spent(scope, key) + self.reserved(scope, key)

    def remaining(self, scope: str, key: str) -> Decimal | None:
        limit = self._limit_of.get((scope, key))
        if limit is None:
            return None
        return limit - self.committed_and_held(scope, key)

    def reserve(
        self,
        request: ActionRequest,
        *,
        token: CapabilityToken | None = None,
    ) -> Reservation:
        """Hold this action's estimated cost against every applicable limit.

        Raises:
            BudgetExceeded: the action would pass a limit. The action does not
                run; nothing is held.
        """
        amount = request.estimated_cost_usd
        per_action = self._limits.per_action_usd
        if per_action is not None and amount > per_action:
            # A single-action ceiling, checked outright rather than accumulated:
            # it exists to catch one absurd call, not a busy day.
            raise BudgetExceeded("action", request.action_id, per_action, amount)

        applicable = self._applicable_scopes(request, token)

        for (scope, key), limit in applicable:
            if limit is None:
                continue
            projected = self.committed_and_held(scope, key) + amount
            if projected > limit:
                raise BudgetExceeded(scope, key, limit, projected)

        reservation = Reservation(
            reservation_id=self._id_factory(),
            action_id=request.action_id,
            amount_usd=amount,
            scopes=tuple(scope_key for scope_key, _ in applicable),
            created_at=self._clock.now(),
        )
        for scope_key, limit in applicable:
            if limit is not None:
                self._limit_of[scope_key] = limit
            self._reserved[scope_key] = self._reserved.get(scope_key, Decimal("0")) + amount
        self._open[reservation.reservation_id] = reservation
        return reservation

    def commit(
        self, reservation: Reservation, actual_usd: Decimal
    ) -> tuple[BudgetBreach, ...]:
        """Settle a reservation with what the action really cost.

        Returns:
            Any limits the actual spend passed. An empty tuple is the normal
            case; a non-empty one means an estimate was wrong by enough to
            matter and the caller should treat it as an incident.
        """
        self._release(reservation)
        breaches: list[BudgetBreach] = []
        for scope_key in reservation.scopes:
            total = self._spent.get(scope_key, Decimal("0")) + actual_usd
            self._spent[scope_key] = total
            limit = self._limit_of.get(scope_key)
            if limit is not None and total > limit:
                scope, key = scope_key
                breaches.append(
                    BudgetBreach(scope=scope, key=key, limit=limit, spent=total)
                )
        return tuple(breaches)

    def release(self, reservation: Reservation) -> None:
        """Drop a hold for an action that never ran. Nothing is spent."""
        self._release(reservation)

    def _release(self, reservation: Reservation) -> None:
        if self._open.pop(reservation.reservation_id, None) is None:
            return
        for scope_key in reservation.scopes:
            held = self._reserved.get(scope_key, Decimal("0")) - reservation.amount_usd
            self._reserved[scope_key] = max(held, Decimal("0"))

    def _applicable_scopes(
        self,
        request: ActionRequest,
        token: CapabilityToken | None,
    ) -> tuple[tuple[ScopeKey, Decimal | None], ...]:
        today = self._clock.today()
        day = today.isoformat()
        month = today.strftime("%Y-%m")
        limits = self._limits

        scopes: list[tuple[ScopeKey, Decimal | None]] = [
            (("agent_daily", f"{request.actor}:{day}"), limits.per_agent_daily_usd),
            (("global_daily", day), limits.global_daily_usd),
            (("global_monthly", month), limits.global_monthly_usd),
        ]
        if request.task_id is not None:
            scopes.append((("task", request.task_id), limits.per_task_usd))
        if request.venture_id is not None:
            scopes.append(
                (
                    ("venture_daily", f"{request.venture_id}:{day}"),
                    limits.per_venture_daily_usd,
                )
            )
        if token is not None and token.budget_usd > 0:
            # The token's own ceiling: authority to spend is part of the grant,
            # not a separate setting an agent could outlive.
            scopes.append((("token", token.token_id), token.budget_usd))
        return tuple(scopes)


def _uuid_id() -> str:
    return uuid4().hex
