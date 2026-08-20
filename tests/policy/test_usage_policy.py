"""The refusal matrix.

`evaluate_source_usage` is the mechanism that lets the policy engine refuse an
action when a source's commercial-use policy does not permit it. These tests
are the specification of that behaviour.

Three properties matter more than any individual case:

* **fail closed** — UNKNOWN is a refusal, never a permission;
* **stale is unverified** — old terms are refused for outward-facing use;
* **obligations are surfaced** — conditional permission tells the caller what
  it must do, rather than silently allowing.
"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from happy.core.errors import UsageNotPermitted
from happy.core.risk import RiskTier
from happy.core.terms import CommercialUse, DataSourceMetadata, Permission
from happy.core.usage_policy import UsageIntent, evaluate_source_usage

pytestmark = pytest.mark.policy

ALL_INTENTS = list(UsageIntent)
OUTWARD_INTENTS = [
    UsageIntent.EXTERNAL_PUBLICATION,
    UsageIntent.REDISTRIBUTION,
    UsageIntent.COMMERCIAL_PRODUCT,
]


class TestFailClosed:
    """Absence of evidence is not permission."""

    @pytest.mark.parametrize("intent", ALL_INTENTS)
    def test_unreviewed_source_is_refused_for_every_intent(
        self, unreviewed_source: DataSourceMetadata, intent: UsageIntent, today: date
    ) -> None:
        decision = evaluate_source_usage(unreviewed_source, intent, today=today)
        assert not decision.allowed
        if intent is not UsageIntent.MODEL_TRAINING:
            # Training is refused by a categorical rule before metadata is
            # consulted, so it is not a "resolve the metadata" refusal.
            assert decision.requires_review

    def test_default_metadata_requires_review(self) -> None:
        meta = DataSourceMetadata(
            provider="p", source_name="s", last_verified=date(2026, 8, 20)
        )
        assert meta.requires_review
        assert meta.commercial_use is CommercialUse.UNKNOWN
        assert meta.redistribution_allowed is Permission.UNKNOWN
        assert meta.derived_data_allowed is Permission.UNKNOWN

    def test_attribution_defaults_to_required(self) -> None:
        """Attributing unnecessarily is harmless; failing to is not."""
        meta = DataSourceMetadata(
            provider="p", source_name="s", last_verified=date(2026, 8, 20)
        )
        assert meta.attribution_required is True


class TestCommercialUseGate:
    """The check the audit called for."""

    @pytest.mark.parametrize("intent", ALL_INTENTS)
    def test_prohibited_commercial_use_refuses_everything(
        self, yahoo_finance: DataSourceMetadata, intent: UsageIntent, today: date
    ) -> None:
        """A source that forbids commercial use is refused even for internal work.

        Project Happy is a commercial undertaking; there is no 'just internal'
        exemption from a commercial-use prohibition.
        """
        decision = evaluate_source_usage(yahoo_finance, intent, today=today)
        assert not decision.allowed

    def test_non_commercial_context_permits_internal_analysis(
        self, yahoo_finance: DataSourceMetadata, today: date
    ) -> None:
        """The same source is usable for private, non-commercial exploration."""
        decision = evaluate_source_usage(
            yahoo_finance,
            UsageIntent.INTERNAL_ANALYSIS,
            today=today,
            commercial_context=False,
        )
        assert decision.allowed

    def test_non_commercial_context_still_refuses_redistribution(
        self, yahoo_finance: DataSourceMetadata, today: date
    ) -> None:
        """Non-commercial does not override an explicit redistribution ban."""
        decision = evaluate_source_usage(
            yahoo_finance,
            UsageIntent.REDISTRIBUTION,
            today=today,
            commercial_context=False,
        )
        assert not decision.allowed

    @pytest.mark.parametrize("intent", OUTWARD_INTENTS)
    def test_paid_tier_source_refused_outward_until_plan_confirmed(
        self, paid_tier_source: DataSourceMetadata, intent: UsageIntent, today: date
    ) -> None:
        decision = evaluate_source_usage(paid_tier_source, intent, today=today)
        assert not decision.allowed
        assert "paid tier" in decision.reason

    def test_paid_tier_source_allows_internal_use_with_an_obligation(
        self, paid_tier_source: DataSourceMetadata, today: date
    ) -> None:
        decision = evaluate_source_usage(
            paid_tier_source, UsageIntent.INTERNAL_ANALYSIS, today=today
        )
        assert decision.allowed
        assert any("paid plan" in o for o in decision.obligations)
        assert decision.required_risk_tier >= RiskTier.T1


class TestPermittedSource:
    """A clean source is genuinely usable — the policy is not merely restrictive."""

    @pytest.mark.parametrize(
        "intent",
        [
            UsageIntent.INTERNAL_ANALYSIS,
            UsageIntent.DERIVED_ARTIFACT,
            UsageIntent.EXTERNAL_PUBLICATION,
            UsageIntent.REDISTRIBUTION,
            UsageIntent.COMMERCIAL_PRODUCT,
        ],
    )
    def test_public_domain_source_permits_everything_but_training(
        self, sec_edgar: DataSourceMetadata, intent: UsageIntent, today: date
    ) -> None:
        decision = evaluate_source_usage(sec_edgar, intent, today=today)
        assert decision.allowed, decision.reason

    def test_outward_intents_are_raised_to_t2(
        self, sec_edgar: DataSourceMetadata, today: date
    ) -> None:
        for intent in OUTWARD_INTENTS:
            decision = evaluate_source_usage(sec_edgar, intent, today=today)
            assert decision.required_risk_tier >= RiskTier.T2

    def test_no_attribution_obligation_when_not_required(
        self, sec_edgar: DataSourceMetadata, today: date
    ) -> None:
        decision = evaluate_source_usage(sec_edgar, UsageIntent.INTERNAL_ANALYSIS, today=today)
        assert not any("attribution" in o for o in decision.obligations)


class TestModelTraining:
    """No source is permitted for training by default."""

    def test_training_refused_even_for_public_domain_source(
        self, sec_edgar: DataSourceMetadata, today: date
    ) -> None:
        decision = evaluate_source_usage(sec_edgar, UsageIntent.MODEL_TRAINING, today=today)
        assert not decision.allowed
        assert "explicit written permission" in decision.reason


class TestStaleness:
    def test_stale_terms_refused_for_outward_use(
        self, stale_source: DataSourceMetadata, today: date
    ) -> None:
        for intent in OUTWARD_INTENTS:
            decision = evaluate_source_usage(stale_source, intent, today=today)
            assert not decision.allowed
            assert decision.metadata_stale

    def test_stale_terms_still_allow_internal_analysis(
        self, stale_source: DataSourceMetadata, today: date
    ) -> None:
        """Internal analysis is reversible and invisible; it may proceed, flagged."""
        decision = evaluate_source_usage(
            stale_source, UsageIntent.INTERNAL_ANALYSIS, today=today
        )
        assert decision.allowed
        assert decision.metadata_stale

    def test_staleness_threshold_is_configurable(
        self, sec_edgar: DataSourceMetadata, today: date
    ) -> None:
        decision = evaluate_source_usage(
            sec_edgar,
            UsageIntent.REDISTRIBUTION,
            today=today,
            max_metadata_age_days=1,
        )
        assert not decision.allowed
        assert decision.metadata_stale


class TestDerivedAndRedistribution:
    def _meta(self, **kw: object) -> DataSourceMetadata:
        base: dict[str, object] = {
            "provider": "V",
            "source_name": "s",
            "license": "proprietary",
            "commercial_use": CommercialUse.PERMITTED,
            "redistribution_allowed": Permission.DENIED,
            "derived_data_allowed": Permission.ALLOWED,
            "attribution_required": False,
            "last_verified": date(2026, 8, 1),
        }
        base.update(kw)
        return DataSourceMetadata(**base)  # type: ignore[arg-type]

    def test_publication_allowed_when_derived_rights_exist(self, today: date) -> None:
        """Publishing conclusions needs derived rights, not redistribution rights."""
        decision = evaluate_source_usage(
            self._meta(), UsageIntent.EXTERNAL_PUBLICATION, today=today
        )
        assert decision.allowed
        assert any("conclusions only" in o for o in decision.obligations), (
            "must warn that the source data itself may not be included"
        )

    def test_publication_refused_without_derived_rights(self, today: date) -> None:
        decision = evaluate_source_usage(
            self._meta(derived_data_allowed=Permission.DENIED),
            UsageIntent.EXTERNAL_PUBLICATION,
            today=today,
        )
        assert not decision.allowed

    def test_conditional_derived_use_surfaces_an_obligation(self, today: date) -> None:
        decision = evaluate_source_usage(
            self._meta(derived_data_allowed=Permission.CONDITIONAL),
            UsageIntent.DERIVED_ARTIFACT,
            today=today,
        )
        assert decision.allowed
        assert decision.obligations
        assert decision.required_risk_tier >= RiskTier.T1

    def test_redistribution_refused_when_denied(self, today: date) -> None:
        decision = evaluate_source_usage(self._meta(), UsageIntent.REDISTRIBUTION, today=today)
        assert not decision.allowed

    def test_commercial_product_refused_without_derived_rights(self, today: date) -> None:
        decision = evaluate_source_usage(
            self._meta(derived_data_allowed=Permission.DENIED),
            UsageIntent.COMMERCIAL_PRODUCT,
            today=today,
        )
        assert not decision.allowed


class TestAttributionObligation:
    def test_attribution_required_is_surfaced(self, today: date) -> None:
        meta = DataSourceMetadata(
            provider="OpenData",
            source_name="portal",
            license="CC-BY-4.0",
            terms_url="https://example.org/terms",
            commercial_use=CommercialUse.PERMITTED,
            redistribution_allowed=Permission.ALLOWED,
            derived_data_allowed=Permission.ALLOWED,
            attribution_required=True,
            last_verified=date(2026, 8, 1),
        )
        decision = evaluate_source_usage(meta, UsageIntent.EXTERNAL_PUBLICATION, today=today)
        assert decision.allowed
        attribution = [o for o in decision.obligations if "attribution" in o]
        assert attribution
        assert "CC-BY-4.0" in attribution[0]
        assert "OpenData" in attribution[0]


class TestDecisionIsActionable:
    def test_denied_decision_raises_with_context(
        self, yahoo_finance: DataSourceMetadata, today: date
    ) -> None:
        decision = evaluate_source_usage(
            yahoo_finance, UsageIntent.COMMERCIAL_PRODUCT, today=today
        )
        with pytest.raises(UsageNotPermitted) as exc:
            decision.raise_if_denied()
        assert exc.value.source == "Yahoo:Finance"
        assert exc.value.intent == "commercial_product"

    def test_allowed_decision_does_not_raise(
        self, sec_edgar: DataSourceMetadata, today: date
    ) -> None:
        evaluate_source_usage(
            sec_edgar, UsageIntent.INTERNAL_ANALYSIS, today=today
        ).raise_if_denied()

    def test_decision_records_which_source_and_intent(
        self, sec_edgar: DataSourceMetadata, today: date
    ) -> None:
        """Decisions land in the audit log; they must be self-describing."""
        decision = evaluate_source_usage(sec_edgar, UsageIntent.DERIVED_ARTIFACT, today=today)
        assert decision.source_id == "SEC:EDGAR"
        assert decision.intent is UsageIntent.DERIVED_ARTIFACT
        assert decision.reason


class TestPurity:
    """The policy is a pure function, which is why it is exhaustively testable."""

    def test_same_inputs_give_same_decision(
        self, paid_tier_source: DataSourceMetadata, today: date
    ) -> None:
        a = evaluate_source_usage(paid_tier_source, UsageIntent.INTERNAL_ANALYSIS, today=today)
        b = evaluate_source_usage(paid_tier_source, UsageIntent.INTERNAL_ANALYSIS, today=today)
        assert a == b

    def test_decision_is_frozen(self, sec_edgar: DataSourceMetadata, today: date) -> None:
        decision = evaluate_source_usage(sec_edgar, UsageIntent.INTERNAL_ANALYSIS, today=today)
        with pytest.raises(ValidationError):
            decision.allowed = False  # type: ignore[misc]

    def test_metadata_is_frozen(self, sec_edgar: DataSourceMetadata) -> None:
        with pytest.raises(ValidationError):
            sec_edgar.commercial_use = CommercialUse.PERMITTED  # type: ignore[misc]
