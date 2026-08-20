"""End-to-end proof that the gate cannot be walked around.

This module is the M1 exit criterion: **a fake dangerous tool is provably
blocked end-to-end**. The fake is written the way a real mistake would arrive —
not as an obviously prohibited method, but as a plausible-looking operation on a
port that declares itself harmless, with a working implementation behind it.
The test asserts that the implementation never runs.

Everything here goes through `GovernedPort`, because that is what a department
is given. These tests are the reason the composition root may never hand out a
raw adapter.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, ClassVar

import pytest

from happy.core.capability import Capability
from happy.core.errors import ProhibitedAction
from happy.core.ports.base import (
    CapabilityPort,
    OperationSpec,
    PortDescriptor,
    PortInput,
    PortOutput,
)
from happy.core.ports.email import (
    Draft,
    DraftRequest,
    EmailProviderPort,
    ListThreadsRequest,
    SendRequest,
    SendResult,
    ThreadList,
)
from happy.core.ports.llm import (
    CompletionRequest,
    CompletionResult,
    EmbeddingRequest,
    EmbeddingResult,
    LLMProviderPort,
    Message,
    Role,
    TokenCountRequest,
    TokenCountResult,
    TokenUsage,
)
from happy.core.ports.payment import (
    Balance,
    BalanceRequest,
    ManualEntryRequest,
    ManualEntryResult,
    PaymentProviderPort,
    ReconcileRequest,
    ReconcileResult,
    TransactionList,
    TransactionsRequest,
)
from happy.core.provenance import ProvenanceKind
from happy.core.risk import RiskTier
from happy.core.terms import (
    AuthRequirement,
    CommercialUse,
    CostKind,
    CostModel,
    Permission,
    ProviderTerms,
    RateLimit,
)
from happy.governance.audit import AuditChain, AuditDecision
from happy.governance.budget_guard import BudgetGuard
from happy.governance.capability import CapabilityToken, TokenIssuer
from happy.governance.errors import ApprovalRequired, PolicyDenied
from happy.governance.gateway import ApprovalGateway
from happy.governance.governed_port import GovernedPort
from happy.governance.kill_switch import KillSwitch
from happy.governance.policy import PolicyEngine

if TYPE_CHECKING:
    from tests.conftest import FrozenClock

pytestmark = pytest.mark.policy

VENDOR_TERMS = ProviderTerms(
    provider="Fake",
    commercial_use=CommercialUse.PERMITTED,
    redistribution_allowed=Permission.ALLOWED,
    attribution_required=False,
    last_verified=date(2026, 8, 1),
)


# --- Fakes -----------------------------------------------------------------


class FakeLLM(LLMProviderPort):
    """A well-behaved adapter that records what it was asked to do."""

    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[str] = []
        self.fail = fail

    def terms(self) -> ProviderTerms:
        return VENDOR_TERMS

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        self.calls.append("complete")
        if self.fail:
            raise RuntimeError("the vendor timed out")
        return CompletionResult(
            text="a considered answer",
            model="fake-standard",
            usage=TokenUsage(input_tokens=10, output_tokens=20),
            cost_usd=Decimal("0.03"),
            stop_reason="end_turn",
        )

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        self.calls.append("embed")
        return EmbeddingResult(
            vectors=((0.1, 0.2),),
            model="fake-embed",
            usage=TokenUsage(input_tokens=5, output_tokens=0),
            cost_usd=Decimal("0.001"),
        )

    async def count_tokens(self, request: TokenCountRequest) -> TokenCountResult:
        self.calls.append("count_tokens")
        return TokenCountResult(input_tokens=10)


class FakePayments(PaymentProviderPort):
    """Read-only by construction: the port declares no way to move money."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def terms(self) -> ProviderTerms:
        return VENDOR_TERMS

    async def get_balance(self, request: BalanceRequest) -> Balance:
        self.calls.append("get_balance")
        return Balance(
            account_id=request.account_id,
            currency="USD",
            available=Decimal("1200.00"),
            as_of=datetime(2026, 8, 20, 9, 0, tzinfo=UTC),
        )

    async def list_transactions(self, request: TransactionsRequest) -> TransactionList:
        self.calls.append("list_transactions")
        return TransactionList(account_id=request.account_id, transactions=())

    async def record_manual_entry(self, request: ManualEntryRequest) -> ManualEntryResult:
        self.calls.append("record_manual_entry")
        return ManualEntryResult(
            entry_id="entry-1",
            venture_id=request.venture_id,
            recorded_at=datetime(2026, 8, 20, 9, 0, tzinfo=UTC),
        )

    async def reconcile(self, request: ReconcileRequest) -> ReconcileResult:
        self.calls.append("reconcile")
        return ReconcileResult(account_id=request.account_id, matched=0, unmatched=0)


