"""The mandatory proxy.

A department is constructed with port *interfaces*, and the composition root
binds every one of them to a `GovernedPort` wrapping a real adapter. A
department therefore never holds a raw adapter, and there is no argument, flag
or keyword anywhere in this class that reaches the underlying port without a
policy decision first (ADR-0002).

Three refusals happen here, before the policy engine is even consulted:

* **A prohibited operation raises on attribute access.** Reaching for
  `payments.transfer` is the attempt; there is nothing to call, and `hasattr`
  deliberately raises rather than quietly returning False.
* **An undeclared operation is refused.** A method the descriptor does not
  declare is unassessed, and unassessed means denied — not "probably fine".
* **Nothing private is offered.** Underscore attributes are not served, so
  the proxy presents no route to the adapter it wraps.

What this class is not: a sandbox. Python has no private attributes, and code
running in this process could import an adapter and call it directly. The proxy
makes ungoverned calls impossible *by construction of the object graph* — a
department is handed proxies and never sees a raw adapter — which is why the
composition root is the only place adapters may be built (ADR-0002), and why
that rule is enforced by review rather than by this file.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from happy.core.errors import ProhibitedAction
from happy.core.ports.base import CapabilityPort, PortDescriptor, PortInput
from happy.core.terms import ProviderTerms
from happy.governance.action import ActionRequest
from happy.governance.capability import CapabilityToken
from happy.governance.hashing import digest
from happy.governance.policy import PolicyEngine


class GovernedPort:
    """A capability port that cannot be called without a policy decision."""

    def __init__(
        self,
        port: CapabilityPort,
        *,
        engine: PolicyEngine,
        token: CapabilityToken,
        actor: str,
        venture_id: str | None = None,
        task_id: str | None = None,
        approval_id: str | None = None,
    ) -> None:
        self._port = port
        self._engine = engine
        self._token = token
        self._actor = actor
        self._venture_id = venture_id
        self._task_id = task_id
        self._approval_id = approval_id

    @property
    def descriptor(self) -> PortDescriptor:
        """The port's static declaration. Readable: it is what governs the call."""
        return self._port.descriptor

    @property
    def port_id(self) -> str:
        return self.descriptor.port_id

    def terms(self) -> ProviderTerms:
        """The bound provider's terms. Reading metadata is not an action."""
        return self._port.terms()

    def with_approval(self, approval_id: str) -> GovernedPort:
        """A proxy that will spend `approval_id` on its next governed call."""
        return GovernedPort(
            self._port,
            engine=self._engine,
            token=self._token,
            actor=self._actor,
            venture_id=self._venture_id,
            task_id=self._task_id,
            approval_id=approval_id,
        )

    def for_task(self, task_id: str) -> GovernedPort:
        """A proxy whose calls are billed and audited against `task_id`."""
        return GovernedPort(
            self._port,
            engine=self._engine,
            token=self._token,
            actor=self._actor,
            venture_id=self._venture_id,
            task_id=task_id,
            approval_id=self._approval_id,
        )

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(
                f"{type(self).__name__!r} exposes no private attribute {name!r}; "
                "the wrapped adapter is not reachable through its proxy"
            )

        descriptor = self._port.descriptor
        if name in descriptor.prohibited_names:
            raise ProhibitedAction(
                f"{descriptor.port_id}.{name}",
                "declared prohibited by the port; there is no method to call and "
                "no approval that would create one",
            )
        if name not in descriptor.operation_names:
            raise ProhibitedAction(
                f"{descriptor.port_id}.{name}",
                "not a declared operation; an unassessed action is refused rather "
                "than attempted",
            )
        return self._govern(name)

    def _govern(self, operation: str) -> Callable[..., Awaitable[Any]]:
        async def call(
            payload: PortInput | None = None,
            *,
            estimated_cost_usd: Decimal | None = None,
            approval_id: str | None = None,
        ) -> Any:
            request = ActionRequest.from_operation(
                actor=self._actor,
                descriptor=self._port.descriptor,
                operation=operation,
                payload=payload,
                estimated_cost_usd=estimated_cost_usd,
                venture_id=self._venture_id,
                task_id=self._task_id,
            )
            decision = self._engine.evaluate(
                request,
                self._token,
                approval_id=approval_id or self._approval_id,
                prohibited_names=self._port.descriptor.prohibited_names,
            )
            decision.raise_if_denied()

            method = getattr(self._port, operation)
            try:
                result = await (method() if payload is None else method(payload))
            except BaseException as error:
                self._engine.settle(decision, request, error=error)
                raise

            self._engine.settle(
                decision,
                request,
                actual_cost_usd=_actual_cost(result),
                output_digest=_output_digest(result),
            )
            return result

        call.__name__ = operation
        return call


def _actual_cost(result: Any) -> Decimal | None:
    """Adapters that know what a call cost say so on the result."""
    cost = getattr(result, "cost_usd", None)
    return Decimal(str(cost)) if cost is not None else None


def _output_digest(result: Any) -> str:
    """Hash the output so the audit can prove what was returned, without storing it."""
    if isinstance(result, BaseModel):
        return digest(result.model_dump(mode="json"))
    return digest(repr(result))
