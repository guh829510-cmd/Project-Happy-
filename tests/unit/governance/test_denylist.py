"""The T4 deny list.

Two failure modes matter and both are tested here. **Under-blocking** — an
action that should be refused gets through — is checked against every
prohibition in the plan, and against plausible operation names an adapter might
invent later. **Over-blocking** is checked too: a deny list that refuses
ordinary work gets loosened by whoever is on call, and a loosened deny list
protects nobody.
"""

from __future__ import annotations

import pytest

from happy.core.capability import Capability
from happy.core.errors import ProhibitedAction
from happy.core.ports import PORT_REGISTRY
from happy.governance import denylist
from happy.governance.action import ActionRequest

PLAN_PROHIBITIONS = {
    "money_movement",
    "contract_execution",
    "borrowing_and_credit",
    "securities_issuance",
    "autonomous_trading",
    "regulatory_filing",
    "entity_and_representation",
    "financial_rail_access",
    "irreversible_destruction",
}


def request_for(operation: str, port_id: str = "some_port", **kwargs: object) -> ActionRequest:
    return ActionRequest(actor="agent", port_id=port_id, operation=operation, **kwargs)


def test_every_prohibition_in_the_plan_has_a_rule() -> None:
    """§8.1 of the development plan maps onto rule ids, one for one."""
    assert PLAN_PROHIBITIONS <= denylist.RULE_IDS


def test_rule_ids_are_unique() -> None:
    ids = [rule.rule_id for rule in denylist.T4_DENY_LIST]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize(
    ("operation", "expected_rule"),
    [
        ("transfer_funds", "money_movement"),
        ("send_payout", "money_movement"),
        ("issue_refund", "money_movement"),
        ("charge_customer", "money_movement"),
        ("initiate_debit", "money_movement"),
        ("wire_to_supplier", "money_movement"),
        ("sign_contract", "contract_execution"),
        ("accept_terms", "contract_execution"),
        ("apply_for_credit", "borrowing_and_credit"),
        ("take_out_loan", "borrowing_and_credit"),
        ("issue_shares", "securities_issuance"),
        ("place_order", "autonomous_trading"),
        ("execute_trade", "autonomous_trading"),
        ("connect_brokerage", "autonomous_trading"),
        ("rebalance_portfolio", "autonomous_trading"),
        ("submit_tax_return", "regulatory_filing"),
        ("make_regulatory_filing", "regulatory_filing"),
        ("incorporate_company", "entity_and_representation"),
        ("act_on_behalf_of", "entity_and_representation"),
        ("open_bank_account", "financial_rail_access"),
        ("purge_history", "irreversible_destruction"),
        ("force_push", "irreversible_destruction"),
        ("bypass_review", "governance_bypass"),
        ("impersonate_founder", "governance_bypass"),
        ("solve_captcha", "governance_bypass"),
    ],
)
def test_invented_operation_names_are_refused(operation: str, expected_rule: str) -> None:
    """The rules catch operations no port declares — the realistic future case.

    A port cannot declare `Capability.MONEY_MOVE` at all, so the way a
    prohibited action would actually appear is an adapter adding a
    plausible-looking method later. These are those names.
    """
    rule = denylist.evaluate(request_for(operation))
    assert rule is not None, f"{operation} was not refused"
    assert rule.rule_id == expected_rule


def test_money_move_capability_is_refused_however_it_is_named() -> None:
    """Naming is a heuristic; the capability is not."""
    request = request_for("do_a_favour", capabilities=frozenset({Capability.MONEY_MOVE}))
    rule = denylist.evaluate(request)
    assert rule is not None
    assert rule.rule_id == "money_movement"


@pytest.mark.parametrize(
    "capabilities",
    [
        frozenset({Capability.SECRET_READ, Capability.EXTERNAL_PUBLISH}),
        frozenset({Capability.SECRET_READ, Capability.OUTBOUND_MESSAGE}),
        frozenset({Capability.SECRET_READ, Capability.NETWORK_WRITE}),
    ],
)
def test_reading_a_secret_while_holding_an_outward_channel_is_refused(
    capabilities: frozenset[Capability],
) -> None:
    """Exfiltration is a shape, not a name: a read plus a way out."""
    rule = denylist.evaluate(request_for("summarise", capabilities=capabilities))
    assert rule is not None
    assert rule.rule_id == "credential_exfiltration"


def test_reading_a_secret_alone_is_ordinary() -> None:
    """An adapter reading its own API key must not be a T4 event."""
    request = request_for("call_api", capabilities=frozenset({Capability.SECRET_READ}))
    assert denylist.evaluate(request) is None


@pytest.mark.parametrize(
    ("port_id", "operation"),
    [
        (port_id, operation)
        for port_id, port in sorted(PORT_REGISTRY.items())
        for operation in sorted(port.descriptor.operation_names)
    ],
)
def test_no_declared_operation_is_refused(port_id: str, operation: str) -> None:
    """Over-blocking check: every callable operation of every port survives.

    `complete`, `read_file` and `list_transactions` all contain fragments of
    prohibited words. Whole-word matching is what keeps them callable.
    """
    descriptor = PORT_REGISTRY[port_id].descriptor
    request = ActionRequest.from_operation(
        actor="agent", descriptor=descriptor, operation=operation
    )
    assert denylist.evaluate(request) is None


@pytest.mark.parametrize(
    ("port_id", "operation"),
    [
        (port_id, operation)
        for port_id, port in sorted(PORT_REGISTRY.items())
        for operation in sorted(port.descriptor.prohibited_names)
    ],
)
def test_every_port_declared_prohibition_is_refused(port_id: str, operation: str) -> None:
    """The kernel repeats each port's own refusal independently."""
    rule = denylist.evaluate(request_for(operation, port_id=port_id))
    assert rule is not None


def test_port_declaration_is_honoured_for_unregistered_ports() -> None:
    """A port outside the registry still gets its declaration enforced."""
    request = request_for("harmless_sounding_name", port_id="not_registered")
    assert denylist.evaluate(request) is None

    rule = denylist.evaluate(
        request, prohibited_names=frozenset({"harmless_sounding_name"})
    )
    assert rule is not None
    assert rule.rule_id == "port_declared_prohibition"


def test_assert_permitted_raises_with_the_rule_in_the_message() -> None:
    with pytest.raises(ProhibitedAction) as excinfo:
        denylist.assert_permitted(request_for("transfer_funds"))

    assert "money_movement" in str(excinfo.value)
    assert excinfo.value.action == "some_port.transfer_funds"


def test_prohibited_action_is_not_a_port_error() -> None:
    """A refusal must not be swallowed by generic adapter error handling."""
    from happy.core.errors import PortError

    assert not issubclass(ProhibitedAction, PortError)