class FakeEmail(EmailProviderPort):
    def __init__(self) -> None:
        self.calls: list[str] = []

    def terms(self) -> ProviderTerms:
        return VENDOR_TERMS

    async def list_threads(self, request: ListThreadsRequest) -> ThreadList:
        self.calls.append("list_threads")
        return ThreadList(threads=())

    async def draft(self, request: DraftRequest) -> Draft:
        self.calls.append("draft")
        return Draft(
            draft_id="draft-1",
            to=request.to,
            subject=request.subject,
            body=request.body,
            created_at=datetime(2026, 8, 20, 9, 0, tzinfo=UTC),
        )

    async def send(self, request: SendRequest) -> SendResult:
        self.calls.append("send")
        return SendResult(
            message_id="message-1",
            sent_at=datetime(2026, 8, 20, 9, 0, tzinfo=UTC),
            recipient_count=1,
        )


class SettlementRequest(PortInput):
    supplier: str
    amount_usd: Decimal


class SettlementResult(PortOutput):
    confirmation: str


class DangerousPort(CapabilityPort):
    """The fake dangerous tool.

    It is written the way the mistake would actually arrive. Nothing about the
    declaration is obviously wrong: the tier is T1, the capability is an
    ordinary network write, the summary sounds like bookkeeping, and the method
    behind it works. The only thing that gives it away is the name of the
    operation — which is precisely what the deny list reads.

    Note what it *cannot* do even here: `OperationSpec` refuses
    `Capability.MONEY_MOVE`, so the honest version of this port will not import.
    """

    descriptor: ClassVar[PortDescriptor] = PortDescriptor(
        port_id="supplier_settlement",
        version="1.0",
        summary="Settle supplier balances.",
        provenance_kind=ProvenanceKind.VENDOR_API,
        auth=AuthRequirement.none(),
        rate_limit=RateLimit.unknown(),
        operations=(
            OperationSpec(
                name="wire_funds",
                summary="Record and settle an outstanding supplier balance.",
                risk_tier=RiskTier.T1,
                capabilities=frozenset({Capability.NETWORK_WRITE}),
                input_model=SettlementRequest,
                output_model=SettlementResult,
                typical_cost=CostModel(kind=CostKind.FREE),
            ),
        ),
    )

    def __init__(self) -> None:
        self.money_moved = Decimal("0")

    def terms(self) -> ProviderTerms:
        return VENDOR_TERMS

    async def wire_funds(self, request: SettlementRequest) -> SettlementResult:
        # If governance fails, this line runs and the money is gone.
        self.money_moved += request.amount_usd
        return SettlementResult(confirmation="sent")


# --- Fixtures --------------------------------------------------------------


@pytest.fixture
def llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def governed_llm(
    llm: FakeLLM, engine: PolicyEngine, token: CapabilityToken
) -> GovernedPort:
    return GovernedPort(
        llm,
        engine=engine,
        token=token,
        actor="research_analyst",
        venture_id="venture-1",
        task_id="task-1",
    )


@pytest.fixture
def completion() -> CompletionRequest:
    return CompletionRequest(
        messages=(Message(role=Role.USER, content="Summarise this filing."),),
        budget_usd=Decimal("0.10"),
    )


def dangerous_token(issuer: TokenIssuer) -> CapabilityToken:
    """A generous token, to show that authority is not what stops this."""
    return issuer.issue(
        subject="finance_analyst",
        capabilities=frozenset({Capability.NETWORK_WRITE, Capability.NETWORK_READ}),
        port_ids=frozenset({"supplier_settlement"}),
        max_tier=RiskTier.T3,
        budget_usd=Decimal("100.00"),
    )


# --- The proof -------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_fake_dangerous_tool_is_blocked_end_to_end(
    engine: PolicyEngine,
    issuer: TokenIssuer,
    audit: AuditChain,
    budget: BudgetGuard,
) -> None:
    """The M1 exit criterion.

    A department holds a valid, generously-scoped token for a port whose
    operation is declared T1 and implemented correctly. The call is still
    refused, the implementation never runs, and the attempt is on the record.
    """
    port = DangerousPort()
    governed = GovernedPort(
        port,
        engine=engine,
        token=dangerous_token(issuer),
        actor="finance_analyst",
        venture_id="venture-1",
    )

    with pytest.raises(ProhibitedAction) as excinfo:
        await governed.wire_funds(
            SettlementRequest(supplier="ACME", amount_usd=Decimal("500"))
        )

    assert port.money_moved == Decimal("0"), "the adapter ran; governance failed"
    assert "money_movement" in str(excinfo.value)
    assert excinfo.value.action == "supplier_settlement.wire_funds"

    prohibited = [e for e in audit.events if e.decision is AuditDecision.PROHIBITED]
    assert len(prohibited) == 1
    assert prohibited[0].operation == "wire_funds"
    assert prohibited[0].tier is RiskTier.T4
    assert budget.spent("global_daily", "2026-08-20") == Decimal("0")
    audit.verify()


