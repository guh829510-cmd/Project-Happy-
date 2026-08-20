"""PaymentProvider — observation and reconciliation only. It cannot move money.

This is the most constrained port in the system, and the constraint is
structural rather than procedural.

**There is no method that moves value.** Not a disabled one, not a guarded one,
not one that checks a flag — the contract simply has no `transfer`, `payout`,
`charge`, `refund` or `debit`. An adapter cannot implement what the interface
does not declare, and `register_port` refuses at import time if any prohibited
name appears as an attribute on the class.

Three further guarantees stack behind that:

* the port declares `MONEY_READ` and never `MONEY_MOVE`, which is in
  `FORBIDDEN_CAPABILITIES` and rejected by `OperationSpec`;
* no payment, banking or brokerage credential exists in the runtime, so there
  is nothing to authenticate with even if code existed;
* the egress allowlist does not contain payment rails.

`record_manual_entry` writes to **our own ledger**. It records a movement the
Chairman already performed elsewhere. It has no outward effect whatsoever.
"""

from __future__ import annotations

from abc import abstractmethod
from datetime import date, datetime
from decimal import Decimal
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


class EntryKind(StrEnum):
    REVENUE = "revenue"
    COST = "cost"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"
    ADJUSTMENT = "adjustment"


class BalanceRequest(PortInput):
    account_id: str


class Balance(PortOutput):
    account_id: str
    currency: str
    available: Decimal
    pending: Decimal = Decimal("0")
    as_of: datetime


class TransactionsRequest(PortInput):
    account_id: str
    start: date
    end: date
    max_records: int = Field(default=200, ge=1, le=5000)


class Transaction(PortOutput):
    transaction_id: str
    account_id: str
    kind: EntryKind
    amount: Decimal
    currency: str
    description: str
    occurred_at: datetime


class TransactionList(PortOutput):
    account_id: str
    transactions: tuple[Transaction, ...]
    truncated: bool = False


class ManualEntryRequest(PortInput):
    """Record something the Chairman already did, elsewhere, by hand."""

    venture_id: str
    kind: EntryKind
    amount: Decimal
    currency: str = "USD"
    description: str = Field(min_length=1, max_length=512)
    occurred_at: datetime
    recorded_by: str = "chairman"
    external_reference: str | None = None


class ManualEntryResult(PortOutput):
    entry_id: str
    venture_id: str
    recorded_at: datetime


class ReconcileRequest(PortInput):
    account_id: str
    venture_id: str
    start: date
    end: date


class ReconcileResult(PortOutput):
    matched: int
    unmatched_external: tuple[str, ...]
    """Transactions seen at the provider with no matching ledger entry."""
    unmatched_internal: tuple[str, ...]
    """Ledger entries with no matching provider transaction."""
    difference: Decimal


@register_port
class PaymentProviderPort(CapabilityPort):
    """Read-only financial observation and ledger reconciliation."""

    descriptor: ClassVar[PortDescriptor] = PortDescriptor(
        port_id="payment_provider",
        version="1.0",
        summary="Observe balances and transactions; reconcile against our ledger. "
        "Cannot move money — no such operation exists.",
        provenance_kind=ProvenanceKind.VENDOR_API,
        auth=AuthRequirement(
            scheme=AuthScheme.API_KEY,
            required=True,
            credential_keys=("HAPPY_PAYMENT_READONLY_KEY",),
            supports_read_only_credential=True,
            notes="MUST be a read-only credential. An adapter presented with a "
            "write-capable key should refuse to start.",
        ),
        rate_limit=RateLimit(requests=30, window_seconds=60),
        operations=(
            OperationSpec(
                name="get_balance",
                summary="Read an account balance.",
                risk_tier=RiskTier.T0,
                capabilities=frozenset({Capability.NETWORK_READ, Capability.MONEY_READ}),
                input_model=BalanceRequest,
                output_model=Balance,
                idempotent=True,
                typical_cost=CostModel(kind=CostKind.FREE),
            ),
            OperationSpec(
                name="list_transactions",
                summary="Read transactions over a date range.",
                risk_tier=RiskTier.T0,
                capabilities=frozenset({Capability.NETWORK_READ, Capability.MONEY_READ}),
                input_model=TransactionsRequest,
                output_model=TransactionList,
                idempotent=True,
                typical_cost=CostModel(kind=CostKind.FREE),
            ),
            OperationSpec(
                name="record_manual_entry",
                summary="Record a movement the Chairman performed elsewhere. "
                "Writes to our ledger only; no outward effect.",
                risk_tier=RiskTier.T1,
                capabilities=frozenset({Capability.MONEY_READ}),
                input_model=ManualEntryRequest,
                output_model=ManualEntryResult,
                typical_cost=CostModel(kind=CostKind.FREE),
            ),
            OperationSpec(
                name="reconcile",
                summary="Compare provider transactions against ledger entries.",
                risk_tier=RiskTier.T0,
                capabilities=frozenset({Capability.NETWORK_READ, Capability.MONEY_READ}),
                input_model=ReconcileRequest,
                output_model=ReconcileResult,
                idempotent=True,
                typical_cost=CostModel(kind=CostKind.FREE),
            ),
        ),
        prohibited_operations=(
            ProhibitedOperationSpec(
                name="transfer",
                reason="The AI never moves money. Permanently prohibited.",
            ),
            ProhibitedOperationSpec(
                name="payout",
                reason="The AI never moves money. Permanently prohibited.",
            ),
            ProhibitedOperationSpec(
                name="charge",
                reason="Charging a customer is a financial act reserved to the Chairman.",
            ),
            ProhibitedOperationSpec(
                name="refund",
                reason="Refunds move money and are irreversible.",
            ),
            ProhibitedOperationSpec(
                name="create_payment_method",
                reason="Binding a payment instrument is a financial commitment.",
            ),
            ProhibitedOperationSpec(
                name="initiate_debit",
                reason="Direct debit is money movement.",
            ),
            ProhibitedOperationSpec(
                name="issue_invoice",
                reason="An invoice is a legal demand for payment.",
            ),
            ProhibitedOperationSpec(
                name="open_credit_line",
                reason="Borrowing is permanently prohibited.",
            ),
        ),
        notes=(
            "The Finance department analyses. The Chairman transacts. This port "
            "only ever describes what already happened."
        ),
    )

    @abstractmethod
    async def get_balance(self, request: BalanceRequest) -> Balance: ...

    @abstractmethod
    async def list_transactions(self, request: TransactionsRequest) -> TransactionList: ...

    @abstractmethod
    async def record_manual_entry(self, request: ManualEntryRequest) -> ManualEntryResult: ...

    @abstractmethod
    async def reconcile(self, request: ReconcileRequest) -> ReconcileResult: ...
