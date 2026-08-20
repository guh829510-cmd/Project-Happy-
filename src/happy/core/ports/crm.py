"""CRMProvider — contacts and activity. Personal data throughout."""

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


class ContactRef(PortInput):
    contact_id: str


class Contact(PortOutput):
    contact_id: str
    display_name: str
    email: str | None = None
    company: str | None = None
    tags: tuple[str, ...] = ()
    consent_status: str = "unknown"
    """Marketing consent. 'unknown' blocks outreach; there is no implied opt-in."""
    updated_at: datetime


class ListContactsRequest(PortInput):
    query: str = ""
    tag: str | None = None
    max_results: int = Field(default=50, ge=1, le=500)


class ContactList(PortOutput):
    contacts: tuple[Contact, ...]
    truncated: bool = False


class UpsertContactRequest(PortInput):
    contact_id: str | None = None
    display_name: str
    email: str | None = None
    company: str | None = None
    tags: tuple[str, ...] = ()
    consent_status: str = "unknown"
    source_id: str
    """Where this contact came from. Unsourced contacts are rejected."""


class UpsertResult(PortOutput):
    contact_id: str
    created: bool
    updated_at: datetime


class LogActivityRequest(PortInput):
    contact: ContactRef
    activity_type: str
    summary: str = Field(max_length=2048)
    occurred_at: datetime


class ActivityLogged(PortOutput):
    activity_id: str
    contact_id: str
    logged_at: datetime


@register_port
class CRMProviderPort(CapabilityPort):
    """Customer records.

    Everything here is personal data. Consent is explicit and stored; there is
    no bulk export and no bulk import, because both are how customer data
    leaks and how purchased lists enter a system.
    """

    descriptor: ClassVar[PortDescriptor] = PortDescriptor(
        port_id="crm_provider",
        version="1.0",
        summary="Contact records and activity history, with explicit consent state.",
        provenance_kind=ProvenanceKind.VENDOR_API,
        handles_personal_data=True,
        auth=AuthRequirement(
            scheme=AuthScheme.API_KEY,
            required=True,
            credential_keys=("HAPPY_CRM_API_KEY",),
            supports_read_only_credential=True,
        ),
        rate_limit=RateLimit(requests=60, window_seconds=60),
        operations=(
            OperationSpec(
                name="get_contact",
                summary="Fetch one contact.",
                risk_tier=RiskTier.T0,
                capabilities=frozenset(
                    {Capability.NETWORK_READ, Capability.PERSONAL_DATA_READ}
                ),
                input_model=ContactRef,
                output_model=Contact,
                idempotent=True,
                typical_cost=CostModel(kind=CostKind.FREEMIUM),
            ),
            OperationSpec(
                name="list_contacts",
                summary="List contacts, bounded.",
                risk_tier=RiskTier.T0,
                capabilities=frozenset(
                    {Capability.NETWORK_READ, Capability.PERSONAL_DATA_READ}
                ),
                input_model=ListContactsRequest,
                output_model=ContactList,
                idempotent=True,
                typical_cost=CostModel(kind=CostKind.FREEMIUM),
            ),
            OperationSpec(
                name="upsert_contact",
                summary="Create or update a contact.",
                risk_tier=RiskTier.T1,
                capabilities=frozenset(
                    {Capability.NETWORK_WRITE, Capability.PERSONAL_DATA_WRITE}
                ),
                input_model=UpsertContactRequest,
                output_model=UpsertResult,
                typical_cost=CostModel(kind=CostKind.FREEMIUM),
            ),
            OperationSpec(
                name="log_activity",
                summary="Record an interaction against a contact.",
                risk_tier=RiskTier.T1,
                capabilities=frozenset(
                    {Capability.NETWORK_WRITE, Capability.PERSONAL_DATA_WRITE}
                ),
                input_model=LogActivityRequest,
                output_model=ActivityLogged,
                typical_cost=CostModel(kind=CostKind.FREEMIUM),
            ),
        ),
        prohibited_operations=(
            ProhibitedOperationSpec(
                name="bulk_export",
                reason="Mass export of personal data is the classic exfiltration path.",
            ),
            ProhibitedOperationSpec(
                name="bulk_import",
                reason="How purchased and scraped lists enter a CRM.",
            ),
            ProhibitedOperationSpec(
                name="delete_contact",
                reason="Erasure requests are handled by the Chairman, who can "
                "verify the requester's identity.",
            ),
            ProhibitedOperationSpec(
                name="enrich_from_third_party",
                reason="Appending purchased data to a contact without their "
                "knowledge is a consent violation.",
            ),
        ),
    )

    @abstractmethod
    async def get_contact(self, request: ContactRef) -> Contact: ...

    @abstractmethod
    async def list_contacts(self, request: ListContactsRequest) -> ContactList: ...

    @abstractmethod
    async def upsert_contact(self, request: UpsertContactRequest) -> UpsertResult: ...

    @abstractmethod
    async def log_activity(self, request: LogActivityRequest) -> ActivityLogged: ...