@pytest.mark.asyncio
async def test_no_approval_can_release_the_blocked_tool(
    engine: PolicyEngine, issuer: TokenIssuer, gateway: ApprovalGateway
) -> None:
    """There is nothing to approve: the attempt never reaches the queue."""
    port = DangerousPort()
    governed = GovernedPort(
        port, engine=engine, token=dangerous_token(issuer), actor="finance_analyst"
    )
    payload = SettlementRequest(supplier="ACME", amount_usd=Decimal("500"))

    with pytest.raises(ProhibitedAction):
        await governed.wire_funds(payload)

    assert gateway.pending() == ()


def test_a_declared_prohibition_has_nothing_to_call(
    engine: PolicyEngine, issuer: TokenIssuer
) -> None:
    """Reaching for the attribute is the attempt, so the attribute refuses."""
    token = issuer.issue(
        subject="finance_analyst",
        capabilities=frozenset({Capability.MONEY_READ}),
        port_ids=frozenset({"payment_provider"}),
    )
    governed = GovernedPort(
        FakePayments(), engine=engine, token=token, actor="finance_analyst"
    )

    for operation in ("transfer", "payout", "refund", "charge", "open_credit_line"):
        with pytest.raises(ProhibitedAction, match="no method to call"):
            getattr(governed, operation)


def test_an_undeclared_operation_is_refused(
    governed_llm: GovernedPort,
) -> None:
    """Unassessed means denied, not 'probably fine'."""
    with pytest.raises(ProhibitedAction, match="not a declared operation"):
        governed_llm.run_local_model  # noqa: B018


def test_the_proxy_offers_no_ungoverned_route_to_an_operation(
    governed_llm: GovernedPort, llm: FakeLLM
) -> None:
    """Every declared operation resolves to the governed wrapper.

    The proxy is not a sandbox — code in this process could import the adapter
    and call it directly — so what is asserted is what the proxy actually
    guarantees: a department handed this object has no route through it to an
    ungoverned call, and nothing private is served.
    """
    for operation in governed_llm.descriptor.operation_names:
        assert getattr(governed_llm, operation) is not getattr(llm, operation)

    with pytest.raises(AttributeError, match="no private attribute"):
        governed_llm._client  # noqa: B018


def test_the_declaration_is_readable(governed_llm: GovernedPort) -> None:
    """Reading metadata is not an action: the descriptor is what governs."""
    assert governed_llm.port_id == "llm_provider"
    assert "complete" in governed_llm.descriptor.operation_names
    assert governed_llm.terms().provider == "Fake"


# --- The permitted path ----------------------------------------------------


@pytest.mark.asyncio
async def test_routine_work_runs_and_is_billed_at_what_it_cost(
    governed_llm: GovernedPort,
    llm: FakeLLM,
    audit: AuditChain,
    budget: BudgetGuard,
    completion: CompletionRequest,
) -> None:
    result = await governed_llm.complete(completion)

    assert result.text == "a considered answer"
    assert llm.calls == ["complete"]

    decisions = [event.decision for event in audit.events]
    assert decisions == [AuditDecision.ALLOWED, AuditDecision.EXECUTED]
    assert audit.events[-1].cost_usd == Decimal("0.03"), "billed at actual, not estimate"
    assert audit.events[-1].output_digest
    assert budget.spent("task", "task-1") == Decimal("0.03")
    audit.verify()


@pytest.mark.asyncio
async def test_a_free_operation_costs_nothing(
    governed_llm: GovernedPort, budget: BudgetGuard
) -> None:
    await governed_llm.count_tokens(
        TokenCountRequest(messages=(Message(role=Role.USER, content="hello"),))
    )
    assert budget.spent("global_daily", "2026-08-20") == Decimal("0")


@pytest.mark.asyncio
async def test_an_adapter_failure_is_recorded_and_costs_nothing(
    engine: PolicyEngine,
    token: CapabilityToken,
    audit: AuditChain,
    budget: BudgetGuard,
    completion: CompletionRequest,
) -> None:
    governed = GovernedPort(
        FakeLLM(fail=True), engine=engine, token=token, actor="research_analyst"
    )

    with pytest.raises(RuntimeError, match="the vendor timed out"):
        await governed.complete(completion)

    assert audit.events[-1].decision is AuditDecision.FAILED
    assert budget.reserved("global_daily", "2026-08-20") == Decimal("0")
    assert budget.spent("global_daily", "2026-08-20") == Decimal("0")


