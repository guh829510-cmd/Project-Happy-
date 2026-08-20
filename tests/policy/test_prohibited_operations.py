"""Adversarial tests: the system must be unable to do certain things.

These assert absence, which is the only kind of guarantee worth having here.
A prohibited operation that merely raises at runtime is a bug away from being
callable; a prohibited operation with no method cannot be called at all.

Per the testing strategy, a failure in this module blocks merge.
"""

from __future__ import annotations

import pytest

from happy.core.capability import Capability
from happy.core.ports import PORT_REGISTRY
from happy.core.ports.base import (
    OperationSpec,
    PortInput,
    PortOutput,
    ProhibitedOperationSpec,
)
from happy.core.risk import RiskTier

pytestmark = pytest.mark.policy

PORT_IDS = sorted(PORT_REGISTRY)

MONEY_MOVING_NAMES = frozenset(
    {
        "transfer",
        "payout",
        "charge",
        "refund",
        "debit",
        "credit",
        "withdraw",
        "deposit",
        "send_money",
        "initiate_debit",
        "create_payment_method",
        "issue_invoice",
        "open_credit_line",
        "wire",
        "ach",
        "settle",
    }
)

TRADING_NAMES = frozenset(
    {
        "place_order",
        "execute_trade",
        "submit_order",
        "cancel_order",
        "trade",
        "buy",
        "sell",
        "short",
        "rebalance_portfolio",
        "connect_brokerage",
    }
)


@pytest.mark.parametrize("port_id", PORT_IDS)
def test_prohibited_operations_have_no_method(port_id: str) -> None:
    """The structural guarantee. An adapter cannot implement what is not declared."""
    cls = PORT_REGISTRY[port_id]
    for prohibited in cls.descriptor.prohibited_operations:
        assert not hasattr(cls, prohibited.name), (
            f"{cls.__name__} has an attribute for prohibited operation "
            f"{prohibited.name!r}; it must have none"
        )


@pytest.mark.parametrize("port_id", PORT_IDS)
def test_prohibited_operations_are_t4(port_id: str) -> None:
    for prohibited in PORT_REGISTRY[port_id].descriptor.prohibited_operations:
        assert prohibited.risk_tier is RiskTier.T4
        assert prohibited.reason, "a prohibition must state its reason"


@pytest.mark.parametrize("port_id", PORT_IDS)
def test_no_port_can_move_money(port_id: str) -> None:
    """The central constraint, asserted three ways."""
    cls = PORT_REGISTRY[port_id]
    d = cls.descriptor

    assert Capability.MONEY_MOVE not in d.capabilities

    for name in MONEY_MOVING_NAMES:
        assert name not in d.operation_names, f"{port_id} declares {name!r} callable"
        assert not hasattr(cls, name), f"{port_id} has a {name!r} attribute"


@pytest.mark.parametrize("port_id", PORT_IDS)
def test_no_port_can_trade(port_id: str) -> None:
    """Finding 4: a research system grew order execution in one release. Not here."""
    cls = PORT_REGISTRY[port_id]
    for name in TRADING_NAMES:
        assert name not in cls.descriptor.operation_names
        assert not hasattr(cls, name)


def test_payment_port_is_read_only_by_construction() -> None:
    """The most constrained port in the system, checked exhaustively."""
    cls = PORT_REGISTRY["payment_provider"]
    d = cls.descriptor

    assert Capability.MONEY_READ in d.capabilities
    assert Capability.MONEY_MOVE not in d.capabilities

    # Every callable operation is a read, except the ledger write, which has no
    # outward effect at all.
    for op in d.operations:
        if op.name == "record_manual_entry":
            assert op.capabilities == frozenset({Capability.MONEY_READ}), (
                "recording a manual entry must not touch the network"
            )
            assert not op.externally_visible
        else:
            assert op.risk_tier is RiskTier.T0
            assert op.idempotent

    assert d.auth.supports_read_only_credential, (
        "a read-only credential must be possible for this port"
    )
    assert len(d.prohibited_operations) >= 6


def test_browser_cannot_interact_or_authenticate() -> None:
    cls = PORT_REGISTRY["browser"]
    for name in (
        "interact",
        "authenticate",
        "submit_form",
        "complete_purchase",
        "solve_captcha",
    ):
        assert name in cls.descriptor.prohibited_names
        assert not hasattr(cls, name)


