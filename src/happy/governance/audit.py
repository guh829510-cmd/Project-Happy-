"""The hash-chained audit log.

Two threats shape this module. **Repudiation** — "the AI did it" with no record
— is answered by writing an entry for every governance decision, including the
refusals, with the actor, the token, the tier, the reasoning and a digest of the
inputs. **Tampering** — falsifying history to hide a bad decision — is answered
by chaining each entry's hash into the next, so altering, reordering, removing
or truncating any entry is detectable by `verify()` alone, without a backup to
compare against.

What the chain proves is narrow and worth stating: entries have not been
changed since they were written *by this process*. Someone able to rewrite the
whole log can produce a consistent chain. The defence against that is the
append-only table and the off-box backup, both of which arrive with persistence
in M2; the chain is what makes a partial edit — the realistic case — useless.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from happy.core.protocols import Clock
from happy.core.risk import RiskTier
from happy.governance.action import ActionRequest
from happy.governance.errors import AuditChainBroken
from happy.governance.hashing import GENESIS_HASH, chain_hash, redact_secrets


class AuditDecision(StrEnum):
    """What the kernel did. Refusals are recorded as carefully as approvals."""

    ALLOWED = "allowed"
    DENIED = "denied"
    PROHIBITED = "prohibited"
    """A T4 refusal. Recorded so attempts are visible even though nothing ran."""
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_REJECTED = "approval_rejected"
    APPROVAL_EXPIRED = "approval_expired"
    EXECUTED = "executed"
    FAILED = "failed"
    BUDGET_BREACH = "budget_breach"
    KILL_SWITCH_ENGAGED = "kill_switch_engaged"
    KILL_SWITCH_RELEASED = "kill_switch_released"


class AuditEvent(BaseModel):
    """One immutable entry. `entry_hash` covers the content and the position."""

    model_config = ConfigDict(frozen=True)

    seq: int = Field(ge=0)
    recorded_at: datetime
    decision: AuditDecision
    reason: str

    actor: str = "system"
    port_id: str = ""
    operation: str = ""
    tier: RiskTier | None = None
    capabilities: tuple[str, ...] = ()
    cost_usd: Decimal = Decimal("0")
    token_id: str | None = None
    approval_id: str | None = None
    venture_id: str | None = None
    task_id: str | None = None
    input_digest: str = ""
    output_digest: str = ""

    prev_hash: str
    entry_hash: str

    def hashed_payload(self) -> dict[str, Any]:
        """Everything the hash covers — that is, everything but the hash."""
        payload = self.model_dump(mode="json", exclude={"entry_hash"})
        return dict(payload)


class AuditChain:
    """Append-only, verifiable sequence of governance events."""

    def __init__(self, clock: Clock, events: Sequence[AuditEvent] = ()) -> None:
        self._clock = clock
        self._events: list[AuditEvent] = list(events)

    def __len__(self) -> int:
        return len(self._events)

    def __iter__(self) -> Iterator[AuditEvent]:
        return iter(self._events)

    @property
    def events(self) -> tuple[AuditEvent, ...]:
        return tuple(self._events)

    @property
    def head_hash(self) -> str:
        return self._events[-1].entry_hash if self._events else GENESIS_HASH

    def record(
        self,
        decision: AuditDecision,
        reason: str,
        *,
        actor: str = "system",
        port_id: str = "",
        operation: str = "",
        tier: RiskTier | None = None,
        capabilities: tuple[str, ...] = (),
        cost_usd: Decimal = Decimal("0"),
        token_id: str | None = None,
        approval_id: str | None = None,
        venture_id: str | None = None,
        task_id: str | None = None,
        input_digest: str = "",
        output_digest: str = "",
    ) -> AuditEvent:
        """Append an entry and return it."""
        draft = AuditEvent(
            seq=len(self._events),
            recorded_at=self._clock.now(),
            decision=decision,
            reason=redact_secrets(reason),
            actor=actor,
            port_id=port_id,
            operation=operation,
            tier=tier,
            capabilities=capabilities,
            cost_usd=cost_usd,
            token_id=token_id,
            approval_id=approval_id,
            venture_id=venture_id,
            task_id=task_id,
            input_digest=input_digest,
            output_digest=output_digest,
            prev_hash=self.head_hash,
            entry_hash="",
        )
        event = draft.model_copy(
            update={"entry_hash": chain_hash(draft.prev_hash, draft.hashed_payload())}
        )
        self._events.append(event)
        return event

    def record_action(
        self,
        request: ActionRequest,
        decision: AuditDecision,
        reason: str,
        *,
        tier: RiskTier | None = None,
        token_id: str | None = None,
        approval_id: str | None = None,
        cost_usd: Decimal | None = None,
        output_digest: str = "",
    ) -> AuditEvent:
        """Append an entry describing an attempted action."""
        return self.record(
            decision,
            reason,
            actor=request.actor,
            port_id=request.port_id,
            operation=request.operation,
            tier=tier,
            capabilities=tuple(sorted(c.value for c in request.capabilities)),
            cost_usd=request.estimated_cost_usd if cost_usd is None else cost_usd,
            token_id=token_id,
            approval_id=approval_id,
            venture_id=request.venture_id,
            task_id=request.task_id,
            input_digest=request.input_digest,
            output_digest=output_digest,
        )

    def verify(self) -> None:
        """Recompute the chain.

        Raises:
            AuditChainBroken: an entry was altered, reordered, inserted or
                removed. The exception names the first bad sequence number.
        """
        prev = GENESIS_HASH
        for index, event in enumerate(self._events):
            if event.seq != index:
                raise AuditChainBroken(event.seq, f"expected seq {index}; entries are ordered")
            if event.prev_hash != prev:
                raise AuditChainBroken(
                    event.seq, "previous hash does not match the entry before it"
                )
            expected = chain_hash(event.prev_hash, event.hashed_payload())
            if expected != event.entry_hash:
                raise AuditChainBroken(event.seq, "entry hash does not match its content")
            prev = event.entry_hash
