"""Risk tiers, capabilities and provenance."""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from happy.core.capability import FORBIDDEN_CAPABILITIES, Capability
from happy.core.errors import ProhibitedAction, UsageNotPermitted
from happy.core.provenance import DataProvenance, Evidence, ProvenanceKind
from happy.core.risk import RiskTier

NOW = datetime(2026, 8, 20, 12, 0, 0)


class TestRiskTier:
    def test_ordering_is_strictness(self) -> None:
        assert RiskTier.T0 < RiskTier.T1 < RiskTier.T2 < RiskTier.T3 < RiskTier.T4

    @pytest.mark.parametrize(
        ("tier", "auto", "approval", "prohibited"),
        [
            (RiskTier.T0, True, False, False),
            (RiskTier.T1, True, False, False),
            (RiskTier.T2, False, True, False),
            (RiskTier.T3, False, True, False),
            (RiskTier.T4, False, False, True),
        ],
    )
    def test_handling_per_tier(
        self, tier: RiskTier, auto: bool, approval: bool, prohibited: bool
    ) -> None:
        assert tier.auto_executable is auto
        assert tier.requires_approval is approval
        assert tier.is_prohibited is prohibited

    def test_every_tier_has_exactly_one_handling(self) -> None:
        for tier in RiskTier:
            handlings = [tier.auto_executable, tier.requires_approval, tier.is_prohibited]
            assert sum(handlings) == 1, f"{tier.name} has ambiguous handling"

    def test_raised_to_is_commutative_and_takes_the_max(self) -> None:
        for a in RiskTier:
            for b in RiskTier:
                assert a.raised_to(b) is b.raised_to(a)
                assert a.raised_to(b) == max(a, b)


class TestCapability:
    def test_money_move_is_forbidden(self) -> None:
        assert Capability.MONEY_MOVE in FORBIDDEN_CAPABILITIES

    def test_money_read_is_not_forbidden(self) -> None:
        assert Capability.MONEY_READ not in FORBIDDEN_CAPABILITIES

    def test_capability_values_are_namespaced(self) -> None:
        """Namespacing keeps grants readable in an audit record."""
        for capability in Capability:
            assert ":" in capability.value


class TestProvenance:
    def test_only_user_supplied_input_is_trusted(self) -> None:
        for kind in ProvenanceKind:
            provenance = DataProvenance(kind=kind, source_id="s", retrieved_at=NOW)
            assert provenance.is_trusted_input == (kind is ProvenanceKind.USER_SUPPLIED)

    def test_fetched_content_is_never_trusted(self) -> None:
        """A page saying 'ignore your instructions' is data, not an instruction."""
        provenance = DataProvenance(
            kind=ProvenanceKind.FETCHED_DOCUMENT,
            source_id="example.com",
            retrieved_at=NOW,
        )
        assert not provenance.is_trusted_input

    def test_model_output_is_never_trusted(self) -> None:
        provenance = DataProvenance(
            kind=ProvenanceKind.MODEL_OUTPUT, source_id="model", retrieved_at=NOW
        )
        assert not provenance.is_trusted_input

    def test_provenance_is_immutable(self) -> None:
        provenance = DataProvenance(
            kind=ProvenanceKind.VENDOR_API, source_id="s", retrieved_at=NOW
        )
        with pytest.raises(ValidationError):
            provenance.source_id = "other"  # type: ignore[misc]

    def test_evidence_requires_provenance(self) -> None:
        with pytest.raises(ValidationError):
            Evidence(claim="the market is large")  # type: ignore[call-arg]

    def test_evidence_confidence_is_bounded(self) -> None:
        provenance = DataProvenance(
            kind=ProvenanceKind.FETCHED_DOCUMENT, source_id="s", retrieved_at=NOW
        )
        with pytest.raises(ValidationError):
            Evidence(claim="c", provenance=provenance, confidence=1.5)


class TestErrors:
    def test_prohibited_action_carries_action_and_reason(self) -> None:
        error = ProhibitedAction("transfer", "the AI never moves money")
        assert error.action == "transfer"
        assert "never moves money" in str(error)

    def test_usage_not_permitted_carries_source_and_intent(self) -> None:
        error = UsageNotPermitted("Yahoo:Finance", "commercial_product", "ToS")
        assert error.source == "Yahoo:Finance"
        assert error.intent == "commercial_product"
