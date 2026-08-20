"""Data-usage policy: may this source be used for this purpose?

This module is the mechanism promised in `DEVELOPMENT_PLAN.md` §7.5 and
`ARCHITECTURE_V2.md` §2.1 — the reason licensing metadata lives in exactly one
place. The governance kernel calls `evaluate_source_usage` before any artifact
derived from a source is published, redistributed, or shipped in a commercial
product, and refuses the action when the terms do not permit it.

It is a pure function of (metadata, intent, context, today). No I/O, no
network, no clock of its own — so the whole refusal matrix is unit-testable.

Three rules govern the logic:

1. **Fail closed.** `UNKNOWN` is a refusal, never a permission.
2. **Stale terms are unverified terms.** Vendors change terms; metadata older
   than the threshold is refused for anything beyond internal analysis.
3. **Obligations are returned, not assumed.** When use is conditional, the
   caller is told what it must do (e.g. attribute) rather than silently
   permitted.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from happy.core.risk import RiskTier
from happy.core.terms import (
    DEFAULT_MAX_METADATA_AGE_DAYS,
    CommercialUse,
    DataSourceMetadata,
    Permission,
)


class UsageIntent(StrEnum):
    """What the caller intends to do with data from a source."""

    INTERNAL_ANALYSIS = "internal_analysis"
    """Read it, reason over it, store it internally. Never leaves the system."""

    DERIVED_ARTIFACT = "derived_artifact"
    """Produce a derived work held internally (a model, a score, a report)."""

    EXTERNAL_PUBLICATION = "external_publication"
    """Publish a derived work outside the system."""

    REDISTRIBUTION = "redistribution"
    """Pass the source data itself on to a third party."""

    COMMERCIAL_PRODUCT = "commercial_product"
    """Ship it, or something derived from it, as part of a paid offering."""

    MODEL_TRAINING = "model_training"
    """Train or fine-tune a model on it."""


class UsageDecision(BaseModel):
    """The policy engine's answer, with its reasoning."""

    model_config = ConfigDict(frozen=True)

    allowed: bool
    intent: UsageIntent
    source_id: str
    reason: str
    obligations: tuple[str, ...] = ()
    """What the caller must do if it proceeds (e.g. 'attribution required')."""
    required_risk_tier: RiskTier = RiskTier.T0
    """The minimum tier this use must be handled at, if permitted."""
    metadata_stale: bool = False
    requires_review: bool = False
    """True when refusal is due to unresolved metadata rather than a real 'no'."""

    def raise_if_denied(self) -> None:
        from happy.core.errors import UsageNotPermitted

        if not self.allowed:
            raise UsageNotPermitted(self.source_id, self.intent.value, self.reason)


_EXTERNAL_INTENTS = frozenset(
    {
        UsageIntent.EXTERNAL_PUBLICATION,
        UsageIntent.REDISTRIBUTION,
        UsageIntent.COMMERCIAL_PRODUCT,
    }
)


def _deny(
    metadata: DataSourceMetadata,
    intent: UsageIntent,
    reason: str,
    *,
    stale: bool = False,
    review: bool = False,
) -> UsageDecision:
    return UsageDecision(
        allowed=False,
        intent=intent,
        source_id=metadata.source_id,
        reason=reason,
        metadata_stale=stale,
        requires_review=review,
    )


