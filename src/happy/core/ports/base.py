"""Port contract primitives.

The invariants a port must satisfy are checked at import time by
`register_port`, not only in tests. A module that violates them fails to
import, so a violation cannot reach a running system even if a test is skipped.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from happy.core.capability import FORBIDDEN_CAPABILITIES, Capability
from happy.core.provenance import DataProvenance, ProvenanceKind
from happy.core.risk import RiskTier
from happy.core.terms import AuthRequirement, CostModel, ProviderTerms, RateLimit


class PortInput(BaseModel):
    """Base class for every port operation's input."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class PortOutput(BaseModel):
    """Base class for every port operation's output.

    Outputs carry provenance. A port that returns external data without saying
    where it came from cannot be governed, because the usage policy has nothing
    to evaluate.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    provenance: tuple[DataProvenance, ...] = ()


class OperationSpec(BaseModel):
    """The declaration for one operation on a port."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    name: str
    summary: str
    risk_tier: RiskTier
    capabilities: frozenset[Capability]
    input_model: type[PortInput]
    output_model: type[PortOutput]

    idempotent: bool = False
    reversible: bool = True
    externally_visible: bool = False
    """True when the operation is observable by someone outside the system."""
    emits_provenance: bool = True
    typical_cost: CostModel = Field(default_factory=CostModel)

    @model_validator(mode="after")
    def _check_invariants(self) -> OperationSpec:
        forbidden = self.capabilities & FORBIDDEN_CAPABILITIES
        if forbidden:
            raise ValueError(
                f"operation {self.name!r} declares forbidden capability "
                f"{sorted(c.value for c in forbidden)}; no port may hold it"
            )
        if self.risk_tier.is_prohibited:
            raise ValueError(
                f"operation {self.name!r} is declared T4. Prohibited actions must "
                "be listed in `prohibited_operations`, which have no method on the "
                "port, rather than as callable operations"
            )
        if self.externally_visible and self.risk_tier < RiskTier.T2:
            raise ValueError(
                f"operation {self.name!r} is externally visible but tiered "
                f"{self.risk_tier.name}; external visibility requires T2 or higher"
            )
        if not self.reversible and not self.risk_tier.requires_approval:
            raise ValueError(
                f"operation {self.name!r} is irreversible but tiered "
                f"{self.risk_tier.name}; an irreversible action must require "
                "human approval (T2 or T3)"
            )
        return self


class ProhibitedOperationSpec(BaseModel):
    """A named action this port will never perform.

    These exist so prohibition is explicit and testable. A prohibited operation
    has **no corresponding method** on the port class — there is nothing to
    call. Naming it lets the policy engine refuse it by name if some future
    adapter invents it, and lets a test assert the method's absence.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    reason: str
    risk_tier: RiskTier = RiskTier.T4

    @model_validator(mode="after")
    def _must_be_t4(self) -> ProhibitedOperationSpec:
        if not self.risk_tier.is_prohibited:
            raise ValueError(
                f"prohibited operation {self.name!r} must be T4, got {self.risk_tier.name}"
            )
        return self


class PortDescriptor(BaseModel):
    """A port's complete, static capability declaration.

    Readable without instantiating the port, without credentials and without a
    network. The governance kernel reads this to classify a call before any
    adapter is touched.
    """

    model_config = ConfigDict(frozen=True)

    port_id: str
    version: str
    summary: str
    operations: tuple[OperationSpec, ...]
    prohibited_operations: tuple[ProhibitedOperationSpec, ...] = ()
    auth: AuthRequirement
    rate_limit: RateLimit
    provenance_kind: ProvenanceKind
    handles_personal_data: bool = False
    notes: str = ""

    @model_validator(mode="after")
    def _check_unique_names(self) -> PortDescriptor:
        names = [op.name for op in self.operations]
        if len(names) != len(set(names)):
            raise ValueError(f"{self.port_id}: duplicate operation names in {names}")
        overlap = set(names) & {p.name for p in self.prohibited_operations}
        if overlap:
            raise ValueError(
                f"{self.port_id}: {sorted(overlap)} declared both callable and prohibited"
            )
        if not self.operations:
            raise ValueError(f"{self.port_id}: a port must declare ≥1 operation")
        return self

    def operation(self, name: str) -> OperationSpec:
        for op in self.operations:
            if op.name == name:
                return op
        raise KeyError(f"{self.port_id} has no operation {name!r}")

    @property
    def operation_names(self) -> frozenset[str]:
        return frozenset(op.name for op in self.operations)

    @property
    def prohibited_names(self) -> frozenset[str]:
        return frozenset(p.name for p in self.prohibited_operations)

    @property
    def capabilities(self) -> frozenset[Capability]:
        """Union of every capability any operation may exercise."""
        return frozenset().union(*(op.capabilities for op in self.operations))

    @property
    def max_risk_tier(self) -> RiskTier:
        """The strictest tier of any callable operation."""
        return max(op.risk_tier for op in self.operations)

    @property
    def requires_approval(self) -> bool:
        return any(op.risk_tier.requires_approval for op in self.operations)


class CapabilityPort(ABC):
    """Base class for every capability port.

    Subclasses declare a `descriptor` and implement `terms()`. They declare
    abstract methods for their callable operations and — importantly — declare
    no method at all for anything prohibited.
    """

    descriptor: ClassVar[PortDescriptor]

    @abstractmethod
    def terms(self) -> ProviderTerms:
        """The bound provider's licensing, cost and rate-limit terms.

        Runtime rather than static, because the same port serves providers with
        different terms. The usage policy reads this, not the descriptor.
        """
        raise NotImplementedError


PORT_REGISTRY: dict[str, type[CapabilityPort]] = {}
"""Every registered port, by `descriptor.port_id`."""


def register_port(cls: type[CapabilityPort]) -> type[CapabilityPort]:
    """Register a port and enforce its invariants at import time.

    Raises:
        TypeError: the class is not a `CapabilityPort` or has no descriptor.
        ValueError: the port id is a duplicate, or a prohibited operation has a
            matching attribute on the class — which would make it callable.
    """
    if not issubclass(cls, CapabilityPort):
        raise TypeError(f"{cls.__name__} is not a CapabilityPort")

    descriptor = cls.__dict__.get("descriptor")
    if descriptor is None:
        raise TypeError(f"{cls.__name__} must declare its own `descriptor`")

    if descriptor.port_id in PORT_REGISTRY:
        raise ValueError(f"duplicate port id {descriptor.port_id!r}")

    # The structural guarantee: a prohibited operation must not exist as an
    # attribute. If it did, an adapter could implement it and it would be
    # callable despite the declaration.
    for prohibited in descriptor.prohibited_operations:
        if hasattr(cls, prohibited.name):
            raise ValueError(
                f"{cls.__name__} declares {prohibited.name!r} prohibited but also "
                "defines it as an attribute; a prohibited operation must have no "
                "method on the port"
            )

    # Every callable operation must have a method to call.
    for op in descriptor.operations:
        if not hasattr(cls, op.name):
            raise ValueError(
                f"{cls.__name__} declares operation {op.name!r} but defines no method"
            )

    PORT_REGISTRY[descriptor.port_id] = cls
    return cls
