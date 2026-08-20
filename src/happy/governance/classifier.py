"""Risk classification: deterministic rules first.

`ARCHITECTURE_V2.md` §5.3 fixes the shape of this module. Rules are ordered,
each may only **raise** a tier, and the result carries the reasons — because an
approval request that cannot say why it is a T3 is not informed consent.

An LLM may participate, but only through `with_advisory`, which discards any
suggestion that would lower a tier. A model that has been talked into calling
an irreversible action routine therefore changes nothing.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from happy.core.capability import Capability
from happy.core.risk import RiskTier
from happy.governance.action import ActionRequest


class ClassifierConfig(BaseModel):
    """Thresholds. Tuned to keep routine work off the approval queue.

    Approval fatigue is a security risk (`DEVELOPMENT_PLAN.md` §8.3): a system
    that asks fifty times a day gets rubber-stamped. These numbers exist to be
    raised as confidence grows, never to be bypassed.
    """

    model_config = ConfigDict(frozen=True)

    approval_cost_usd: Decimal = Field(default=Decimal("1.00"), gt=0)
    """Spend at or above this needs a human."""
    high_cost_usd: Decimal = Field(default=Decimal("20.00"), gt=0)
    """Spend at or above this needs typed confirmation and a cooling-off."""


class Classification(BaseModel):
    """A tier and the reasoning that produced it."""

    model_config = ConfigDict(frozen=True)

    tier: RiskTier
    reasons: tuple[str, ...] = ()

    def raised_to(self, tier: RiskTier, reason: str) -> Classification:
        """Return a classification at the stricter of the two tiers.

        A rule that would lower the tier contributes nothing — not even its
        reason, which would otherwise read as justification for leniency.
        """
        if tier <= self.tier:
            return self
        return Classification(tier=tier, reasons=(*self.reasons, f"{tier.name}: {reason}"))


class RiskClassifier:
    """Deterministic risk rules over an `ActionRequest`."""

    def __init__(self, config: ClassifierConfig | None = None) -> None:
        self._config = config or ClassifierConfig()

    @property
    def config(self) -> ClassifierConfig:
        return self._config

    def classify(self, request: ActionRequest) -> Classification:
        """Classify an action. Never returns lower than the port's declaration."""
        result = Classification(
            tier=request.declared_tier,
            reasons=(f"{request.declared_tier.name}: declared by {request.action_id}",),
        )

        if not request.declared:
            result = result.raised_to(
                RiskTier.T3,
                "operation is not declared by any port; an unassessed action is "
                "treated as the highest applicable tier",
            )

        if request.externally_visible:
            result = result.raised_to(RiskTier.T2, "the action is visible outside the system")

        if not request.reversible:
            result = result.raised_to(RiskTier.T3, "the action cannot be undone")

        if request.handles_personal_data:
            # The port-wide flag means personal data is in scope at all, which is
            # a T1 concern. Actually *writing* it is T2, via the capability rule
            # below — otherwise reading one's own CRM would need an approval and
            # the queue would fill with decisions nobody should be making.
            result = result.raised_to(
                RiskTier.T1, "the port handles personal data"
            )

        result = self._classify_cost(request, result)
        return self._classify_capabilities(request, result)

    def _classify_cost(
        self, request: ActionRequest, result: Classification
    ) -> Classification:
        cost = request.estimated_cost_usd
        if cost >= self._config.high_cost_usd:
            return result.raised_to(
                RiskTier.T3, f"estimated spend {cost} USD is at or above the high-cost limit"
            )
        if cost >= self._config.approval_cost_usd:
            return result.raised_to(
                RiskTier.T2, f"estimated spend {cost} USD is at or above the approval limit"
            )
        if cost > 0:
            return result.raised_to(RiskTier.T1, f"metered spend of {cost} USD")
        return result

    def _classify_capabilities(
        self, request: ActionRequest, result: Classification
    ) -> Classification:
        caps = request.capabilities

        if Capability.MONEY_MOVE in caps:
            # Unreachable through a declared port — `OperationSpec` refuses the
            # capability outright — and asserted here so the tier is right even
            # for a request built by hand.
            return result.raised_to(RiskTier.T4, "the action would move money")

        rules: tuple[tuple[Capability, RiskTier, str], ...] = (
            # T2, not T3: production changes always need a human, but a
            # rollback also carries this capability and putting a cooling-off
            # period in front of incident recovery makes outages longer. The
            # irreversible case, `deploy_production`, declares T3 itself.
            (Capability.DEPLOY_PRODUCTION, RiskTier.T2, "it changes production"),
            (Capability.EXTERNAL_PUBLISH, RiskTier.T2, "it publishes outside the system"),
            (
                Capability.OUTBOUND_MESSAGE,
                RiskTier.T2,
                "it messages someone who is not the Chairman",
            ),
            (Capability.PERSONAL_DATA_WRITE, RiskTier.T2, "it writes personal data"),
            (Capability.SECRET_READ, RiskTier.T2, "it reads a secret"),
            (Capability.REPO_WRITE, RiskTier.T1, "it writes to a repository"),
            (Capability.PROCESS_EXECUTE, RiskTier.T1, "it executes a process"),
            (Capability.NETWORK_WRITE, RiskTier.T1, "it writes over the network"),
        )
        for capability, tier, reason in rules:
            if capability in caps:
                result = result.raised_to(tier, reason)
        return result

    def with_advisory(
        self,
        classification: Classification,
        advisory_tier: RiskTier,
        reason: str,
    ) -> Classification:
        """Fold in a judgement from a model or a heuristic — raising only.

        This is the only sanctioned way for an LLM to affect classification.
        """
        return classification.raised_to(advisory_tier, f"advisory — {reason}")