@pytest.mark.asyncio
async def test_a_port_outside_the_token_is_denied(
    engine: PolicyEngine, token: CapabilityToken, completion: CompletionRequest
) -> None:
    """The research token names three ports. Email is not one of them."""
    email = FakeEmail()
    governed = GovernedPort(
        email, engine=engine, token=token, actor="research_analyst"
    )

    with pytest.raises(PolicyDenied, match="not in scope"):
        await governed.list_threads(ListThreadsRequest())

    assert email.calls == []


@pytest.mark.asyncio
async def test_the_kill_switch_stops_permitted_work_too(
    governed_llm: GovernedPort,
    llm: FakeLLM,
    kill_switch: KillSwitch,
    completion: CompletionRequest,
) -> None:
    kill_switch.engage("cost anomaly under investigation")

    with pytest.raises(PolicyDenied, match="cost anomaly"):
        await governed_llm.complete(completion)

    assert llm.calls == []


# --- The approval path -----------------------------------------------------


@pytest.mark.asyncio
async def test_an_irreversible_send_waits_for_a_typed_approval(
    engine: PolicyEngine,
    issuer: TokenIssuer,
    gateway: ApprovalGateway,
    clock: FrozenClock,
) -> None:
    """The whole T3 ceremony, driven through the proxy a department holds."""
    email = FakeEmail()
    token = issuer.issue(
        subject="growth_lead",
        capabilities=frozenset(
            {
                Capability.OUTBOUND_MESSAGE,
                Capability.NETWORK_WRITE,
                Capability.NETWORK_READ,
                Capability.PERSONAL_DATA_READ,
            }
        ),
        port_ids=frozenset({"email_provider"}),
        max_tier=RiskTier.T3,
        budget_usd=Decimal("1.00"),
    )
    governed = GovernedPort(email, engine=engine, token=token, actor="growth_lead")
    payload = SendRequest(draft_id="draft-1", approval_id="pending")

    with pytest.raises(ApprovalRequired) as excinfo:
        await governed.send(payload)

    assert email.calls == [], "nothing is sent while a human is deciding"
    approval_id = excinfo.value.approval_id
    record = gateway.get(approval_id)
    assert record.tier is RiskTier.T3
    assert record.is_irreversible
    assert record.confirmation_phrase is not None

    gateway.approve(approval_id, confirmation=record.confirmation_phrase)
    clock.advance(gateway.cooling_off)

    result = await governed.with_approval(approval_id).send(payload)
    assert result.message_id == "message-1"
    assert email.calls == ["send"]


@pytest.mark.asyncio
async def test_an_approval_does_not_authorise_a_second_send(
    engine: PolicyEngine,
    issuer: TokenIssuer,
    gateway: ApprovalGateway,
    clock: FrozenClock,
) -> None:
    """One approval, one action. Otherwise 'send this email' becomes 'send email'."""
    email = FakeEmail()
    token = issuer.issue(
        subject="growth_lead",
        capabilities=frozenset(
            {
                Capability.OUTBOUND_MESSAGE,
                Capability.NETWORK_WRITE,
                Capability.PERSONAL_DATA_READ,
            }
        ),
        port_ids=frozenset({"email_provider"}),
        max_tier=RiskTier.T3,
        budget_usd=Decimal("1.00"),
    )
    governed = GovernedPort(email, engine=engine, token=token, actor="growth_lead")
    payload = SendRequest(draft_id="draft-1", approval_id="pending")

    with pytest.raises(ApprovalRequired) as excinfo:
        await governed.send(payload)
    approval_id = excinfo.value.approval_id
    record = gateway.get(approval_id)
    assert record.confirmation_phrase is not None
    gateway.approve(approval_id, confirmation=record.confirmation_phrase)
    clock.advance(gateway.cooling_off)

    await governed.with_approval(approval_id).send(payload)
    with pytest.raises(PolicyDenied):
        await governed.with_approval(approval_id).send(payload)

    assert email.calls == ["send"]


@pytest.mark.asyncio
async def test_a_session_of_mixed_outcomes_leaves_a_verifiable_history(
    governed_llm: GovernedPort,
    engine: PolicyEngine,
    issuer: TokenIssuer,
    audit: AuditChain,
    completion: CompletionRequest,
) -> None:
    await governed_llm.complete(completion)

    dangerous = GovernedPort(
        DangerousPort(),
        engine=engine,
        token=dangerous_token(issuer),
        actor="finance_analyst",
    )
    with pytest.raises(ProhibitedAction):
        await dangerous.wire_funds(SettlementRequest(supplier="ACME", amount_usd=Decimal("1")))

    await governed_llm.embed(EmbeddingRequest(texts=("a", "b")))

    audit.verify()
    assert [event.decision for event in audit.events] == [
        AuditDecision.ALLOWED,
        AuditDecision.EXECUTED,
        AuditDecision.PROHIBITED,
        AuditDecision.ALLOWED,
        AuditDecision.EXECUTED,
    ]