def evaluate_source_usage(
    metadata: DataSourceMetadata,
    intent: UsageIntent,
    *,
    today: date,
    commercial_context: bool = True,
    max_metadata_age_days: int = DEFAULT_MAX_METADATA_AGE_DAYS,
) -> UsageDecision:
    """Decide whether `metadata`'s source may be used for `intent`.

    Args:
        metadata: terms for the source, as recorded by its integration.
        intent: what the caller means to do with the data.
        today: injected date. The domain never reads the clock itself.
        commercial_context: whether this venture is a commercial undertaking.
            Project Happy's default is True; a source that prohibits commercial
            use is therefore refused even for internal analysis.
        max_metadata_age_days: age beyond which terms count as unverified.

    Returns:
        A `UsageDecision`. Callers that treat a decision as advisory should use
        `raise_if_denied()` instead.
    """
    stale = metadata.is_stale(today=today, max_age_days=max_metadata_age_days)
    obligations: list[str] = []
    tier = RiskTier.T0

    # Rule 1 — model training is refused unless a source says yes explicitly.
    # No mainstream data licence grants it by silence, and the downside of
    # being wrong is not recoverable.
    if intent is UsageIntent.MODEL_TRAINING:
        return _deny(
            metadata,
            intent,
            "model training requires explicit written permission from the source; "
            "no source is permitted for training by default",
        )

    # Rule 2 — stale terms are unverified terms. Internal analysis may proceed
    # (it is reversible and invisible); anything outward-facing may not.
    if stale and intent is not UsageIntent.INTERNAL_ANALYSIS:
        return _deny(
            metadata,
            intent,
            f"terms last verified {metadata.age_days(today=today)} days ago "
            f"(limit {max_metadata_age_days}); re-verify before non-internal use",
            stale=True,
            review=True,
        )

    # Rule 3 — commercial-use gate. This is the check the audit called for:
    # refuse when the source's commercial policy does not permit the operation.
    if commercial_context:
        if metadata.commercial_use is CommercialUse.PROHIBITED:
            return _deny(
                metadata,
                intent,
                "source prohibits commercial use and this is a commercial context",
            )
        if metadata.commercial_use is CommercialUse.UNKNOWN:
            return _deny(
                metadata,
                intent,
                "commercial-use terms are UNKNOWN — REQUIRES REVIEW; "
                "unresolved terms are refused",
                stale=stale,
                review=True,
            )
        if metadata.commercial_use is CommercialUse.REQUIRES_PAID_TIER:
            if intent in _EXTERNAL_INTENTS:
                return _deny(
                    metadata,
                    intent,
                    "source requires a paid tier for commercial use; "
                    "confirm an active paid plan before outward-facing use",
                    review=True,
                )
            obligations.append("requires an active paid plan for this source")
            tier = tier.raised_to(RiskTier.T1)

    # Rule 4 — per-intent permission checks.
    if intent is UsageIntent.INTERNAL_ANALYSIS:
        pass  # permitted once the commercial gate above is satisfied

    elif intent is UsageIntent.DERIVED_ARTIFACT:
        if metadata.derived_data_allowed is Permission.DENIED:
            return _deny(metadata, intent, "source forbids derived data")
        if metadata.derived_data_allowed is Permission.UNKNOWN:
            return _deny(
                metadata,
                intent,
                "derived-data permission is UNKNOWN — REQUIRES REVIEW",
                review=True,
            )
        if metadata.derived_data_allowed is Permission.CONDITIONAL:
            obligations.append("derived use is conditional; see source terms")
            tier = tier.raised_to(RiskTier.T1)

    elif intent is UsageIntent.EXTERNAL_PUBLICATION:
        # Publishing a derived work needs derived rights, not redistribution
        # rights — but an outright redistribution ban is a strong signal and
        # is honoured here rather than argued with.
        if metadata.derived_data_allowed is not Permission.ALLOWED:
            if metadata.derived_data_allowed is Permission.CONDITIONAL:
                obligations.append("publication is conditional; see source terms")
            else:
                return _deny(
                    metadata,
                    intent,
                    "publishing a derived work requires derived-data permission; "
                    f"source states {metadata.derived_data_allowed.value}",
                    review=metadata.derived_data_allowed is Permission.UNKNOWN,
                )
        if metadata.redistribution_allowed is Permission.DENIED:
            obligations.append(
                "source data itself may not be included; publish conclusions only"
            )
        tier = tier.raised_to(RiskTier.T2)

    elif intent is UsageIntent.REDISTRIBUTION:
        if metadata.redistribution_allowed is not Permission.ALLOWED:
            return _deny(
                metadata,
                intent,
                "redistribution requires explicit permission; "
                f"source states {metadata.redistribution_allowed.value}",
                review=metadata.redistribution_allowed is Permission.UNKNOWN,
            )
        tier = tier.raised_to(RiskTier.T2)

    elif intent is UsageIntent.COMMERCIAL_PRODUCT:
        if metadata.commercial_use is not CommercialUse.PERMITTED:
            return _deny(
                metadata,
                intent,
                "shipping in a commercial product requires unambiguous "
                f"commercial permission; source states {metadata.commercial_use.value}",
                review=metadata.commercial_use is CommercialUse.UNKNOWN,
            )
        if metadata.derived_data_allowed is Permission.DENIED:
            return _deny(metadata, intent, "source forbids derived data")
        tier = tier.raised_to(RiskTier.T2)

    if metadata.attribution_required:
        obligations.append(f"attribution required: {metadata.attribution_text()}")

    return UsageDecision(
        allowed=True,
        intent=intent,
        source_id=metadata.source_id,
        reason="permitted by source terms",
        obligations=tuple(obligations),
        required_risk_tier=tier,
        metadata_stale=stale,
    )
