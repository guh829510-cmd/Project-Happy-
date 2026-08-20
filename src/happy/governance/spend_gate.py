"""Pre-call authorisation: estimate the worst case, hold it, then settle.

The gate sits **before** LiteLLM, not inside it. That placement is the control:
the LiteLLM key is held by the gate, so there is no route to the provider that
skips the reservation.

    REQUEST -> estimate max cost -> reserve -> ALLOW/DENY -> LiteLLM
            -> actual cost -> settle -> audit

The estimate is a *bound*, not a guess:

    worst_case = input_tokens x (1 + margin) x input_price
               + max_output_tokens x output_price

Output cannot exceed `max_output_tokens` because the gate sends that value.
Input is measured, then inflated by a margin because `litellm.token_counter`
has no Anthropic-specific tokenizer and may undercount. Both terms therefore
bound from above.

If any term is unavailable — no price for the model, no token count — there is
no bound, and no bound means no call.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from happy.governance.budget_store import BudgetStore, Reservation
from happy.governance.errors import BudgetExceeded

DEFAULT_INPUT_MARGIN = Decimal("0.25")
"""Inflate measured input tokens by 25%. Conservative, not precise, on purpose."""


class Unpriceable(BudgetExceeded):
    """The request cannot be bounded, so it cannot be authorised.

    A subclass of `BudgetExceeded` so callers that already refuse on budget
    grounds refuse on this too, rather than needing a second except clause.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(
            scope="request", key="unpriceable", limit=Decimal("0"), attempted=Decimal("0")
        )
        self.reason = reason
        self.args = (f"cannot bound request cost: {reason}",)


@dataclass(frozen=True)
class Pricing:
    """Per-token prices for one model, in dollars."""

    input_cost_per_token: Decimal
    output_cost_per_token: Decimal

    def __post_init__(self) -> None:
        for name, value in (
            ("input_cost_per_token", self.input_cost_per_token),
            ("output_cost_per_token", self.output_cost_per_token),
        ):
            if not value.is_finite() or value < 0:
                raise ValueError(f"{name} must be finite and non-negative, got {value}")


def estimate_max_cost(
    *,
    input_tokens: int,
    max_output_tokens: int,
    pricing: Pricing,
    input_margin: Decimal = DEFAULT_INPUT_MARGIN,
) -> Decimal:
    """The most this request can possibly cost. Pure; no I/O."""
    if input_tokens < 0 or max_output_tokens < 0:
        raise ValueError("token counts must be non-negative")
    if max_output_tokens == 0:
        raise ValueError("max_output_tokens must be set; it is the output bound")
    padded_input = (Decimal(input_tokens) * (Decimal(1) + input_margin)).to_integral_value(
        rounding="ROUND_CEILING"
    )
    return (
        padded_input * pricing.input_cost_per_token
        + Decimal(max_output_tokens) * pricing.output_cost_per_token
    )


@dataclass(frozen=True)
class Outcome:
    """What happened, once the dust settled."""

    request_id: str
    authorised_usd: Decimal
    actual_usd: Decimal
    response: Any


class SpendGate:
    """Authorise, call, settle. The whole circuit breaker in one object."""

    def __init__(
        self,
        store: BudgetStore,
        *,
        now: Callable[[], datetime],
        input_margin: Decimal = DEFAULT_INPUT_MARGIN,
    ) -> None:
        self._store = store
        self._now = now
        self._margin = input_margin

    def call(
        self,
        *,
        request_id: str,
        scopes: Mapping[str, str],
        input_tokens: int | None,
        max_output_tokens: int,
        pricing: Pricing | None,
        invoke: Callable[[], Any],
        cost_of: Callable[[Any], Decimal | str | float | None],
    ) -> Outcome:
        """Run one guarded request.

        `invoke` is only called if the reservation succeeds. If it raises, the
        hold is released in full — a call that never reached the provider must
        not consume budget.

        Raises:
            Unpriceable: the cost could not be bounded, so nothing was called.
            BudgetExceeded: a limit refused the request; nothing was called.
        """
        if pricing is None:
            raise Unpriceable("no pricing available for this model")
        if input_tokens is None:
            raise Unpriceable("input token count unavailable")

        bound = estimate_max_cost(
            input_tokens=input_tokens,
            max_output_tokens=max_output_tokens,
            pricing=pricing,
            input_margin=self._margin,
        )

        reservation: Reservation = self._store.reserve(
            request_id=request_id,
            amount_usd=bound,
            scopes=scopes,
            now=self._now(),
        )

        try:
            response = invoke()
        except BaseException as exc:
            self._store.release(
                reservation,
                now=self._now(),
                reason=f"call failed: {type(exc).__name__}",
            )
            raise

        try:
            reported = cost_of(response)
        except Exception as exc:  # a cost reader that throws is an untrusted cost
            reported = None
            _ = exc

        actual = self._store.settle(reservation, reported, now=self._now())
        return Outcome(request_id, reservation.amount_usd, actual, response)
