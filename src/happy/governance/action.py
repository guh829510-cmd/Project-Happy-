"""The unit the kernel governs.

An `ActionRequest` is what every layer of enforcement sees: the deny list, the
classifier, the token check, the budget guard, the approval gateway and the
audit log all read this one object. It carries **digests of inputs, never the
inputs themselves** — the kernel needs to bind an approval to exact arguments
and to prove afterwards what was run, neither of which requires holding the
payload, and holding it would put untrusted content and possible secrets into
the audit log.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from happy.core.capability import Capability
from happy.core.ports.base import PortDescriptor, PortInput
from happy.core.risk import RiskTier
from happy.governance.hashing import digest, redact_secrets


class ActionRequest(BaseModel):
    """One attempted action, described in governance terms."""

    model_config = ConfigDict(frozen=True)

    actor: str
    """Agent id. Never a person: people approve, agents act."""
    port_id: str
    operation: str
    summary: str = ""

    capabilities: frozenset[Capability] = frozenset()
    declared_tier: RiskTier = RiskTier.T3
    """The port's declared tier. Defaults high: undeclared means unassessed."""
    declared: bool = True
    """False when no port descriptor backs this operation."""

    estimated_cost_usd: Decimal = Field(default=Decimal("0"), ge=0)
    reversible: bool = True
    externally_visible: bool = False
    handles_personal_data: bool = False

    venture_id: str | None = None
    task_id: str | None = None
    input_digest: str = ""

    @property
    def action_id(self) -> str:
        """`port.operation`, the name used in refusals and audit records."""
        return f"{self.port_id}.{self.operation}"

    @property
    def name_words(self) -> frozenset[str]:
        """Lower-cased words of the operation name, for deny-list matching.

        Whole-word matching rather than substring: `complete` must not trigger a
        rule written for `complete_purchase`, and `read_file` must not trigger
        one written for a tax `filing`.
        """
        return frozenset(t for t in self.operation.lower().split("_") if t)

    def audit_fields(self) -> dict[str, Any]:
        """The subset written to the audit log, redacted."""
        return {
            "actor": self.actor,
            "port_id": self.port_id,
            "operation": self.operation,
            "summary": redact_secrets(self.summary),
            "capabilities": sorted(c.value for c in self.capabilities),
            "venture_id": self.venture_id,
            "task_id": self.task_id,
            "input_digest": self.input_digest,
        }

    @classmethod
    def from_operation(
        cls,
        *,
        actor: str,
        descriptor: PortDescriptor,
        operation: str,
        payload: PortInput | None = None,
        estimated_cost_usd: Decimal | None = None,
        venture_id: str | None = None,
        task_id: str | None = None,
    ) -> ActionRequest:
        """Build a request from a port's own declaration.

        Raises:
            KeyError: the port declares no such operation. Callers must treat
                this as a refusal, not as a reason to construct a request by
                hand — an undeclared operation is unassessed by definition.
        """
        spec = descriptor.operation(operation)
        cost = estimated_cost_usd
        if cost is None:
            cost = _payload_budget(payload)
        if cost is None:
            cost = spec.typical_cost.amount or Decimal("0")

        return cls(
            actor=actor,
            port_id=descriptor.port_id,
            operation=spec.name,
            summary=spec.summary,
            capabilities=spec.capabilities,
            declared_tier=spec.risk_tier,
            declared=True,
            estimated_cost_usd=cost,
            reversible=spec.reversible,
            externally_visible=spec.externally_visible,
            handles_personal_data=descriptor.handles_personal_data,
            venture_id=venture_id,
            task_id=task_id,
            input_digest=digest_payload(payload),
        )


def _payload_budget(payload: PortInput | None) -> Decimal | None:
    """A payload that declares its own `budget_usd` is the best cost estimate."""
    budget = getattr(payload, "budget_usd", None)
    return Decimal(str(budget)) if budget is not None else None


def digest_payload(payload: PortInput | None) -> str:
    """Hash a port input so an approval can be bound to exact arguments."""
    if payload is None:
        return digest(None)
    return digest(payload.model_dump(mode="json"))