def test_git_cannot_merge_or_rewrite_history() -> None:
    cls = PORT_REGISTRY["git_provider"]
    for name in (
        "merge_pull_request",
        "force_push",
        "delete_branch",
        "push_to_default_branch",
    ):
        assert name in cls.descriptor.prohibited_names
        assert not hasattr(cls, name)


def test_code_executor_cannot_reach_the_network() -> None:
    """Generated code plus network is the shortest path to exfiltration."""
    cls = PORT_REGISTRY["code_executor"]
    assert "run_with_network" in cls.descriptor.prohibited_names
    assert not hasattr(cls, "run_with_network")
    for op in cls.descriptor.operations:
        assert Capability.NETWORK_READ not in op.capabilities
        assert Capability.NETWORK_WRITE not in op.capabilities


def test_email_send_requires_an_approval_id_in_its_type() -> None:
    """The approval requirement is in the schema, not in a convention."""
    from happy.core.ports.email import SendRequest

    assert "approval_id" in SendRequest.model_fields
    assert SendRequest.model_fields["approval_id"].is_required()


def test_production_deploy_requires_approval_and_rollback_in_its_type() -> None:
    from happy.core.ports.deployment import DeployProductionRequest

    fields = DeployProductionRequest.model_fields
    assert fields["approval_id"].is_required()
    assert fields["rollback_ref"].is_required(), (
        "a production deploy without a rollback path must not be expressible"
    )


def test_rollback_is_never_harder_than_deploying() -> None:
    """Recovering from a mistake must not cost more than making one."""
    d = PORT_REGISTRY["deployment_provider"].descriptor
    assert d.operation("rollback").risk_tier <= d.operation("deploy_production").risk_tier


class TestSpecRejectsUnsafeDeclarations:
    """The invariants are enforced at construction, not only reviewed."""

    def _models(self) -> tuple[type[PortInput], type[PortOutput]]:
        class In(PortInput):
            pass

        class Out(PortOutput):
            pass

        return In, Out

    def test_rejects_money_move_capability(self) -> None:
        In, Out = self._models()
        with pytest.raises(ValueError, match="forbidden capability"):
            OperationSpec(
                name="x",
                summary="",
                risk_tier=RiskTier.T1,
                capabilities=frozenset({Capability.MONEY_MOVE}),
                input_model=In,
                output_model=Out,
            )

    def test_rejects_callable_t4_operation(self) -> None:
        In, Out = self._models()
        with pytest.raises(ValueError, match="declared T4"):
            OperationSpec(
                name="x",
                summary="",
                risk_tier=RiskTier.T4,
                capabilities=frozenset(),
                input_model=In,
                output_model=Out,
            )

    def test_rejects_auto_executable_external_visibility(self) -> None:
        In, Out = self._models()
        with pytest.raises(ValueError, match="externally visible"):
            OperationSpec(
                name="x",
                summary="",
                risk_tier=RiskTier.T1,
                capabilities=frozenset(),
                input_model=In,
                output_model=Out,
                externally_visible=True,
            )

    def test_rejects_auto_executable_irreversible_action(self) -> None:
        In, Out = self._models()
        with pytest.raises(ValueError, match="irreversible"):
            OperationSpec(
                name="x",
                summary="",
                risk_tier=RiskTier.T1,
                capabilities=frozenset(),
                input_model=In,
                output_model=Out,
                reversible=False,
            )

    def test_rejects_non_t4_prohibition(self) -> None:
        with pytest.raises(ValueError, match="must be T4"):
            ProhibitedOperationSpec(name="x", reason="y", risk_tier=RiskTier.T2)


def test_risk_tiers_cannot_be_lowered() -> None:
    """There is deliberately no API for lowering a tier."""
    assert RiskTier.T1.raised_to(RiskTier.T3) is RiskTier.T3
    assert RiskTier.T3.raised_to(RiskTier.T1) is RiskTier.T3
    assert not hasattr(RiskTier.T3, "lowered_to")


def test_t4_has_no_approval_path() -> None:
    assert RiskTier.T4.is_prohibited
    assert not RiskTier.T4.requires_approval
    assert not RiskTier.T4.auto_executable
