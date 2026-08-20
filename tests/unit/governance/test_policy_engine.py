"""The policy engine — the composition of the layers.

The ordering is the design, so these tests assert the ordering as much as the
outcomes: the kill switch stops everything, prohibitions refuse without appeal,
classification decides the scrutiny, the token bounds the authority, a human
decides when the tier says so, and money is committed last.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest

from happy.core.capability import Capability
from happy.core.errors import ProhibitedAction
from happy.core.risk import RiskTier
from happy.core.terms import DataSourceMetadata
from happy.core.usage_policy import UsageIntent
from happy.governance.action import ActionRequest
from happy.governance.audit import AuditChain, AuditDecision
from happy.governance.budget_guard import BudgetGuard
from happy.governance.capability import CapabilityToken, TokenIssuer
from happy.governance.errors import ApprovalRequired, PolicyDenied
from happy.governance.gateway import ApprovalGateway
from happy.governance.kill_switch import KillSwitch
from happy.governance.policy import PolicyEngine, PolicyOutcome

if TYPE_CHECKING:
    from tests.conftest import FrozenClock


def action(**overrides: Any) -> ActionRequest:
    fields: dict[str, Any] = {
        "actor": "research_analyst",
        "port_id": "llm_provider",
        "operation": "complete",
        "capabilities": frozenset({Capability.LLM_INFERENCE}),
        "declared_tier": RiskTier.T1,
        "estimated_cost_usd": Decimal("0.25"),
        "venture_id": "venture-1",
        "input_digest": "digest-1",
    }
    fields.update(overrides)
    return ActionRequest(**fields)


@pytest.fixture
def publisher_token(issuer: TokenIssuer) -> CapabilityToken:
    """A token that reaches the tiers where a human is involved."""
    return issuer.issue(
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
        budget_usd=Decimal("5.00"),
    )


def outbound(**overrides: Any) -> ActionRequest:
    fields: dict[str, Any] = {
        "actor": "growth_lead",
        "port_id": "email_provider",
        "operation": "send",
        "capabilities": frozenset({Capability.OUTBOUND_MESSAGE}),
        "declared_tier": RiskTier.T2,
        "reversible": False,
        "externally_visible": True,
        "input_digest": "the-email",
    }
    fields.update(overrides)
    return ActionRequest(**fields)


def test_routine_work_is_allowed_and_audited(
    engine: PolicyEngine, token: CapabilityToken, audit: AuditChain
) -> None:
    decision = engine.evaluate(action(), token)

    assert decision.outcome is PolicyOutcome.ALLOW
    assert decision.tier is RiskTier.T1
    assert decision.reservation is not None
    assert audit.events[-1].decision is AuditDecision.ALLOWED


def test_a_prohibited_action_is_refused_before_anything_else(
    engine: PolicyEngine, token: CapabilityToken, audit: AuditChain, budget: BudgetGuard
) -> None:
    """No classification, no token check, no budget: a refusal, and a record."""
    decision = engine.evaluate(
        action(port_id="payment_provider", operation="transfer"), token
    )

    assert decision.outcome is PolicyOutcome.DENY
    assert decision.prohibited
    assert decision.rule_id == "port_declared_prohibition"
    assert audit.events[-1].decision is AuditDecision.PROHIBITED
    assert budget.reserved("global_daily", "2026-08-20") == Decimal("0")

    with pytest.raises(ProhibitedAction):
        decision.raise_if_denied()


def test_an_invented_operation_name_is_refused_by_the_word_rules(
    engine: PolicyEngine, token: CapabilityToken
) -> None:
    """The case the deny list is really for: a port that does not declare the
    prohibition, and an adapter that added a plausible-looking method."""
    decision = engine.evaluate(
        action(port_id="some_future_port", operation="wire_funds"), token
    )

    assert decision.prohibited
    assert decision.rule_id == "money_movement"


def test_the_kill_switch_stops_even_a_free_read(
    engine: PolicyEngine, token: CapabilityToken, kill_switch: KillSwitch
) -> None:
    """Fail closed means fail closed: no tier keeps running."""
    kill_switch.engage("the Chairman is investigating something")
    decision = engine.evaluate(
        action(
            operation="count_tokens",
            declared_tier=RiskTier.T0,
            estimated_cost_usd=Decimal("0"),
        ),
        token,
    )

    assert decision.outcome is PolicyOutcome.DENY
    assert "investigating" in decision.reason

    kill_switch.release("chairman", "all clear")
    assert engine.evaluate(action(), token).outcome is PolicyOutcome.ALLOW


def test_an_action_outside_the_token_is_denied(
    engine: PolicyEngine, token: CapabilityToken
) -> None:
    decision = engine.evaluate(
        action(port_id="email_provider", operation="draft"), token
    )

    assert decision.outcome is PolicyOutcome.DENY
    assert "not in scope" in decision.reason
    with pytest.raises(PolicyDenied):
        decision.raise_if_denied()


def test_an_expired_token_denies(
    engine: PolicyEngine, token: CapabilityToken, clock: FrozenClock
) -> None:
    clock.advance(timedelta(hours=2))
    decision = engine.evaluate(action(), token)

    assert decision.outcome is PolicyOutcome.DENY
    assert "expired" in decision.reason


def test_an_action_above_the_tokens_tier_is_denied(
    engine: PolicyEngine, token: CapabilityToken
) -> None:
    """Classification happens first, so the tier the token is judged against is
    the classified one, not the declared one."""
    decision = engine.evaluate(action(estimated_cost_usd=Decimal("1.50")), token)

    assert decision.outcome is PolicyOutcome.DENY
    assert "token reaches only T1" in decision.reason


def test_work_over_budget_is_denied_without_reaching_the_port(
    engine: PolicyEngine, token: CapabilityToken, budget: BudgetGuard
) -> None:
    for _ in range(12):
        engine.evaluate(action(), token)

    decision = engine.evaluate(action(), token)
    assert decision.outcome is PolicyOutcome.DENY
    assert "budget" in decision.reason


def test_a_t2_action_requires_approval_and_then_proceeds(
    engine: PolicyEngine,
    publisher_token: CapabilityToken,
    gateway: ApprovalGateway,
) -> None:
    request = outbound(declared_tier=RiskTier.T2, reversible=True, externally_visible=True)
    first = engine.evaluate(request, publisher_token)

    assert first.outcome is PolicyOutcome.REQUIRE_APPROVAL
    assert first.approval_id is not None
    assert first.reservation is None, "nothing is held while a human is deciding"
    with pytest.raises(ApprovalRequired):
        first.raise_if_denied()

    gateway.approve(first.approval_id)
    second = engine.evaluate(request, publisher_token, approval_id=first.approval_id)

    assert second.outcome is PolicyOutcome.ALLOW
    assert second.reservation is not None


def test_a_rejected_approval_denies_the_action(
    engine: PolicyEngine, publisher_token: CapabilityToken, gateway: ApprovalGateway
) -> None:
    request = outbound(declared_tier=RiskTier.T2, reversible=True)
    first = engine.evaluate(request, publisher_token)
    assert first.approval_id is not None
    gateway.reject(first.approval_id, "wrong prospect")

    second = engine.evaluate(request, publisher_token, approval_id=first.approval_id)
    assert second.outcome is PolicyOutcome.DENY


def test_an_approval_for_different_arguments_does_not_transfer(
    engine: PolicyEngine, publisher_token: CapabilityToken, gateway: ApprovalGateway
) -> None:
    approved_request = outbound(declared_tier=RiskTier.T2, reversible=True)
    first = engine.evaluate(approved_request, publisher_token)
    assert first.approval_id is not None
    gateway.approve(first.approval_id)

    other = outbound(declared_tier=RiskTier.T2, reversible=True, input_digest="another-email")
    decision = engine.evaluate(other, publisher_token, approval_id=first.approval_id)

    assert decision.outcome is PolicyOutcome.DENY
    assert "different action or different arguments" in decision.reason


def test_an_irreversible_action_reaches_t3_and_its_ceremony(
    engine: PolicyEngine,
    publisher_token: CapabilityToken,
    gateway: ApprovalGateway,
    clock: FrozenClock,
) -> None:
    request = outbound()
    first = engine.evaluate(request, publisher_token)

    assert first.tier is RiskTier.T3
    assert first.approval_id is not None
    record = gateway.get(first.approval_id)
    assert record.confirmation_phrase is not None

    gateway.approve(first.approval_id, confirmation=record.confirmation_phrase)
    too_soon = engine.evaluate(request, publisher_token, approval_id=first.approval_id)
    assert too_soon.outcome is PolicyOutcome.DENY

    clock.advance(gateway.cooling_off)
    assert (
        engine.evaluate(request, publisher_token, approval_id=first.approval_id).outcome
        is PolicyOutcome.ALLOW
    )


def test_settling_records_the_outcome_and_releases_the_hold(
    engine: PolicyEngine, token: CapabilityToken, budget: BudgetGuard, audit: AuditChain
) -> None:
    request = action()
    decision = engine.evaluate(request, token)
    engine.settle(decision, request, actual_cost_usd=Decimal("0.11"), output_digest="out")

    assert budget.reserved("global_daily", "2026-08-20") == Decimal("0")
    assert budget.spent("global_daily", "2026-08-20") == Decimal("0.11")
    assert audit.events[-1].decision is AuditDecision.EXECUTED
    assert audit.events[-1].output_digest == "out"


def test_a_failed_action_costs_nothing_by_default(
    engine: PolicyEngine, token: CapabilityToken, budget: BudgetGuard, audit: AuditChain
) -> None:
    request = action()
    decision = engine.evaluate(request, token)
    engine.settle(decision, request, error=RuntimeError("the vendor timed out"))

    assert budget.spent("global_daily", "2026-08-20") == Decimal("0")
    assert audit.events[-1].decision is AuditDecision.FAILED
    assert "the vendor timed out" in audit.events[-1].reason


def test_a_failure_that_still_cost_money_is_charged(
    engine: PolicyEngine, token: CapabilityToken, budget: BudgetGuard
) -> None:
    request = action()
    decision = engine.evaluate(request, token)
    engine.settle(
        decision, request, actual_cost_usd=Decimal("0.05"), error=RuntimeError("truncated")
    )

    assert budget.spent("global_daily", "2026-08-20") == Decimal("0.05")


def test_spending_past_a_limit_engages_the_kill_switch(
    engine: PolicyEngine,
    token: CapabilityToken,
    kill_switch: KillSwitch,
    audit: AuditChain,
) -> None:
    """Being wrong about cost once is forgivable. Continuing to act while the
    accounting is known to be wrong is not."""
    for _ in range(11):
        request = action()
        decision = engine.evaluate(request, token)
        if decision.allowed:
            engine.settle(decision, request, actual_cost_usd=Decimal("0.90"))

    assert kill_switch.engaged
    assert any(event.decision is AuditDecision.BUDGET_BREACH for event in audit.events)


def test_every_decision_leaves_a_verifiable_record(
    engine: PolicyEngine, token: CapabilityToken, audit: AuditChain
) -> None:
    engine.evaluate(action(), token)
    engine.evaluate(action(port_id="payment_provider", operation="payout"), token)
    engine.evaluate(action(port_id="crm_provider", operation="get_contact"), token)

    audit.verify()
    assert len(audit) == 3


def test_the_engine_is_the_single_entry_point_to_the_usage_policy(
    engine: PolicyEngine, yahoo_finance: DataSourceMetadata
) -> None:
    """The kernel and the domain must not disagree about what day it is."""
    decision = engine.evaluate_source_usage(yahoo_finance, UsageIntent.EXTERNAL_PUBLICATION)

    assert not decision.allowed
    assert decision.source_id == "Yahoo:Finance"
