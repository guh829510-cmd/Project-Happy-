"""The policy engine — one place where the layers are composed.

Every governed action passes through `evaluate` in this order, and the order is
the design: the kill switch stops everything, then prohibitions refuse without
appeal, then classification decides how much scrutiny applies, then the token
bounds the authority, then a human decides if the tier says so, and only then is
money committed. Each step can only refuse; none can grant more than the step
before it allowed.

`evaluate` returns a decision rather than raising, so a caller can inspect it,
show it to a person, or record it. Turning a refusal into an exception is the
caller's explicit act — `raise_if_denied` — which is why the deny path is hard
to ignore by accident but never happens implicitly.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from happy.core.errors import ProhibitedAction
from happy.core.protocols import Clock
from happy.core.risk import RiskTier
from happy.core.terms import DataSourceMetadata
from happy.core.usage_policy import UsageDecision, UsageIntent, evaluate_source_usage
from happy.governance import denylist
from happy.governance.action import ActionRequest
from happy.governance.audit import AuditChain, AuditDecision
from happy.governance.budget_guard import BudgetBreach, BudgetGuard, Reservation
from happy.governance.capability import CapabilityToken, TokenIssuer
from happy.governance.classifier import Classification, RiskClassifier
from happy.governance.errors import (
    ApprovalInvalid,
    ApprovalRequired,
    BudgetExceeded,
    CapabilityDenied,
    GovernanceError,
    KillSwitchEngaged,
    PolicyDenied,
    TokenInvalid,
)
from happy.governance.gateway import ApprovalGateway
from happy.governance.kill_switch import KillSwitch


class PolicyOutcome(StrEnum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


class PolicyDecision(BaseModel):
    """The engine's answer, with everything needed to act on it or explain it."""

    model_config = ConfigDict(frozen=True)

    outcome: PolicyOutcome
    tier: RiskTier
    reason: str
    reasons: tuple[str, ...] = ()
    prohibited: bool = False
    """True for a T4 refusal, which is a different kind of no."""
    rule_id: str | None = None
    approval_id: str | None = None
    reservation: Reservation | None = None
    action_id: str = ""

    @property
    def allowed(self) -> bool:
        return self.outcome is PolicyOutcome.ALLOW

    def raise_if_denied(self) -> None:
        """Turn a refusal into the exception that matches its kind.

        Raises:
            ProhibitedAction: the action is T4.
            ApprovalRequired: a human must decide first.
            PolicyDenied: refused for any other reason.
        """
        if self.outcome is PolicyOutcome.ALLOW:
            return
        if self.prohibited:
            raise ProhibitedAction(self.action_id, self.reason)
        if self.outcome is PolicyOutcome.REQUIRE_APPROVAL:
            raise ApprovalRequired(self.approval_id or "", self.tier, self.action_id)
        raise PolicyDenied(self.action_id, self.reason)


