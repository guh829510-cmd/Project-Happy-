"""Risk classification.

The property that matters most is the one-way ratchet: every rule may raise a
tier and none may lower one. If that holds, anything that influences an input —
a cost estimate, a model's opinion, a description written by an adapter — can
make the system more cautious but never less.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from happy.core.capability import Capability
from happy.core.ports import PORT_REGISTRY
from happy.core.risk import RiskTier
from happy.governance.action import ActionRequest
from happy.governance.classifier import Classification, ClassifierConfig, RiskClassifier


@pytest.fixture
def classifier() -> RiskClassifier:
    return RiskClassifier(
        ClassifierConfig(approval_cost_usd=Decimal("1.00"), high_cost_usd=Decimal("20.00"))
    )


def action(**overrides: Any) -> ActionRequest:
    fields: dict[str, Any] = {
        "actor": "agent",
        "port_id": "research_provider",
        "operation": "search",
        "declared_tier": RiskTier.T0,
    }
    fields.update(overrides)
    return ActionRequest(**fields)


def test_a_declared_tier_is_the_floor(classifier: RiskClassifier) -> None:
    result = classifier.classify(action(declared_tier=RiskTier.T2))
    assert result.tier is RiskTier.T2
    assert result.reasons[0].startswith("T2: declared by")


def test_classification_never_drops_below_the_declaration(classifier: RiskClassifier) -> None:
    """A free, reversible, internal T3 stays T3. Nothing argues a tier down."""
    result = classifier.classify(
        action(declared_tier=RiskTier.T3, estimated_cost_usd=Decimal("0"), reversible=True)
    )
    assert result.tier is RiskTier.T3


def test_undeclared_operations_are_treated_as_the_highest_applicable_tier(
    classifier: RiskClassifier,
) -> None:
    """Deny by default: an unassessed action is not a cheap action."""
    result = classifier.classify(action(declared=False, declared_tier=RiskTier.T0))
    assert result.tier is RiskTier.T3
    assert any("not declared by any port" in reason for reason in result.reasons)


def test_external_visibility_requires_a_human(classifier: RiskClassifier) -> None:
    result = classifier.classify(action(externally_visible=True))
    assert result.tier is RiskTier.T2
    assert result.tier.requires_approval


def test_irreversibility_requires_the_ceremony(classifier: RiskClassifier) -> None:
    result = classifier.classify(action(reversible=False))
    assert result.tier is RiskTier.T3


@pytest.mark.parametrize(
    ("cost", "expected"),
    [
        (Decimal("0"), RiskTier.T0),
        (Decimal("0.01"), RiskTier.T1),
        (Decimal("0.99"), RiskTier.T1),
        (Decimal("1.00"), RiskTier.T2),
        (Decimal("19.99"), RiskTier.T2),
        (Decimal("20.00"), RiskTier.T3),
        (Decimal("500"), RiskTier.T3),
    ],
)
def test_cost_thresholds_are_inclusive(
    classifier: RiskClassifier, cost: Decimal, expected: RiskTier
) -> None:
    """At the threshold, not merely past it — a limit you can sit exactly on is
    a limit somebody will sit exactly on."""
    assert classifier.classify(action(estimated_cost_usd=cost)).tier is expected


def test_money_move_capability_classifies_as_prohibited(classifier: RiskClassifier) -> None:
    """Unreachable through a port, asserted anyway: a hand-built request that
    claims this capability must classify T4 rather than merely T3."""
    result = classifier.classify(
        action(capabilities=frozenset({Capability.MONEY_MOVE}))
    )
    assert result.tier is RiskTier.T4
    assert result.tier.is_prohibited


@pytest.mark.parametrize(
    ("capability", "expected"),
    [
        (Capability.EXTERNAL_PUBLISH, RiskTier.T2),
        (Capability.OUTBOUND_MESSAGE, RiskTier.T2),
        (Capability.PERSONAL_DATA_WRITE, RiskTier.T2),
        (Capability.SECRET_READ, RiskTier.T2),
        (Capability.DEPLOY_PRODUCTION, RiskTier.T2),
        (Capability.REPO_WRITE, RiskTier.T1),
        (Capability.PROCESS_EXECUTE, RiskTier.T1),
        (Capability.NETWORK_WRITE, RiskTier.T1),
        (Capability.NETWORK_READ, RiskTier.T0),
        (Capability.FILESYSTEM_READ, RiskTier.T0),
    ],
)
def test_capabilities_carry_their_own_floor(
    classifier: RiskClassifier, capability: Capability, expected: RiskTier
) -> None:
    result = classifier.classify(action(capabilities=frozenset({capability})))
    assert result.tier is expected


def test_reading_personal_data_does_not_queue_an_approval(
    classifier: RiskClassifier,
) -> None:
    """Approval fatigue is a security risk: reading one's own CRM is T1, and
    only writing personal data reaches the queue."""
    read = classifier.classify(
        action(
            port_id="crm_provider",
            operation="get_contact",
            handles_personal_data=True,
            capabilities=frozenset({Capability.PERSONAL_DATA_READ}),
        )
    )
    write = classifier.classify(
        action(
            port_id="crm_provider",
            operation="upsert_contact",
            handles_personal_data=True,
            capabilities=frozenset({Capability.PERSONAL_DATA_WRITE}),
        )
    )
    assert read.tier is RiskTier.T1
    assert not read.tier.requires_approval
    assert write.tier is RiskTier.T2


def test_rollback_is_not_harder_than_the_deploy_it_undoes(
    classifier: RiskClassifier,
) -> None:
    """A cooling-off period in front of incident recovery makes outages longer.

    Both need a human; only the irreversible one needs typed confirmation.
    """
    deployment = PORT_REGISTRY["deployment_provider"].descriptor
    rollback = classifier.classify(
        ActionRequest.from_operation(
            actor="agent", descriptor=deployment, operation="rollback"
        )
    )
    deploy = classifier.classify(
        ActionRequest.from_operation(
            actor="agent", descriptor=deployment, operation="deploy_production"
        )
    )
    assert rollback.tier is RiskTier.T2
    assert deploy.tier is RiskTier.T3
    assert rollback.tier < deploy.tier


def test_reasons_accumulate_in_the_order_they_were_applied(
    classifier: RiskClassifier,
) -> None:
    """An approval request that cannot say why is not informed consent."""
    result = classifier.classify(
        action(
            declared_tier=RiskTier.T1,
            externally_visible=True,
            reversible=False,
            estimated_cost_usd=Decimal("25"),
        )
    )
    assert result.tier is RiskTier.T3
    assert len(result.reasons) >= 3
    assert any("cannot be undone" in reason for reason in result.reasons)
    assert any("visible outside" in reason for reason in result.reasons)


def test_an_advisory_may_raise_a_tier(classifier: RiskClassifier) -> None:
    base = classifier.classify(action(declared_tier=RiskTier.T1))
    raised = classifier.with_advisory(base, RiskTier.T3, "the model judged this novel")
    assert raised.tier is RiskTier.T3
    assert any("advisory" in reason for reason in raised.reasons)


def test_an_advisory_cannot_lower_a_tier(classifier: RiskClassifier) -> None:
    """The only route by which an LLM affects classification is upward.

    A model talked into calling an irreversible action routine changes nothing.
    """
    base = classifier.classify(action(declared_tier=RiskTier.T3))
    lowered = classifier.with_advisory(base, RiskTier.T0, "the model said it is fine")
    assert lowered.tier is RiskTier.T3
    assert lowered == base


def test_raised_to_discards_the_reason_of_a_rule_that_would_lower() -> None:
    """A lenient reason must not survive as apparent justification."""
    start = Classification(tier=RiskTier.T2, reasons=("T2: externally visible",))
    assert start.raised_to(RiskTier.T0, "looks harmless") == start
