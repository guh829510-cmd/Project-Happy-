"""Capability tokens.

The token is the answer to excessive agency: an agent that chains its way to an
unintended action still holds only what its token names. These tests cover both
halves of that — the grant cannot be forged or outlived, and it cannot be
stretched to cover a port, an operation, a capability or a tier it does not name.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from happy.core.capability import Capability
from happy.core.risk import RiskTier
from happy.governance.action import ActionRequest
from happy.governance.capability import CapabilityToken, TokenIssuer
from happy.governance.errors import CapabilityDenied, TokenInvalid

if TYPE_CHECKING:
    from tests.conftest import FrozenClock


def action(**overrides: object) -> ActionRequest:
    fields: dict[str, object] = {
        "actor": "research_analyst",
        "port_id": "llm_provider",
        "operation": "complete",
        "capabilities": frozenset({Capability.LLM_INFERENCE}),
        "venture_id": "venture-1",
    }
    fields.update(overrides)
    return ActionRequest(**fields)  # type: ignore[arg-type]


def test_a_short_secret_is_not_a_signing_key(clock: FrozenClock) -> None:
    with pytest.raises(ValueError, match="at least 32 bytes"):
        TokenIssuer(b"too-short", clock)


def test_a_token_cannot_grant_a_forbidden_capability(issuer: TokenIssuer) -> None:
    with pytest.raises(ValueError, match="forbidden capability"):
        issuer.issue(
            subject="agent",
            capabilities=frozenset({Capability.MONEY_MOVE}),
            port_ids=frozenset({"payment_provider"}),
        )


def test_a_token_cannot_grant_t4(issuer: TokenIssuer) -> None:
    """The absence that matters: no grant reaches the prohibited tier."""
    with pytest.raises(ValueError, match="no token may grant T4"):
        issuer.issue(
            subject="agent",
            capabilities=frozenset({Capability.NETWORK_READ}),
            port_ids=frozenset({"research_provider"}),
            max_tier=RiskTier.T4,
        )


def test_a_token_granting_no_port_is_refused(issuer: TokenIssuer) -> None:
    with pytest.raises(ValueError, match="authorises nothing"):
        issuer.issue(
            subject="agent",
            capabilities=frozenset({Capability.NETWORK_READ}),
            port_ids=frozenset(),
        )


def test_a_freshly_issued_token_verifies(issuer: TokenIssuer, token: CapabilityToken) -> None:
    issuer.verify(token)


def test_widening_a_token_invalidates_its_signature(
    issuer: TokenIssuer, token: CapabilityToken
) -> None:
    """The realistic attack is editing scope in the database, not forging HMAC."""
    widened = token.model_copy(
        update={"port_ids": token.port_ids | {"payment_provider"}}
    )
    with pytest.raises(TokenInvalid, match="signature does not match"):
        issuer.verify(widened)


def test_raising_a_tokens_tier_invalidates_its_signature(
    issuer: TokenIssuer, token: CapabilityToken
) -> None:
    escalated = token.model_copy(update={"max_tier": RiskTier.T3})
    with pytest.raises(TokenInvalid):
        issuer.verify(escalated)


def test_an_unsigned_token_is_invalid(issuer: TokenIssuer, token: CapabilityToken) -> None:
    with pytest.raises(TokenInvalid):
        issuer.verify(token.model_copy(update={"signature": ""}))


def test_a_token_expires(
    issuer: TokenIssuer, token: CapabilityToken, clock: FrozenClock
) -> None:
    clock.advance(timedelta(hours=1))
    with pytest.raises(TokenInvalid, match="expired"):
        issuer.verify(token)


def test_a_token_authorises_an_action_in_its_scope(
    issuer: TokenIssuer, token: CapabilityToken
) -> None:
    issuer.authorize(token, action(), RiskTier.T1)


def test_a_token_does_not_travel_between_agents(
    issuer: TokenIssuer, token: CapabilityToken
) -> None:
    with pytest.raises(CapabilityDenied, match="presented by"):
        issuer.authorize(token, action(actor="growth_lead"), RiskTier.T1)


def test_a_token_does_not_reach_an_unnamed_port(
    issuer: TokenIssuer, token: CapabilityToken
) -> None:
    with pytest.raises(CapabilityDenied, match="not in scope"):
        issuer.authorize(
            token,
            action(port_id="payment_provider", operation="get_balance"),
            RiskTier.T0,
        )


def test_a_token_may_be_narrowed_to_named_operations(issuer: TokenIssuer) -> None:
    narrow = issuer.issue(
        subject="research_analyst",
        capabilities=frozenset({Capability.LLM_INFERENCE}),
        port_ids=frozenset({"llm_provider"}),
        operations=frozenset({"count_tokens"}),
    )
    issuer.authorize(narrow, action(operation="count_tokens"), RiskTier.T0)
    with pytest.raises(CapabilityDenied, match="operation 'complete' is not in scope"):
        issuer.authorize(narrow, action(operation="complete"), RiskTier.T1)


def test_a_token_cannot_be_stretched_to_a_capability_it_lacks(
    issuer: TokenIssuer, token: CapabilityToken
) -> None:
    """Text in a scraped page can ask for anything; the grant does not move."""
    with pytest.raises(CapabilityDenied, match="requires capability"):
        issuer.authorize(
            token,
            action(capabilities=frozenset({Capability.NETWORK_WRITE})),
            RiskTier.T1,
        )


def test_a_token_cannot_reach_above_its_tier(
    issuer: TokenIssuer, token: CapabilityToken
) -> None:
    with pytest.raises(CapabilityDenied, match="token reaches only T1"):
        issuer.authorize(token, action(), RiskTier.T2)


def test_a_venture_scoped_token_stays_in_its_venture(
    issuer: TokenIssuer, token: CapabilityToken
) -> None:
    with pytest.raises(CapabilityDenied, match="scoped to venture"):
        issuer.authorize(token, action(venture_id="venture-2"), RiskTier.T1)


def test_authorisation_verifies_before_it_checks_scope(
    issuer: TokenIssuer, token: CapabilityToken, clock: FrozenClock
) -> None:
    """An expired token fails as invalid even when the action is in scope."""
    clock.advance(timedelta(days=1))
    with pytest.raises(TokenInvalid):
        issuer.authorize(token, action(), RiskTier.T1)


def test_signing_payload_excludes_the_signature(token: CapabilityToken) -> None:
    assert "signature" not in token.signing_payload()


def test_tokens_are_immutable(token: CapabilityToken) -> None:
    with pytest.raises(ValueError, match="frozen"):
        token.max_tier = RiskTier.T3  # type: ignore[misc]
