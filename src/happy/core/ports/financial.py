"""FinancialAnalyzer — analysis only. It computes; it never transacts.

There is no order, trade, transfer or execution operation on this port, and
none may be added: the audit found that DeepResearchAgent grew live
order-execution agents from a research codebase across a single release. The
prohibition here is structural — the contract has no such method — and the
denylist below names what will never be implemented.
"""

from __future__ import annotations

from abc import abstractmethod
from datetime import date
from decimal import Decimal
from typing import ClassVar

from pydantic import Field

from happy.core.ports.base import (
    CapabilityPort,
    OperationSpec,
    PortDescriptor,
    PortInput,
    PortOutput,
    ProhibitedOperationSpec,
    register_port,
)
from happy.core.provenance import ProvenanceKind
from happy.core.risk import RiskTier
from happy.core.terms import AuthRequirement, CostKind, CostModel, RateLimit


class Assumption(PortInput):
    """A named input the analysis depends on, with its provenance."""

    name: str
    value: Decimal
    unit: str
    source_id: str | None = None
    """None means the Chairman or an agent asserted it without evidence."""
    rationale: str = ""


class UnitEconomicsRequest(PortInput):
    price_per_unit: Decimal = Field(gt=0)
    variable_cost_per_unit: Decimal = Field(ge=0)
    customer_acquisition_cost: Decimal = Field(ge=0)
    monthly_churn_rate: float = Field(ge=0.0, le=1.0)
    horizon_months: int = Field(default=36, ge=1, le=240)
    assumptions: tuple[Assumption, ...] = ()


class UnitEconomicsResult(PortOutput):
    gross_margin: Decimal
    contribution_margin_per_unit: Decimal
    lifetime_value: Decimal
    ltv_to_cac: Decimal
    cac_payback_months: Decimal | None
    """None when contribution margin is non-positive: payback never occurs."""
    breakeven_units: Decimal | None
    assumptions_used: tuple[Assumption, ...]
    warnings: tuple[str, ...] = ()


class ScenarioRequest(PortInput):
    base: UnitEconomicsRequest
    vary: str
    """Field name on `base` to sweep."""
    multipliers: tuple[float, ...] = (0.5, 0.75, 1.0, 1.5, 2.0)


class ScenarioPoint(PortOutput):
    multiplier: float
    result: UnitEconomicsResult


class ScenarioResult(PortOutput):
    vary: str
    points: tuple[ScenarioPoint, ...]
    most_sensitive_to: str | None = None


class RunwayRequest(PortInput):
    cash_on_hand: Decimal = Field(ge=0)
    monthly_burn: Decimal = Field(ge=0)
    monthly_revenue: Decimal = Field(default=Decimal("0"), ge=0)
    monthly_revenue_growth: float = Field(default=0.0, ge=-1.0, le=10.0)
    as_of: date


class RunwayResult(PortOutput):
    runway_months: Decimal | None
    """None means the venture is cash-flow positive at the stated assumptions."""
    zero_cash_date: date | None
    net_monthly_burn: Decimal
    breakeven_month: int | None
    warnings: tuple[str, ...] = ()


@register_port
class FinancialAnalyzerPort(CapabilityPort):
    """Unit economics, scenarios and runway.

    Pure computation over supplied assumptions. It reaches no network and holds
    no credentials, which is why every operation is T0.
    """

    descriptor: ClassVar[PortDescriptor] = PortDescriptor(
        port_id="financial_analyzer",
        version="1.0",
        summary="Unit economics, sensitivity analysis and runway modelling.",
        provenance_kind=ProvenanceKind.DERIVED,
        auth=AuthRequirement.none(),
        rate_limit=RateLimit(notes="Local computation; no external limit applies."),
        operations=(
            OperationSpec(
                name="unit_economics",
                summary="Compute LTV, CAC payback, margins and breakeven.",
                risk_tier=RiskTier.T0,
                capabilities=frozenset(),
                input_model=UnitEconomicsRequest,
                output_model=UnitEconomicsResult,
                idempotent=True,
                typical_cost=CostModel(kind=CostKind.FREE),
            ),
            OperationSpec(
                name="scenario",
                summary="Sweep one assumption and report sensitivity.",
                risk_tier=RiskTier.T0,
                capabilities=frozenset(),
                input_model=ScenarioRequest,
                output_model=ScenarioResult,
                idempotent=True,
                typical_cost=CostModel(kind=CostKind.FREE),
            ),
            OperationSpec(
                name="runway",
                summary="Project runway and the zero-cash date.",
                risk_tier=RiskTier.T0,
                capabilities=frozenset(),
                input_model=RunwayRequest,
                output_model=RunwayResult,
                idempotent=True,
                typical_cost=CostModel(kind=CostKind.FREE),
            ),
        ),
        prohibited_operations=(
            ProhibitedOperationSpec(
                name="place_order",
                reason="Autonomous order execution is permanently prohibited (ADR-0010).",
            ),
            ProhibitedOperationSpec(
                name="execute_trade",
                reason="Autonomous trading is permanently prohibited (ADR-0010).",
            ),
            ProhibitedOperationSpec(
                name="rebalance_portfolio",
                reason="Implies discretionary authority over assets. Never granted.",
            ),
            ProhibitedOperationSpec(
                name="connect_brokerage",
                reason="No brokerage credential may exist in this runtime.",
            ),
        ),
        notes=(
            "Output is analysis, not advice. Every report must carry the "
            "AI-generated-content disclaimer before reaching a decision."
        ),
    )

    @abstractmethod
    async def unit_economics(self, request: UnitEconomicsRequest) -> UnitEconomicsResult: ...

    @abstractmethod
    async def scenario(self, request: ScenarioRequest) -> ScenarioResult: ...

    @abstractmethod
    async def runway(self, request: RunwayRequest) -> RunwayResult: ...
