"""EmailProvider — drafts by default, sends only with approval."""

from __future__ import annotations

from abc import abstractmethod
from datetime import datetime
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


class EmailAddress(PortInput):
    address: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    display_name: str | None = None


class DraftRequest(PortInput):
    to: tuple[EmailAddress, ...] = Field(min_length=1, max_length=10)
    subject: str = Field(min_length=1, max_length=256)
    body: str
    ai_disclosure: bool = True
    """Outbound mail from this system discloses that it was AI-generated."""


class Draft(PortOutput):
    draft_id: str
    to: tuple[EmailAddress, ...]
    subject: str
    body: str
    created_at: datetime


class SendRequest(PortInput):
    draft_id: str
    approval_id: str
    """The approval that authorised this send. Adapters must verify it."""


class SendResult(PortOutput):
    message_id: str
    sent_at: datetime
    recipient_count: int


class ListThreadsRequest(PortInput):
    query: str = ""
    max_results: int = Field(default=20, ge=1, le=100)


class ThreadSummary(PortOutput):
    thread_id: str
    subject: str
    participants: tuple[str, ...]
    last_message_at: datetime
    unread: bool = False


class ThreadList(PortOutput):
    threads: tuple[ThreadSummary, ...]
    truncated: bool = False


@register_port
class EmailProviderPort(CapabilityPort):
    """Read mail, draft replies, and send only against an approval.

    `send` requires an `approval_id` in its input. The requirement is in the
    type, so an adapter cannot accidentally offer an unapproved send path.
    """

    descriptor: ClassVar[PortDescriptor] = PortDescriptor(
        port_id="email_provider",
        version="1.0",
        summary="Mailbox read, draft composition, and approval-gated sending.",
        provenance_kind=ProvenanceKind.VENDOR_API,
        handles_personal_data=True,
        auth=AuthRequirement(
            scheme=AuthScheme.OAUTH2,
            required=True,
            credential_keys=("HAPPY_EMAIL_OAUTH_REFRESH_TOKEN",),
            scopes=("mail.read", "mail.compose", "mail.send"),
            supports_read_only_credential=True,
        ),
        rate_limit=RateLimit(
            requests=20,
            window_seconds=60,
            daily_quota=50,
            notes="Deliberately low. Volume sending is not a capability we want.",
        ),
        operations=(
            OperationSpec(
                name="list_threads",
                summary="List mailbox threads.",
                risk_tier=RiskTier.T0,
                capabilities=frozenset(
                    {Capability.NETWORK_READ, Capability.PERSONAL_DATA_READ}
                ),
                input_model=ListThreadsRequest,
                output_model=ThreadList,
                idempotent=True,
                typical_cost=CostModel(kind=CostKind.FREE),
            ),
            OperationSpec(
                name="draft",
                summary="Compose a draft. Nothing leaves the system.",
                risk_tier=RiskTier.T1,
                capabilities=frozenset({Capability.PERSONAL_DATA_READ}),
                input_model=DraftRequest,
                output_model=Draft,
                typical_cost=CostModel(kind=CostKind.FREE),
            ),
            OperationSpec(
                name="send",
                summary="Send a previously approved draft.",
                risk_tier=RiskTier.T2,
                capabilities=frozenset(
                    {
                        Capability.NETWORK_WRITE,
                        Capability.OUTBOUND_MESSAGE,
                        Capability.PERSONAL_DATA_READ,
                    }
                ),
                input_model=SendRequest,
                output_model=SendResult,
                externally_visible=True,
                reversible=False,
                typical_cost=CostModel(kind=CostKind.FREE),
            ),
        ),
        prohibited_operations=(
            ProhibitedOperationSpec(
                name="bulk_send",
                reason="Mass outreach is spam-adjacent, hard to reverse, and "
                "damages the venture's sending reputation.",
            ),
            ProhibitedOperationSpec(
                name="send_without_approval",
                reason="Every outbound message is approved by the Chairman.",
            ),
            ProhibitedOperationSpec(
                name="delete_messages",
                reason="Irreversible destruction of the Chairman's records.",
            ),
            ProhibitedOperationSpec(
                name="import_purchased_list",
                reason="Unlawful in most jurisdictions and unacceptable regardless.",
            ),
        ),
        notes="Outbound mail discloses AI generation and honours opt-outs.",
    )

    @abstractmethod
    async def list_threads(self, request: ListThreadsRequest) -> ThreadList: ...

    @abstractmethod
    async def draft(self, request: DraftRequest) -> Draft: ...

    @abstractmethod
    async def send(self, request: SendRequest) -> SendResult: ...
