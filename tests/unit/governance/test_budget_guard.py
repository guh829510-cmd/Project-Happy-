"""Budget accounting.

Cost is the failure mode most likely to actually occur, and the one that shows
up as a bill rather than an alert. The behaviour worth pinning down is that a
hold placed on authorisation is real: two actions authorised concurrently
cannot both see room only one of them has.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest

from happy.governance.action import ActionRequest
from happy.governance.budget_guard import BudgetGuard, BudgetLimits
from happy.governance.capability import CapabilityToken
from happy.governance.errors import BudgetExceeded

if TYPE_CHECKING:
    from tests.conftest import FrozenClock


def action(cost: str, **overrides: Any) -> ActionRequest:
    fields: dict[str, Any] = {
        "actor": "research_analyst",
        "port_id": "llm_provider",
        "operation": "complete",
        "estimated_cost_usd": Decimal(cost),
    }
    fields.update(overrides)
    return ActionRequest(**fields)


def test_a_reservation_holds_against_every_applicable_scope(budget: BudgetGuard) -> None:
    budget.reserve(action("0.50", task_id="task-1", venture_id="venture-1"))

    assert budget.reserved("agent_daily", "research_analyst:2026-08-20") == Decimal("0.50")
    assert budget.reserved("task", "task-1") == Decimal("0.50")
    assert budget.reserved("venture_daily", "venture-1:2026-08-20") == Decimal("0.50")
    assert budget.reserved("global_daily", "2026-08-20") == Decimal("0.50")
    assert budget.reserved("global_monthly", "2026-08") == Decimal("0.50")


def test_holds_are_visible_to_the_next_authorisation(budget: BudgetGuard) -> None:
    """The concurrency property: an unsettled hold still occupies the budget."""
    for _ in range(10):
        budget.reserve(action("1.00"))

    with pytest.raises(BudgetExceeded) as excinfo:
        budget.reserve(action("1.00"))

    assert excinfo.value.scope == "agent_daily"
    assert excinfo.value.limit == Decimal("10.00")


def test_a_single_absurd_action_is_refused_outright(budget: BudgetGuard) -> None:
    """The per-action ceiling catches one bad call, not a busy day."""
    with pytest.raises(BudgetExceeded) as excinfo:
        budget.reserve(action("2.01"))

    assert excinfo.value.scope == "action"
    assert budget.reserved("global_daily", "2026-08-20") == Decimal("0")


def test_a_refused_reservation_holds_nothing(budget: BudgetGuard) -> None:
    budget.reserve(action("2.00", task_id="task-1"))
    budget.reserve(action("2.00", task_id="task-1"))

    with pytest.raises(BudgetExceeded) as excinfo:
        budget.reserve(action("1.50", task_id="task-1", venture_id="venture-1"))

    # The task scope is the one that refused, and the scopes it would also have
    # touched are untouched: a refusal leaves no partial hold behind.
    assert excinfo.value.scope == "task"
    assert budget.reserved("task", "task-1") == Decimal("4.00")
    assert budget.reserved("venture_daily", "venture-1:2026-08-20") == Decimal("0")


def test_committing_moves_a_hold_into_spend(budget: BudgetGuard) -> None:
    reservation = budget.reserve(action("1.00"))
    breaches = budget.commit(reservation, Decimal("0.60"))

    assert breaches == ()
    assert budget.reserved("global_daily", "2026-08-20") == Decimal("0")
    assert budget.spent("global_daily", "2026-08-20") == Decimal("0.60")


def test_releasing_an_action_that_never_ran_spends_nothing(budget: BudgetGuard) -> None:
    reservation = budget.reserve(action("1.00"))
    budget.release(reservation)

    assert budget.reserved("global_daily", "2026-08-20") == Decimal("0")
    assert budget.spent("global_daily", "2026-08-20") == Decimal("0")


def test_releasing_twice_does_not_credit_the_budget(budget: BudgetGuard) -> None:
    reservation = budget.reserve(action("1.00"))
    budget.release(reservation)
    budget.release(reservation)

    assert budget.reserved("global_daily", "2026-08-20") == Decimal("0")


def test_an_underestimate_is_reported_as_a_breach(budget: BudgetGuard) -> None:
    """Estimates can be wrong. The money is already gone; the point is to know."""
    for _ in range(9):
        budget.commit(budget.reserve(action("1.00")), Decimal("1.00"))

    reservation = budget.reserve(action("1.00"))
    breaches = budget.commit(reservation, Decimal("1.75"))

    scopes = {breach.scope for breach in breaches}
    assert "agent_daily" in scopes
    assert all(breach.spent > breach.limit for breach in breaches)


def test_daily_scopes_reset_with_the_date(budget: BudgetGuard, clock: FrozenClock) -> None:
    budget.commit(budget.reserve(action("2.00")), Decimal("2.00"))
    clock.advance(timedelta(days=1))

    assert budget.spent("global_daily", "2026-08-21") == Decimal("0")
    assert budget.spent("global_monthly", "2026-08") == Decimal("2.00")


def test_a_token_budget_is_enforced_alongside_the_configured_limits(
    budget: BudgetGuard, token: CapabilityToken
) -> None:
    """Authority to spend is part of the grant, not a separate setting."""
    budget.reserve(action("1.50"), token=token)
    budget.reserve(action("1.50"), token=token)

    with pytest.raises(BudgetExceeded) as excinfo:
        budget.reserve(action("1.00"), token=token)

    assert excinfo.value.scope == "token"
    assert excinfo.value.limit == Decimal("3.00")


def test_remaining_reports_headroom(budget: BudgetGuard) -> None:
    budget.commit(budget.reserve(action("1.00")), Decimal("1.00"))
    assert budget.remaining("agent_daily", "research_analyst:2026-08-20") == Decimal("9.00")
    assert budget.remaining("agent_daily", "nobody:2026-08-20") is None


def test_unlimited_scopes_never_refuse(clock: FrozenClock) -> None:
    """`None` means unlimited — used for a scope, never for the global ones."""
    guard = BudgetGuard(
        BudgetLimits(
            per_action_usd=None,
            per_task_usd=None,
            per_agent_daily_usd=None,
            per_venture_daily_usd=None,
            global_daily_usd=Decimal("50"),
            global_monthly_usd=Decimal("300"),
        ),
        clock,
    )
    guard.reserve(action("49.00"))
    with pytest.raises(BudgetExceeded) as excinfo:
        guard.reserve(action("2.00"))

    assert excinfo.value.scope == "global_daily"


def test_free_actions_are_free(budget: BudgetGuard) -> None:
    for _ in range(100):
        budget.commit(budget.reserve(action("0")), Decimal("0"))

    assert budget.spent("global_daily", "2026-08-20") == Decimal("0")
