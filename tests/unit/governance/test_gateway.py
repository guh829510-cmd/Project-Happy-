"""The approval gateway.

Every principle in §8.3 of the development plan is a test here. The one worth
reading first is `test_the_gateway_cannot_file_a_t4_approval`: the guarantee is
an absence, and an absence is only real if something asserts it.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest

from happy.core.errors import ProhibitedAction
from happy.core.risk import RiskTier
from happy.governance.action import ActionRequest
from happy.governance.audit import AuditChain, AuditDecision
from happy.governance.classifier import Classification
from happy.governance.errors import ApprovalInvalid
from happy.governance.gateway import ApprovalGateway, ApprovalStatus

if TYPE_CHECKING:
    from tests.conftest import FrozenClock


def action(**overrides: Any) -> ActionRequest:
    fields: dict[str, Any] = {
        "actor": "growth_lead",
        "port_id": "email_provider",
        "operation": "send",
        "summary": "Send the intro email to a prospect.",
        "reversible": False,
        "externally_visible": True,
        "input_digest": "digest-1",
    }
    fields.update(overrides)
    return ActionRequest(**fields)


def classification(tier: RiskTier) -> Classification:
    return Classification(tier=tier, reasons=(f"{tier.name}: because the test says so",))


def submit(gateway: ApprovalGateway, tier: RiskTier = RiskTier.T2, **overrides: Any) -> Any:
    return gateway.submit(action(**overrides), classification(tier))


def test_the_gateway_cannot_file_a_t4_approval(gateway: ApprovalGateway) -> None:
    """There is no code path that approves a prohibited action.

    Not a policy, not a permission check — the queue cannot represent one, so
    no interface can ever render it with an Approve button.
    """
    with pytest.raises(ProhibitedAction):
        gateway.submit(action(operation="transfer"), classification(RiskTier.T4))

    assert gateway.pending() == ()


def test_routine_work_is_not_filed(gateway: ApprovalGateway) -> None:
    """Approval fatigue is a security risk. T0 and T1 never reach the queue."""
    for tier in (RiskTier.T0, RiskTier.T1):
        with pytest.raises(ValueError, match="executes without approval"):
            gateway.submit(action(), classification(tier))


def test_a_submitted_request_is_pending_and_audited(
    gateway: ApprovalGateway, audit: AuditChain
) -> None:
    record = submit(gateway)

    assert record.status is ApprovalStatus.PENDING
    assert gateway.pending() == (record,)
    assert audit.events[-1].decision is AuditDecision.APPROVAL_REQUIRED
    assert audit.events[-1].approval_id == record.approval_id


def test_the_record_carries_what_informed_consent_needs(gateway: ApprovalGateway) -> None:
    record = submit(gateway, RiskTier.T3, estimated_cost_usd=Decimal("12.50"))

    assert record.summary.startswith("email_provider.send")
    assert record.is_irreversible
    assert record.request.estimated_cost_usd == Decimal("12.50")
    assert record.reasons


def test_t2_needs_no_typed_confirmation(gateway: ApprovalGateway) -> None:
    record = gateway.approve(submit(gateway, RiskTier.T2).approval_id)
    assert record.status is ApprovalStatus.APPROVED


def test_t3_requires_the_phrase_typed_exactly(gateway: ApprovalGateway) -> None:
    """Clicking is too cheap for an irreversible action."""
    record = submit(gateway, RiskTier.T3)
    assert record.confirmation_phrase == f"APPROVE {record.approval_id}"

    with pytest.raises(ApprovalInvalid, match="confirmation phrase"):
        gateway.approve(record.approval_id)
    with pytest.raises(ApprovalInvalid):
        gateway.approve(record.approval_id, confirmation="approve")

    approved = gateway.approve(record.approval_id, confirmation=record.confirmation_phrase)
    assert approved.status is ApprovalStatus.APPROVED


def test_t3_cannot_be_used_until_the_cooling_off_has_passed(
    gateway: ApprovalGateway, clock: FrozenClock
) -> None:
    """A minimum delay between request and executable approval, to defeat
    momentary rubber-stamping."""
    request = action()
    record = gateway.submit(request, classification(RiskTier.T3))
    gateway.approve(record.approval_id, confirmation=record.confirmation_phrase)

    with pytest.raises(ApprovalInvalid, match="cooling-off"):
        gateway.consume(record.approval_id, request)

    clock.advance(gateway.cooling_off)
    assert gateway.consume(record.approval_id, request).status is ApprovalStatus.CONSUMED


def test_t2_is_executable_immediately(gateway: ApprovalGateway) -> None:
    request = action()
    record = gateway.submit(request, classification(RiskTier.T2))
    gateway.approve(record.approval_id)

    assert gateway.consume(record.approval_id, request).status is ApprovalStatus.CONSUMED


def test_t3_approvals_cannot_be_batched(gateway: ApprovalGateway) -> None:
    """Bulk-approving irreversible actions is the behaviour the tier exists to
    prevent, so the whole call is refused rather than partially applied."""
    first = submit(gateway, RiskTier.T2, input_digest="a")
    second = submit(gateway, RiskTier.T3, input_digest="b")

    with pytest.raises(ApprovalInvalid, match="cannot be batched"):
        gateway.approve_many((first.approval_id, second.approval_id))

    assert gateway.get(first.approval_id).status is ApprovalStatus.PENDING


def test_t2_approvals_may_be_batched(gateway: ApprovalGateway) -> None:
    first = submit(gateway, RiskTier.T2, input_digest="a")
    second = submit(gateway, RiskTier.T2, input_digest="b")

    approved = gateway.approve_many((first.approval_id, second.approval_id))
    assert [record.status for record in approved] == [ApprovalStatus.APPROVED] * 2


def test_an_unanswered_request_expires_as_denied(
    gateway: ApprovalGateway, clock: FrozenClock, audit: AuditChain
) -> None:
    """Silence is not consent."""
    record = submit(gateway)
    clock.advance(timedelta(hours=13))

    expired = gateway.get(record.approval_id)
    assert expired.status is ApprovalStatus.EXPIRED
    assert gateway.pending() == ()
    assert audit.events[-1].decision is AuditDecision.APPROVAL_EXPIRED

    with pytest.raises(ApprovalInvalid, match="already expired"):
        gateway.approve(record.approval_id)


def test_an_approval_works_exactly_once(gateway: ApprovalGateway) -> None:
    request = action()
    record = gateway.submit(request, classification(RiskTier.T2))
    gateway.approve(record.approval_id)
    gateway.consume(record.approval_id, request)

    with pytest.raises(ApprovalInvalid, match="not approved"):
        gateway.consume(record.approval_id, request)


def test_an_approval_is_bound_to_the_arguments_it_was_shown_with(
    gateway: ApprovalGateway,
) -> None:
    """Approving one email must not authorise a different one."""
    request = action(input_digest="the-email-that-was-reviewed")
    record = gateway.submit(request, classification(RiskTier.T2))
    gateway.approve(record.approval_id)

    with pytest.raises(ApprovalInvalid, match="different action or different arguments"):
        gateway.consume(record.approval_id, action(input_digest="a-different-email"))


def test_a_rejected_request_cannot_be_approved_afterwards(
    gateway: ApprovalGateway, audit: AuditChain
) -> None:
    record = submit(gateway)
    gateway.reject(record.approval_id, "not now")

    assert audit.events[-1].decision is AuditDecision.APPROVAL_REJECTED
    with pytest.raises(ApprovalInvalid, match="decisions are final"):
        gateway.approve(record.approval_id)


def test_a_rejected_approval_cannot_be_consumed(gateway: ApprovalGateway) -> None:
    request = action()
    record = gateway.submit(request, classification(RiskTier.T2))
    gateway.reject(record.approval_id, "no")

    with pytest.raises(ApprovalInvalid, match="not approved"):
        gateway.consume(record.approval_id, request)


def test_an_approval_that_expires_after_being_granted_is_not_usable(
    gateway: ApprovalGateway, clock: FrozenClock
) -> None:
    request = action()
    record = gateway.submit(request, classification(RiskTier.T2))
    gateway.approve(record.approval_id)
    clock.advance(timedelta(hours=13))

    with pytest.raises(ApprovalInvalid, match="expired"):
        gateway.consume(record.approval_id, request)


def test_pending_is_ordered_oldest_first(
    gateway: ApprovalGateway, clock: FrozenClock
) -> None:
    first = submit(gateway, input_digest="a")
    clock.advance(timedelta(minutes=5))
    second = submit(gateway, input_digest="b")

    assert [record.approval_id for record in gateway.pending()] == [
        first.approval_id,
        second.approval_id,
    ]