class PolicyEngine:
    """Composes the enforcement layers into one decision."""

    def __init__(
        self,
        *,
        clock: Clock,
        issuer: TokenIssuer,
        budget_guard: BudgetGuard,
        gateway: ApprovalGateway,
        audit: AuditChain,
        classifier: RiskClassifier | None = None,
        kill_switch: KillSwitch | None = None,
        commercial_context: bool = True,
    ) -> None:
        self._clock = clock
        self._issuer = issuer
        self._budget = budget_guard
        self._gateway = gateway
        self._audit = audit
        self._classifier = classifier or RiskClassifier()
        self._kill_switch = kill_switch or KillSwitch(audit)
        self._commercial_context = commercial_context

    @property
    def audit(self) -> AuditChain:
        return self._audit

    @property
    def gateway(self) -> ApprovalGateway:
        return self._gateway

    @property
    def kill_switch(self) -> KillSwitch:
        return self._kill_switch

    @property
    def budget(self) -> BudgetGuard:
        return self._budget

    def classify(self, request: ActionRequest) -> Classification:
        return self._classifier.classify(request)

    def evaluate(
        self,
        request: ActionRequest,
        token: CapabilityToken,
        *,
        approval_id: str | None = None,
        prohibited_names: frozenset[str] = frozenset(),
    ) -> PolicyDecision:
        """Decide whether this action may run now."""
        try:
            self._kill_switch.assert_clear()
        except KillSwitchEngaged as stop:
            return self._deny(request, RiskTier.T4, str(stop), token_id=token.token_id)

        rule = denylist.evaluate(request, prohibited_names=prohibited_names)
        if rule is not None:
            reason = f"{rule.rule_id}: {rule.description} {rule.rationale}"
            self._audit.record_action(
                request,
                AuditDecision.PROHIBITED,
                reason,
                tier=RiskTier.T4,
                token_id=token.token_id,
            )
            return PolicyDecision(
                outcome=PolicyOutcome.DENY,
                tier=RiskTier.T4,
                reason=reason,
                prohibited=True,
                rule_id=rule.rule_id,
                action_id=request.action_id,
            )

        classification = self._classifier.classify(request)
        if classification.tier.is_prohibited:
            # Reached only by a request built by hand: no port can declare T4.
            reason = "classified T4; prohibited actions have no approval path"
            self._audit.record_action(
                request,
                AuditDecision.PROHIBITED,
                reason,
                tier=RiskTier.T4,
                token_id=token.token_id,
            )
            return PolicyDecision(
                outcome=PolicyOutcome.DENY,
                tier=RiskTier.T4,
                reason=reason,
                reasons=classification.reasons,
                prohibited=True,
                action_id=request.action_id,
            )

        try:
            self._issuer.authorize(token, request, classification.tier)
        except (TokenInvalid, CapabilityDenied) as denied:
            return self._deny(
                request, classification.tier, str(denied), token_id=token.token_id
            )

        if classification.tier.requires_approval:
            decision = self._resolve_approval(request, token, classification, approval_id)
            if decision is not None:
                return decision

        try:
            reservation = self._budget.reserve(request, token=token)
        except BudgetExceeded as over:
            return self._deny(
                request, classification.tier, str(over), token_id=token.token_id
            )

        self._audit.record_action(
            request,
            AuditDecision.ALLOWED,
            "; ".join(classification.reasons),
            tier=classification.tier,
            token_id=token.token_id,
            approval_id=approval_id,
        )
        return PolicyDecision(
            outcome=PolicyOutcome.ALLOW,
            tier=classification.tier,
            reason="permitted",
            reasons=classification.reasons,
            approval_id=approval_id,
            reservation=reservation,
            action_id=request.action_id,
        )

    def settle(
        self,
        decision: PolicyDecision,
        request: ActionRequest,
        *,
        actual_cost_usd: Decimal | None = None,
        output_digest: str = "",
        error: BaseException | None = None,
    ) -> None:
        """Record what actually happened and release the money held for it.

        A breach — actual spend past a limit an estimate said was fine — engages
        the kill switch. Being wrong about cost once is forgivable; continuing to
        act while the accounting is known to be wrong is not.
        """
        cost = actual_cost_usd if actual_cost_usd is not None else request.estimated_cost_usd
        breaches: tuple[BudgetBreach, ...] = ()
        if decision.reservation is not None:
            if error is not None and actual_cost_usd is None:
                self._budget.release(decision.reservation)
                cost = Decimal("0")
            else:
                breaches = self._budget.commit(decision.reservation, cost)

        self._audit.record_action(
            request,
            AuditDecision.FAILED if error is not None else AuditDecision.EXECUTED,
            f"{type(error).__name__}: {error}" if error is not None else "completed",
            tier=decision.tier,
            approval_id=decision.approval_id,
            cost_usd=cost,
            output_digest=output_digest,
        )

        for breach in breaches:
            self._audit.record(
                AuditDecision.BUDGET_BREACH,
                f"{breach.scope} budget for {breach.key!r} passed: "
                f"spent {breach.spent} against limit {breach.limit}",
                actor=request.actor,
                cost_usd=breach.spent,
            )
            self._kill_switch.engage(
                f"actual spend passed the {breach.scope} limit for {breach.key!r}"
            )

    def evaluate_source_usage(
        self,
        metadata: DataSourceMetadata,
        intent: UsageIntent,
        *,
        today: date | None = None,
    ) -> UsageDecision:
        """The single entry point to the data-usage policy.

        Delegates to the pure domain rule and supplies the injected clock, so
        the kernel and the domain cannot disagree about what day it is.
        """
        return evaluate_source_usage(
            metadata,
            intent,
            today=today or self._clock.today(),
            commercial_context=self._commercial_context,
        )

    def _resolve_approval(
        self,
        request: ActionRequest,
        token: CapabilityToken,
        classification: Classification,
        approval_id: str | None,
    ) -> PolicyDecision | None:
        """Return a decision when approval is missing or unusable, else None."""
        if approval_id is None:
            record = self._gateway.submit(request, classification, token=token)
            return PolicyDecision(
                outcome=PolicyOutcome.REQUIRE_APPROVAL,
                tier=classification.tier,
                reason=f"{classification.tier.name} approval required",
                reasons=classification.reasons,
                approval_id=record.approval_id,
                action_id=request.action_id,
            )
        try:
            self._gateway.consume(approval_id, request)
        except (ApprovalInvalid, KeyError) as invalid:
            reason = (
                str(invalid)
                if isinstance(invalid, GovernanceError)
                else f"no approval {invalid}"
            )
            return self._deny(
                request,
                classification.tier,
                reason,
                token_id=token.token_id,
                approval_id=approval_id,
            )
        return None

    def _deny(
        self,
        request: ActionRequest,
        tier: RiskTier,
        reason: str,
        *,
        token_id: str | None = None,
        approval_id: str | None = None,
    ) -> PolicyDecision:
        self._audit.record_action(
            request,
            AuditDecision.DENIED,
            reason,
            tier=tier,
            token_id=token_id,
            approval_id=approval_id,
        )
        return PolicyDecision(
            outcome=PolicyOutcome.DENY,
            tier=tier,
            reason=reason,
            approval_id=approval_id,
            action_id=request.action_id,
        )
