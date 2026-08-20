"""DeploymentProvider — ship a venture's software.

Preview deployments are cheap and disposable; production affects real users.
The tiering follows that asymmetry rather than treating all deploys alike.
"""

from __future__ import annotations

from abc import abstractmethod
from datetime import datetime
from enum import StrEnum
from typing import ClassVar

from pydantic import Field

from happy.core.capability import Capability
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
from happy.core.terms import AuthRequirement, AuthScheme, CostKind, CostModel, RateLimit


class EnvironmentKind(StrEnum):
    PREVIEW = "preview"
    STAGING = "staging"
    PRODUCTION = "production"


class DescribeEnvironmentRequest(PortInput):
    environment: str


class EnvironmentState(PortOutput):
    environment: str
    kind: EnvironmentKind
    current_ref: str
    healthy: bool
    url: str | None = None
    last_deployed_at: datetime | None = None


class DeployPreviewRequest(PortInput):
    environment: str
    git_ref: str
    build_command: str | None = None


class DeployProductionRequest(PortInput):
    environment: str
    git_ref: str
    approval_id: str
    """Production deployment requires an approval; enforced by the type."""
    rollback_ref: str
    """The ref to return to. A deploy without a rollback path is not accepted."""


class DeployResult(PortOutput):
    environment: str
    deployed_ref: str
    url: str | None = None
    deployed_at: datetime
    healthy: bool
    rollback_ref: str | None = None


class RollbackRequest(PortInput):
    environment: str
    to_ref: str
    reason: str = Field(min_length=1, max_length=512)


@register_port
class DeploymentProviderPort(CapabilityPort):
    """Deploy and roll back a venture's application.

    `deploy_production` is T3: it is externally visible, affects real users, and
    is the point at which a generated product becomes something people depend
    on. It requires an approval id and a rollback ref in its input, so neither
    can be forgotten by an adapter.
    """

    descriptor: ClassVar[PortDescriptor] = PortDescriptor(
        port_id="deployment_provider",
        version="1.0",
        summary="Preview and production deployment with mandatory rollback paths.",
        provenance_kind=ProvenanceKind.SYSTEM_EVENT,
        auth=AuthRequirement(
            scheme=AuthScheme.BEARER_TOKEN,
            required=True,
            credential_keys=("HAPPY_DEPLOY_TOKEN",),
            scopes=("deployments:write",),
            notes="Token must not carry account, billing or DNS administration scope.",
        ),
        rate_limit=RateLimit(requests=10, window_seconds=3600, concurrent=1),
        operations=(
            OperationSpec(
                name="describe_environment",
                summary="Report an environment's current state and health.",
                risk_tier=RiskTier.T0,
                capabilities=frozenset({Capability.NETWORK_READ}),
                input_model=DescribeEnvironmentRequest,
                output_model=EnvironmentState,
                idempotent=True,
                typical_cost=CostModel(kind=CostKind.FREE),
            ),
            OperationSpec(
                name="deploy_preview",
                summary="Deploy to a disposable preview environment.",
                risk_tier=RiskTier.T2,
                capabilities=frozenset({Capability.NETWORK_WRITE, Capability.DEPLOY_PREVIEW}),
                input_model=DeployPreviewRequest,
                output_model=DeployResult,
                externally_visible=True,
                typical_cost=CostModel(kind=CostKind.FREEMIUM),
            ),
            OperationSpec(
                name="deploy_production",
                summary="Deploy to production against an approval.",
                risk_tier=RiskTier.T3,
                capabilities=frozenset(
                    {Capability.NETWORK_WRITE, Capability.DEPLOY_PRODUCTION}
                ),
                input_model=DeployProductionRequest,
                output_model=DeployResult,
                externally_visible=True,
                typical_cost=CostModel(kind=CostKind.SUBSCRIPTION),
            ),
            OperationSpec(
                name="rollback",
                summary="Return an environment to a known-good ref.",
                risk_tier=RiskTier.T2,
                capabilities=frozenset(
                    {Capability.NETWORK_WRITE, Capability.DEPLOY_PRODUCTION}
                ),
                input_model=RollbackRequest,
                output_model=DeployResult,
                externally_visible=True,
                typical_cost=CostModel(kind=CostKind.FREE),
            ),
        ),
        prohibited_operations=(
            ProhibitedOperationSpec(
                name="delete_environment",
                reason="Irreversible destruction of a running venture.",
            ),
            ProhibitedOperationSpec(
                name="rotate_production_secrets",
                reason="Unattended secret rotation can lock the Chairman out of "
                "their own infrastructure.",
            ),
            ProhibitedOperationSpec(
                name="change_dns",
                reason="DNS control is identity-bearing and reserved to the Chairman.",
            ),
            ProhibitedOperationSpec(
                name="modify_billing",
                reason="Changing a hosting plan is a financial commitment.",
            ),
            ProhibitedOperationSpec(
                name="scale_infrastructure",
                reason="Autoscaling spend is uncapped spend.",
            ),
        ),
        notes="Rollback is deliberately cheaper (T2) than deploying (T3): "
        "recovering from a mistake must never be harder than making one.",
    )

    @abstractmethod
    async def describe_environment(
        self, request: DescribeEnvironmentRequest
    ) -> EnvironmentState: ...

    @abstractmethod
    async def deploy_preview(self, request: DeployPreviewRequest) -> DeployResult: ...

    @abstractmethod
    async def deploy_production(self, request: DeployProductionRequest) -> DeployResult: ...

    @abstractmethod
    async def rollback(self, request: RollbackRequest) -> DeployResult: ...
