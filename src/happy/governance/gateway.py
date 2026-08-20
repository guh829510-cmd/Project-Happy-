"""The approval gateway — where a human decides.

Enforcement layer 4. The design principles in `DEVELOPMENT_PLAN.md` §8.3 are
implemented literally here, and each one is a property a test asserts:

* **Deny by default** — an approval is required before the action, never after.
* **Expiry closes.** An unanswered request expires as *denied*. Silence is not
  consent, and a request left open overnight must not still be live at noon.
* **Typed confirmation on T3.** Clicking is too cheap for irreversible actions.
* **Cooling-off on T3.** A minimum delay between request and executable
  approval, so a decision cannot be made purely on impulse.
* **No batching of T3.** Bulk-approving irreversible actions is exactly the
  behaviour the tier exists to prevent.
* **Single use, bound to the inputs.** An approval authorises one action with
  one set of arguments — not the operation in general, and not a second run.

And the load-bearing absence: **there is no code path that approves a T4**.
`submit` refuses to file one, so the queue can never show a prohibited action
with an Approve button next to it.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from happy.core.errors import ProhibitedAction
from happy.core.protocols import Clock, IdFactory
from happy.core.risk import RiskTier
from happy.governance.action import ActionRequest
from happy.governance.audit import AuditChain, AuditDecision
from happy.governance.capability import CapabilityToken
from happy.governance.classifier import Classification
from happy.governance.errors import ApprovalInvalid

DEFAULT_APPROVAL_TTL = timedelta(hours=12)
DEFAULT_T3_COOLING_OFF = timedelta(minutes=15)


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    """Unanswered past its deadline. Equivalent to rejected, and never usable."""
    CONSUMED = "consumed"
    """Used by the action it authorised. An approval works exactly once."""


class ApprovalRecord(BaseModel):
    """One pending or settled decision, with everything needed to make it.

    Informed consent means the record answers, without leaving the page: what
    will happen, what it costs, what is irreversible about it, and why it was
    classified the way it was.
    """

    model_config = ConfigDict(frozen=True)

    approval_id: str
    request: ActionRequest
    tier: RiskTier
    reasons: tuple[str, ...]
    status: ApprovalStatus = ApprovalStatus.PENDING

    created_at: datetime
    expires_at: datetime
    executable_after: datetime
    """T3 cooling-off. Equal to `created_at` for T2."""

    confirmation_phrase: str | None = None
    """T3 only. The approver types this exactly; a click is not enough."""

    token_id: str | None = None
    decided_at: datetime | None = None
    decided_by: str | None = None
    decision_note: str = ""
    consumed_at: datetime | None = None

    @property
    def summary(self) -> str:
        return f"{self.request.action_id} ({self.tier.name})"

    @property
    def is_irreversible(self) -> bool:
        return not self.request.reversible

    def is_expired(self, now: datetime) -> bool:
        return now >= self.expires_at


class ApprovalGateway:
    """The queue of decisions waiting on the Chairman."""

    def __init__(
        self,
        clock: Clock,
        audit: AuditChain,
        *,
        ttl: timedelta = DEFAULT_APPROVAL_TTL,
        cooling_off: timedelta = DEFAULT_T3_COOLING_OFF,
        id_factory: IdFactory | None = None,
    ) -> None:
        self._clock = clock
        self._audit = audit
        self._ttl = ttl
        self._cooling_off = cooling_off
        self._id_factory: IdFactory = id_factory or _uuid_id
        self._records: dict[str, ApprovalRecord] = {}

    @property
    def cooling_off(self) -> timedelta:
        return self._cooling_off

    def submit(
        self,
        request: ActionRequest,
        classification: Classification,
        *,
        token: CapabilityToken | None = None,
    ) -> ApprovalRecord:
        """File a request for human decision.

        Raises:
            ProhibitedAction: the action is T4. This is the absence that matters
                — the gateway cannot represent a prohibited action, so nothing
                downstream can approve one.
            ValueError: the action does not need approval. Filing T0/T1 work
                would train the Chairman to approve without reading.
        """
        if classification.tier.is_prohibited:
            raise ProhibitedAction(
                request.action_id,
                "T4 actions have no approval path; the gateway cannot file one",
            )
        if not classification.tier.requires_approval:
            raise ValueError(
                f"{request.action_id} is {classification.tier.name} and executes without "
                "approval; filing it would add noise to the queue"
            )

        now = self._clock.now()
        cooling_off = self._cooling_off if classification.tier is RiskTier.T3 else timedelta(0)
        approval_id = self._id_factory()
        record = ApprovalRecord(
            approval_id=approval_id,
            request=request,
            tier=classification.tier,
            reasons=classification.reasons,
            created_at=now,
            expires_at=now + self._ttl,
            executable_after=now + cooling_off,
            confirmation_phrase=(
                f"APPROVE {approval_id}" if classification.tier is RiskTier.T3 else None
            ),
            token_id=token.token_id if token is not None else None,
        )
        self._records[approval_id] = record
        self._audit.record_action(
            request,
            AuditDecision.APPROVAL_REQUIRED,
            f"awaiting {record.tier.name} approval: " + "; ".join(classification.reasons),
            tier=record.tier,
            token_id=record.token_id,
            approval_id=approval_id,
        )
        return record

    def get(self, approval_id: str) -> ApprovalRecord:
        """Fetch a record, expiring it first if its deadline has passed.

        Raises:
            KeyError: no such approval.
        """
        record = self._records[approval_id]
        return self._expire_if_due(record)

    def pending(self) -> tuple[ApprovalRecord, ...]:
        """Every still-answerable request, oldest first."""
        live = [self._expire_if_due(r) for r in self._records.values()]
        return tuple(
            sorted(
                (r for r in live if r.status is ApprovalStatus.PENDING),
                key=lambda r: r.created_at,
            )
        )

    def approve(
        self,
        approval_id: str,
        *,
        approver: str = "chairman",
        confirmation: str | None = None,
        note: str = "",
    ) -> ApprovalRecord:
        """Grant an approval.

        Raises:
            ApprovalInvalid: already settled, expired, or — for T3 — the typed
                confirmation does not match.
        """
        record = self.get(approval_id)
        self._require_pending(record)

        if record.tier is RiskTier.T3 and confirmation != record.confirmation_phrase:
            raise ApprovalInvalid(
                approval_id,
                "T3 approval requires the confirmation phrase to be typed exactly",
            )

        settled = record.model_copy(
            update={
                "status": ApprovalStatus.APPROVED,
                "decided_at": self._clock.now(),
                "decided_by": approver,
                "decision_note": note,
            }
        )
        self._records[approval_id] = settled
        self._audit.record_action(
            record.request,
            AuditDecision.APPROVAL_GRANTED,
            f"approved by {approver}" + (f": {note}" if note else ""),
            tier=record.tier,
            token_id=record.token_id,
            approval_id=approval_id,
        )
        return settled

    def approve_many(
        self,
        approval_ids: tuple[str, ...],
        *,
        approver: str = "chairman",
        note: str = "",
    ) -> tuple[ApprovalRecord, ...]:
        """Approve several T2 requests at once.

        Raises:
            ApprovalInvalid: any of them is T3. Batching irreversible actions
                defeats the purpose of the tier, so the whole call is refused
                rather than partially applied.
        """
        records = [self.get(approval_id) for approval_id in approval_ids]
        for record in records:
            if record.tier is RiskTier.T3:
                raise ApprovalInvalid(
                    record.approval_id,
                    "T3 approvals cannot be batched; approve it on its own",
                )
        return tuple(
            self.approve(record.approval_id, approver=approver, note=note)
            for record in records
        )

    def reject(
        self,
        approval_id: str,
        reason: str,
        *,
        approver: str = "chairman",
    ) -> ApprovalRecord:
        """Decline an approval.

        Raises:
            ApprovalInvalid: already settled or expired.
        """
        record = self.get(approval_id)
        self._require_pending(record)
        settled = record.model_copy(
            update={
                "status": ApprovalStatus.REJECTED,
                "decided_at": self._clock.now(),
                "decided_by": approver,
                "decision_note": reason,
            }
        )
        self._records[approval_id] = settled
        self._audit.record_action(
            record.request,
            AuditDecision.APPROVAL_REJECTED,
            f"rejected by {approver}: {reason}",
            tier=record.tier,
            token_id=record.token_id,
            approval_id=approval_id,
        )
        return settled

    def consume(self, approval_id: str, request: ActionRequest) -> ApprovalRecord:
        """Spend an approval on the action it authorised.

        Raises:
            ApprovalInvalid: not approved, expired, still cooling off, already
                used, or presented with different arguments than were approved.
        """
        record = self.get(approval_id)
        if record.status is not ApprovalStatus.APPROVED:
            raise ApprovalInvalid(
                approval_id, f"status is {record.status.value}, not approved"
            )

        now = self._clock.now()
        if now < record.executable_after:
            remaining = record.executable_after - now
            raise ApprovalInvalid(
                approval_id,
                f"T3 cooling-off has {remaining} left; the approval is not yet executable",
            )
        if record.is_expired(now):
            self._expire(record)
            raise ApprovalInvalid(approval_id, "expired before it was used")

        if not _same_action(record.request, request):
            raise ApprovalInvalid(
                approval_id,
                "approved a different action or different arguments; approvals are "
                "bound to the inputs they were shown with",
            )

        spent = record.model_copy(
            update={"status": ApprovalStatus.CONSUMED, "consumed_at": now}
        )
        self._records[approval_id] = spent
        return spent

    def _require_pending(self, record: ApprovalRecord) -> None:
        if record.status is not ApprovalStatus.PENDING:
            raise ApprovalInvalid(
                record.approval_id, f"already {record.status.value}; decisions are final"
            )

    def _expire_if_due(self, record: ApprovalRecord) -> ApprovalRecord:
        if record.status is not ApprovalStatus.PENDING:
            return record
        if not record.is_expired(self._clock.now()):
            return record
        return self._expire(record)

    def _expire(self, record: ApprovalRecord) -> ApprovalRecord:
        expired = record.model_copy(
            update={"status": ApprovalStatus.EXPIRED, "decided_at": self._clock.now()}
        )
        self._records[record.approval_id] = expired
        self._audit.record_action(
            record.request,
            AuditDecision.APPROVAL_EXPIRED,
            "expired unanswered; an unanswered approval is a denial",
            tier=record.tier,
            token_id=record.token_id,
            approval_id=record.approval_id,
        )
        return expired


def _same_action(approved: ActionRequest, presented: ActionRequest) -> bool:
    """An approval covers one action with one set of arguments."""
    return (
        approved.actor == presented.actor
        and approved.port_id == presented.port_id
        and approved.operation == presented.operation
        and approved.input_digest == presented.input_digest
        and approved.venture_id == presented.venture_id
    )


def _uuid_id() -> str:
    from uuid import uuid4

    return uuid4().hex
