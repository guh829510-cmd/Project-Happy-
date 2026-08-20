"""NotificationProvider — reaching the Chairman.

Distinct from `EmailProvider` on purpose. This port talks to exactly one
person, who has consented to receive it, so it is low-risk. That is what makes
it usable for approval requests: the mechanism that asks for permission must
not itself need permission.
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


class Urgency(StrEnum):
    LOW = "low"
    """Batched into the digest."""
    NORMAL = "normal"
    HIGH = "high"
    """Approval needed, or a budget or runway threshold was crossed."""


class NotifyRequest(PortInput):
    title: str = Field(min_length=1, max_length=128)
    body: str = Field(max_length=4096)
    urgency: Urgency = Urgency.NORMAL
    deep_link: str | None = None
    """Path into the dashboard, e.g. an approval. Never an external URL."""
    dedupe_key: str | None = None
    """Suppresses repeats. Approval fatigue is a security risk."""


class NotifyResult(PortOutput):
    delivered: bool
    channel: str
    sent_at: datetime
    deduplicated: bool = False


@register_port
class NotificationProviderPort(CapabilityPort):
    """One-way notification to the Chairman only."""

    descriptor: ClassVar[PortDescriptor] = PortDescriptor(
        port_id="notification_provider",
        version="1.0",
        summary="Notify the Chairman. Single recipient, no third parties.",
        provenance_kind=ProvenanceKind.SYSTEM_EVENT,
        auth=AuthRequirement(
            scheme=AuthScheme.API_KEY,
            required=False,
            credential_keys=("HAPPY_NOTIFY_WEBHOOK_TOKEN",),
            notes="Console adapter needs no credential.",
        ),
        rate_limit=RateLimit(
            requests=10,
            window_seconds=300,
            notes="Rate-limited to protect the Chairman's attention, "
            "which is the scarcest resource in the system.",
        ),
        operations=(
            OperationSpec(
                name="notify",
                summary="Send a notification to the Chairman.",
                risk_tier=RiskTier.T1,
                capabilities=frozenset({Capability.NETWORK_WRITE}),
                input_model=NotifyRequest,
                output_model=NotifyResult,
                typical_cost=CostModel(kind=CostKind.FREE),
            ),
        ),
        prohibited_operations=(
            ProhibitedOperationSpec(
                name="notify_third_party",
                reason="This port reaches the Chairman only. Contacting anyone "
                "else is outbound messaging and goes through EmailProvider "
                "under approval.",
            ),
            ProhibitedOperationSpec(
                name="broadcast",
                reason="No multi-recipient path exists here.",
            ),
        ),
        notes=(
            "Not externally visible despite writing to the network: the sole "
            "recipient is the system's owner."
        ),
    )

    @abstractmethod
    async def notify(self, request: NotifyRequest) -> NotifyResult: ...
