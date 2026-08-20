"""Shared fixtures.

Every test in this suite is offline and deterministic. Nothing here opens a
socket, reads a clock, or needs a credential.
"""

from __future__ import annotations

from datetime import date

import pytest

from happy.core.terms import (
    CommercialUse,
    CostKind,
    CostModel,
    DataSourceMetadata,
    Permission,
    RateLimit,
)

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
