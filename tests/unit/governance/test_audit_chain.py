"""The hash-chained audit log.

What the chain must actually prove: that no entry has been altered, reordered,
inserted or removed since it was written. Each of those is a separate test,
because a chain that catches edits but not deletions is a chain that lets a bad
decision disappear.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from happy.core.risk import RiskTier
from happy.governance.action import ActionRequest
from happy.governance.audit import AuditChain, AuditDecision
from happy.governance.errors import AuditChainBroken
from happy.governance.hashing import GENESIS_HASH, redact_secrets

if TYPE_CHECKING:
    from tests.conftest import FrozenClock


def populate(chain: AuditChain, count: int = 3) -> None:
    for index in range(count):
        chain.record(AuditDecision.ALLOWED, f"entry {index}", actor="agent")


def test_an_empty_chain_verifies(audit: AuditChain) -> None:
    audit.verify()
    assert audit.head_hash == GENESIS_HASH


def test_entries_are_sequential_and_linked(audit: AuditChain) -> None:
    populate(audit, 3)
    audit.verify()

    events = audit.events
    assert [event.seq for event in events] == [0, 1, 2]
    assert events[0].prev_hash == GENESIS_HASH
    assert events[1].prev_hash == events[0].entry_hash
    assert events[2].prev_hash == events[1].entry_hash
    assert audit.head_hash == events[-1].entry_hash


def test_editing_an_entry_breaks_the_chain(audit: AuditChain, clock: FrozenClock) -> None:
    """Falsifying history to hide a bad decision is the threat this answers."""
    populate(audit, 3)
    events = list(audit.events)
    events[1] = events[1].model_copy(update={"reason": "nothing to see here"})

    with pytest.raises(AuditChainBroken) as excinfo:
        AuditChain(clock, events).verify()

    assert excinfo.value.seq == 1
    assert "does not match its content" in excinfo.value.reason


def test_removing_an_entry_breaks_the_chain(audit: AuditChain, clock: FrozenClock) -> None:
    populate(audit, 3)
    events = list(audit.events)
    del events[1]

    with pytest.raises(AuditChainBroken):
        AuditChain(clock, events).verify()


def test_reordering_entries_breaks_the_chain(audit: AuditChain, clock: FrozenClock) -> None:
    populate(audit, 3)
    events = list(audit.events)
    events[0], events[1] = events[1], events[0]

    with pytest.raises(AuditChainBroken):
        AuditChain(clock, events).verify()


def test_truncating_the_start_breaks_the_chain(audit: AuditChain, clock: FrozenClock) -> None:
    """A chain that does not begin at the genesis hash is missing its start."""
    populate(audit, 3)

    with pytest.raises(AuditChainBroken):
        AuditChain(clock, list(audit.events)[1:]).verify()


def test_refusals_are_recorded_as_carefully_as_approvals(audit: AuditChain) -> None:
    request = ActionRequest(
        actor="agent",
        port_id="payment_provider",
        operation="transfer",
        venture_id="venture-1",
        input_digest="abc123",
    )
    event = audit.record_action(
        request, AuditDecision.PROHIBITED, "money_movement", tier=RiskTier.T4
    )

    assert event.decision is AuditDecision.PROHIBITED
    assert event.actor == "agent"
    assert event.port_id == "payment_provider"
    assert event.operation == "transfer"
    assert event.tier is RiskTier.T4
    assert event.input_digest == "abc123"
    audit.verify()


def test_an_entry_carries_what_repudiation_needs(audit: AuditChain) -> None:
    """Actor, token, tier, cost and an input digest — enough to answer 'who
    authorised this, under what authority, and what did it cost?'"""
    request = ActionRequest(
        actor="research_analyst",
        port_id="llm_provider",
        operation="complete",
        estimated_cost_usd=Decimal("0.25"),
        task_id="task-9",
        input_digest="digest-of-inputs",
    )
    event = audit.record_action(
        request,
        AuditDecision.EXECUTED,
        "completed",
        tier=RiskTier.T1,
        token_id="token-1",
        output_digest="digest-of-output",
    )

    assert event.token_id == "token-1"
    assert event.task_id == "task-9"
    assert event.cost_usd == Decimal("0.25")
    assert event.output_digest == "digest-of-output"


def test_secrets_are_redacted_before_they_are_written(audit: AuditChain) -> None:
    """The audit log is the artifact most likely to be exported. It must be
    safe to hand to an accountant."""
    event = audit.record(
        AuditDecision.FAILED, "auth failed for key sk-abcdefghijklmnop1234"
    )

    assert "sk-abcdefghijklmnop1234" not in event.reason
    assert "[redacted]" in event.reason


def test_redaction_leaves_ordinary_text_alone() -> None:
    assert redact_secrets("no credentials here") == "no credentials here"


def test_entries_are_immutable(audit: AuditChain) -> None:
    populate(audit, 1)
    with pytest.raises(ValueError, match="frozen"):
        audit.events[0].reason = "edited"  # type: ignore[misc]
