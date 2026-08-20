"""Shared fixtures.

Every test in this suite is offline and deterministic. Nothing here opens a
socket, reads a clock, or needs a credential.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from happy.core.capability import Capability
from happy.core.risk import RiskTier
from happy.core.terms import (
    CommercialUse,
    CostKind,
    CostModel,
    DataSourceMetadata,
    Permission,
    RateLimit,
)
from happy.governance.audit import AuditChain
from happy.governance.budget_guard import BudgetGuard, BudgetLimits
from happy.governance.capability import CapabilityToken, TokenIssuer
from happy.governance.gateway import ApprovalGateway
from happy.governance.kill_switch import KillSwitch
from happy.governance.policy import PolicyEngine

TODAY = date(2026, 8, 20)
"""Injected 'now' for the whole suite. The domain never reads a real clock."""


@pytest.fixture
def today() -> date:
    return TODAY


@pytest.fixture
def sec_edgar() -> DataSourceMetadata:
    """A source that is unambiguously safe: public-domain government data."""
    return DataSourceMetadata(
        provider="SEC",
        source_name="EDGAR",
        license="public-domain",
        terms_url="https://www.sec.gov/os/accessing-edgar-data",
        commercial_use=CommercialUse.PERMITTED,
        redistribution_allowed=Permission.ALLOWED,
        derived_data_allowed=Permission.ALLOWED,
        attribution_required=False,
        authentication_required=False,
        cost=CostModel(kind=CostKind.FREE),
        rate_limit=RateLimit(
            requests=10, window_seconds=1, notes="declared User-Agent required"
        ),
        last_verified=date(2026, 8, 1),
    )


@pytest.fixture
def yahoo_finance() -> DataSourceMetadata:
    """The trap the audit identified: permissive library, restrictive data terms."""
    return DataSourceMetadata(
        provider="Yahoo",
        source_name="Finance",
        license="UNKNOWN — REQUIRES REVIEW",
        commercial_use=CommercialUse.PROHIBITED,
        redistribution_allowed=Permission.DENIED,
        derived_data_allowed=Permission.DENIED,
        last_verified=date(2026, 8, 1),
        notes="yfinance is Apache-2.0; Yahoo's ToS restricts commercial use.",
    )


@pytest.fixture
def unreviewed_source() -> DataSourceMetadata:
    """A source nobody has assessed. Every permission field is UNKNOWN."""
    return DataSourceMetadata(
        provider="SomeVendor",
        source_name="api",
        last_verified=date(2026, 8, 1),
    )


@pytest.fixture
def paid_tier_source() -> DataSourceMetadata:
    """Commercial use permitted, but only on a paid plan."""
    return DataSourceMetadata(
        provider="FMP",
        source_name="financial-statements",
        license="proprietary",
        commercial_use=CommercialUse.REQUIRES_PAID_TIER,
        redistribution_allowed=Permission.DENIED,
        derived_data_allowed=Permission.CONDITIONAL,
        attribution_required=True,
        cost=CostModel(kind=CostKind.SUBSCRIPTION),
        last_verified=date(2026, 8, 1),
    )


@pytest.fixture
def stale_source() -> DataSourceMetadata:
    """Terms verified long ago. Vendors change terms."""
    return DataSourceMetadata(
        provider="OldVendor",
        source_name="feed",
        license="CC-BY-4.0",
        commercial_use=CommercialUse.PERMITTED,
        redistribution_allowed=Permission.ALLOWED,
        derived_data_allowed=Permission.ALLOWED,
        last_verified=date(2024, 1, 1),
    )


# --- Governance fixtures ---------------------------------------------------
#
# The kernel is built entirely from injected effects, so a test can move time
# forward by an hour, assert on the exact identifier in an audit record, and
# still run in microseconds with no clock, no socket and no database.

NOW = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)
SIGNING_SECRET = b"test-signing-secret-32-bytes-min!!"


class FrozenClock:
    """A clock that only moves when a test moves it."""

    def __init__(self, instant: datetime = NOW) -> None:
        self._instant = instant

    def now(self) -> datetime:
        return self._instant

    def today(self) -> date:
        return self._instant.date()

    def advance(self, delta: timedelta) -> None:
        self._instant += delta


class SequentialIds:
    """Deterministic identifiers, so audit assertions can name them."""

    def __init__(self, prefix: str) -> None:
        self._prefix = prefix
        self._next = 0

    def __call__(self) -> str:
        self._next += 1
        return f"{self._prefix}-{self._next}"


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock()


@pytest.fixture
def audit(clock: FrozenClock) -> AuditChain:
    return AuditChain(clock)


@pytest.fixture
def issuer(clock: FrozenClock) -> TokenIssuer:
    return TokenIssuer(SIGNING_SECRET, clock, id_factory=SequentialIds("token"))


@pytest.fixture
def limits() -> BudgetLimits:
    return BudgetLimits(
        per_action_usd=Decimal("2.00"),
        per_task_usd=Decimal("5.00"),
        per_agent_daily_usd=Decimal("10.00"),
        per_venture_daily_usd=Decimal("25.00"),
        global_daily_usd=Decimal("50.00"),
        global_monthly_usd=Decimal("300.00"),
    )


@pytest.fixture
def budget(limits: BudgetLimits, clock: FrozenClock) -> BudgetGuard:
    return BudgetGuard(limits, clock, id_factory=SequentialIds("res"))


@pytest.fixture
def gateway(clock: FrozenClock, audit: AuditChain) -> ApprovalGateway:
    return ApprovalGateway(clock, audit, id_factory=SequentialIds("appr"))


@pytest.fixture
def kill_switch(audit: AuditChain) -> KillSwitch:
    return KillSwitch(audit)


@pytest.fixture
def engine(
    clock: FrozenClock,
    issuer: TokenIssuer,
    budget: BudgetGuard,
    gateway: ApprovalGateway,
    audit: AuditChain,
    kill_switch: KillSwitch,
) -> PolicyEngine:
    return PolicyEngine(
        clock=clock,
        issuer=issuer,
        budget_guard=budget,
        gateway=gateway,
        audit=audit,
        kill_switch=kill_switch,
    )


@pytest.fixture
def token(issuer: TokenIssuer) -> CapabilityToken:
    """A workaday research token: read the network, think, spend a little."""
    return issuer.issue(
        subject="research_analyst",
        capabilities=frozenset(
            {
                Capability.NETWORK_READ,
                Capability.LLM_INFERENCE,
                Capability.FILESYSTEM_READ,
            }
        ),
        port_ids=frozenset({"llm_provider", "research_provider", "data_source"}),
        max_tier=RiskTier.T1,
        budget_usd=Decimal("3.00"),
        venture_id="venture-1",
    )
