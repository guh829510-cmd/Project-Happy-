"""DataSource — structured data from an identified provider under known terms.

This port is the reason `DataSourceMetadata` exists. Its `describe()` operation
returns that metadata, and the governance kernel calls
`happy.core.usage_policy.evaluate_source_usage` against it before any derived
artifact is published, redistributed, or shipped commercially.

The distinction that matters commercially: the client library's licence says
nothing about the data. `yfinance` is Apache-2.0; Yahoo Finance's terms are
not. `describe()` reports the terms of the *data*.
"""

from __future__ import annotations

from abc import abstractmethod
from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar

from pydantic import Field

from happy.core.capability import Capability
from happy.core.ports.base import (
    CapabilityPort,
    OperationSpec,
    PortDescriptor,
    PortInput,
    PortOutput,
    register_port,
)
from happy.core.provenance import ProvenanceKind
from happy.core.risk import RiskTier
from happy.core.terms import (
    AuthRequirement,
    AuthScheme,
    CostKind,
    CostModel,
    DataSourceMetadata,
    RateLimit,
)


class DescribeRequest(PortInput):
    """No arguments: a source describes itself."""


class SourceDescription(PortOutput):
    metadata: DataSourceMetadata


class SeriesRequest(PortInput):
    series_id: str
    start: date | None = None
    end: date | None = None
    max_points: int = Field(default=1000, ge=1, le=100_000)


class SeriesPoint(PortOutput):
    at: datetime
    value: Decimal


class SeriesResult(PortOutput):
    series_id: str
    points: tuple[SeriesPoint, ...]
    unit: str | None = None
    source_id: str
    truncated: bool = False


class RecordsRequest(PortInput):
    collection: str
    filters: tuple[tuple[str, str], ...] = ()
    """Key/value pairs as tuples, so the request stays hashable and frozen."""
    max_records: int = Field(default=100, ge=1, le=10_000)


class RecordsResult(PortOutput):
    collection: str
    records: tuple[str, ...]
    """JSON-encoded records. Shape is provider-specific and validated upstream."""
    source_id: str
    truncated: bool = False


@register_port
class DataSourcePort(CapabilityPort):
    """A structured data provider with declared, machine-readable terms."""

    descriptor: ClassVar[PortDescriptor] = PortDescriptor(
        port_id="data_source",
        version="1.0",
        summary="Structured data retrieval with machine-readable licensing terms.",
        provenance_kind=ProvenanceKind.VENDOR_API,
        auth=AuthRequirement(
            scheme=AuthScheme.API_KEY,
            required=False,
            credential_keys=("HAPPY_DATASOURCE_API_KEY",),
            supports_read_only_credential=True,
            notes="Public sources (SEC EDGAR, RSS, open data) need no credential.",
        ),
        rate_limit=RateLimit(
            requests=10,
            window_seconds=1,
            notes="Overridden per source; SEC EDGAR requires a declared User-Agent.",
        ),
        operations=(
            OperationSpec(
                name="describe",
                summary="Return this source's licensing and usage terms.",
                risk_tier=RiskTier.T0,
                capabilities=frozenset(),
                input_model=DescribeRequest,
                output_model=SourceDescription,
                idempotent=True,
                emits_provenance=False,
                typical_cost=CostModel(kind=CostKind.FREE),
            ),
            OperationSpec(
                name="fetch_series",
                summary="Retrieve a time series.",
                risk_tier=RiskTier.T1,
                capabilities=frozenset({Capability.NETWORK_READ}),
                input_model=SeriesRequest,
                output_model=SeriesResult,
                idempotent=True,
                typical_cost=CostModel(kind=CostKind.FREEMIUM, unit="per_request"),
            ),
            OperationSpec(
                name="fetch_records",
                summary="Retrieve records from a collection.",
                risk_tier=RiskTier.T1,
                capabilities=frozenset({Capability.NETWORK_READ}),
                input_model=RecordsRequest,
                output_model=RecordsResult,
                idempotent=True,
                typical_cost=CostModel(kind=CostKind.FREEMIUM, unit="per_request"),
            ),
        ),
        prohibited_operations=(),
        notes=(
            "`describe()` must be callable without credentials so the policy "
            "engine can evaluate terms before any billable call is made."
        ),
    )

    @abstractmethod
    def terms(self) -> DataSourceMetadata:
        """Narrowed return type: a data source's terms are always full metadata."""

    @abstractmethod
    async def describe(self, request: DescribeRequest) -> SourceDescription: ...

    @abstractmethod
    async def fetch_series(self, request: SeriesRequest) -> SeriesResult: ...

    @abstractmethod
    async def fetch_records(self, request: RecordsRequest) -> RecordsResult: ...
