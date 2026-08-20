"""Terms, metadata and their guardrails."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from happy.core.terms import (
    DEFAULT_MAX_METADATA_AGE_DAYS,
    AuthRequirement,
    AuthScheme,
    CommercialUse,
    CostKind,
    CostModel,
    DataSourceMetadata,
    Permission,
    ProviderTerms,
    RateLimit,
)

REQUIRED_DATA_SOURCE_FIELDS = {
    "provider",
    "source_name",
    "license",
    "terms_url",
    "commercial_use",
    "redistribution_allowed",
    "derived_data_allowed",
    "attribution_required",
    "authentication_required",
    "cost",
    "rate_limit",
    "last_verified",
    "notes",
}


class TestDataSourceMetadataShape:
    def test_declares_every_required_field(self) -> None:
        """The exact field set the architecture requires."""
        assert set(DataSourceMetadata.model_fields) >= REQUIRED_DATA_SOURCE_FIELDS

    def test_source_id_is_stable_and_qualified(self) -> None:
        meta = DataSourceMetadata(
            provider="SEC", source_name="EDGAR", last_verified=date(2026, 8, 1)
        )
        assert meta.source_id == "SEC:EDGAR"

    def test_license_defaults_to_requires_review(self) -> None:
        meta = DataSourceMetadata(
            provider="p", source_name="s", last_verified=date(2026, 8, 1)
        )
        assert meta.license.startswith("UNKNOWN")
        assert meta.requires_review

    def test_requires_review_clears_when_all_fields_resolved(self) -> None:
        meta = DataSourceMetadata(
            provider="p",
            source_name="s",
            license="CC0-1.0",
            commercial_use=CommercialUse.PERMITTED,
            redistribution_allowed=Permission.ALLOWED,
            derived_data_allowed=Permission.ALLOWED,
            last_verified=date(2026, 8, 1),
        )
        assert not meta.requires_review

    def test_attribution_text_names_source_and_license(self) -> None:
        meta = DataSourceMetadata(
            provider="OpenData",
            source_name="portal",
            license="CC-BY-4.0",
            terms_url="https://example.org",
            last_verified=date(2026, 8, 1),
        )
        text = meta.attribution_text()
        assert "OpenData" in text and "portal" in text and "CC-BY-4.0" in text

    def test_attribution_text_omits_unresolved_license(self) -> None:
        meta = DataSourceMetadata(
            provider="p", source_name="s", last_verified=date(2026, 8, 1)
        )
        assert "UNKNOWN" not in meta.attribution_text()

    def test_metadata_is_immutable(self) -> None:
        meta = DataSourceMetadata(
            provider="p", source_name="s", last_verified=date(2026, 8, 1)
        )
        with pytest.raises(ValidationError):
            meta.provider = "other"  # type: ignore[misc]


class TestStaleness:
    def test_fresh_terms_are_not_stale(self) -> None:
        meta = ProviderTerms(provider="p", last_verified=date(2026, 8, 1))
        assert not meta.is_stale(today=date(2026, 8, 20))

    def test_terms_go_stale_past_the_threshold(self) -> None:
        meta = ProviderTerms(provider="p", last_verified=date(2025, 1, 1))
        assert meta.is_stale(today=date(2026, 8, 20))

    def test_threshold_boundary_is_exclusive(self) -> None:
        today = date(2026, 8, 20)
        verified = date.fromordinal(today.toordinal() - DEFAULT_MAX_METADATA_AGE_DAYS)
        meta = ProviderTerms(provider="p", last_verified=verified)
        assert not meta.is_stale(today=today)
        assert meta.age_days(today=today) == DEFAULT_MAX_METADATA_AGE_DAYS


class TestAuthRequirement:
    def test_rejects_openai_style_key(self) -> None:
        with pytest.raises(ValidationError, match="looks like a secret"):
            AuthRequirement(credential_keys=("sk-abcdefghijklmnop",))

    def test_rejects_github_token(self) -> None:
        with pytest.raises(ValidationError, match="looks like a secret"):
            AuthRequirement(credential_keys=("ghp_abcdefghijklmnopqrstuvwxyz",))

    def test_rejects_private_key_block(self) -> None:
        with pytest.raises(ValidationError):
            AuthRequirement(credential_keys=("-----BEGIN RSA PRIVATE KEY-----",))

    def test_rejects_long_base64_blob(self) -> None:
        with pytest.raises(ValidationError):
            AuthRequirement(credential_keys=("A" * 48,))

    def test_accepts_environment_variable_names(self) -> None:
        auth = AuthRequirement(
            scheme=AuthScheme.API_KEY, credential_keys=("HAPPY_LLM_API_KEY",)
        )
        assert auth.credential_keys == ("HAPPY_LLM_API_KEY",)

    def test_none_helper_requires_nothing(self) -> None:
        auth = AuthRequirement.none()
        assert auth.scheme is AuthScheme.NONE
        assert not auth.required


class TestRateLimit:
    def test_undeclared_is_distinguishable_from_unlimited(self) -> None:
        assert not RateLimit().declared
        assert not RateLimit.unknown().declared
        assert RateLimit(requests=10, window_seconds=1).declared

    def test_requests_per_second_computed_when_known(self) -> None:
        assert RateLimit(requests=10, window_seconds=2).requests_per_second == 5.0

    def test_requests_per_second_none_when_window_missing(self) -> None:
        assert RateLimit(requests=10).requests_per_second is None

    def test_daily_quota_alone_counts_as_declared(self) -> None:
        assert RateLimit(daily_quota=500).declared


class TestCostModel:
    def test_unknown_by_default(self) -> None:
        assert CostModel().kind is CostKind.UNKNOWN

    def test_free_is_not_payment_requiring(self) -> None:
        cost = CostModel(kind=CostKind.FREE)
        assert cost.is_free
        assert not cost.requires_payment

    def test_metered_requires_payment(self) -> None:
        cost = CostModel(kind=CostKind.METERED, unit="per_request", amount=Decimal("0.01"))
        assert cost.requires_payment
        assert not cost.is_free

    def test_freemium_is_neither_free_nor_payment_requiring(self) -> None:
        """A free tier exists, but it may run out. Callers must handle both."""
        cost = CostModel(kind=CostKind.FREEMIUM)
        assert not cost.is_free
        assert not cost.requires_payment
