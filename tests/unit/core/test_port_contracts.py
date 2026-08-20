"""Every port must declare a complete, coherent contract.

These tests are parametrised over `PORT_REGISTRY`, so a port added later is
covered automatically — the suite does not need to know it exists.
"""

from __future__ import annotations

import inspect

import pytest

from happy.core.capability import FORBIDDEN_CAPABILITIES, Capability
from happy.core.ports import PORT_REGISTRY, REQUIRED_PORTS
from happy.core.ports.base import CapabilityPort, PortInput, PortOutput
from happy.core.risk import RiskTier

ALL_PORTS = sorted(PORT_REGISTRY.items())
PORT_IDS = [pid for pid, _ in ALL_PORTS]


def test_every_required_port_is_registered() -> None:
    assert set(PORT_REGISTRY) >= REQUIRED_PORTS, (
        f"missing ports: {sorted(REQUIRED_PORTS - set(PORT_REGISTRY))}"
    )


def test_no_unexpected_ports() -> None:
    """A new port is a deliberate architectural act, not an accident."""
    assert set(PORT_REGISTRY) == REQUIRED_PORTS


@pytest.mark.parametrize("port_id", PORT_IDS)
def test_port_declares_all_required_metadata(port_id: str) -> None:
    """The nine things every port must declare."""
    d = PORT_REGISTRY[port_id].descriptor

    assert d.port_id and d.version and d.summary
    assert d.operations, "a port must declare at least one operation"
    assert d.auth is not None, "authentication requirements"
    assert d.rate_limit is not None, "rate limits"
    assert d.provenance_kind is not None, "data provenance kind"

    for op in d.operations:
        assert issubclass(op.input_model, PortInput), f"{op.name}: typed input"
        assert issubclass(op.output_model, PortOutput), f"{op.name}: typed output"
        assert isinstance(op.risk_tier, RiskTier), f"{op.name}: risk classification"
        assert isinstance(op.capabilities, frozenset), f"{op.name}: capability declaration"


@pytest.mark.parametrize("port_id", PORT_IDS)
def test_port_exposes_terms_for_commercial_metadata(port_id: str) -> None:
    """Commercial-use and redistribution metadata come from the bound instance.

    They are runtime rather than static because the same port serves providers
    with different terms.
    """
    cls = PORT_REGISTRY[port_id]
    assert hasattr(cls, "terms")
    assert getattr(cls.terms, "__isabstractmethod__", False), (
        f"{cls.__name__}.terms must stay abstract so every adapter declares its own"
    )


@pytest.mark.parametrize("port_id", PORT_IDS)
def test_declared_operations_have_methods(port_id: str) -> None:
    cls = PORT_REGISTRY[port_id]
    for op in cls.descriptor.operations:
        method = getattr(cls, op.name, None)
        assert method is not None, f"{cls.__name__} declares {op.name} but has no method"
        assert callable(method)


@pytest.mark.parametrize("port_id", PORT_IDS)
def test_ports_are_abstract(port_id: str) -> None:
    """A port is a contract. Instantiating one directly must fail."""
    cls = PORT_REGISTRY[port_id]
    assert inspect.isabstract(cls), f"{cls.__name__} must not be instantiable"
    with pytest.raises(TypeError):
        cls()  # type: ignore[abstract]


@pytest.mark.parametrize("port_id", PORT_IDS)
def test_operation_names_unique_within_port(port_id: str) -> None:
    d = PORT_REGISTRY[port_id].descriptor
    assert len(d.operation_names) == len(d.operations)


@pytest.mark.parametrize("port_id", PORT_IDS)
def test_no_port_declares_a_forbidden_capability(port_id: str) -> None:
    d = PORT_REGISTRY[port_id].descriptor
    assert not (d.capabilities & FORBIDDEN_CAPABILITIES)


@pytest.mark.parametrize("port_id", PORT_IDS)
def test_no_callable_operation_is_t4(port_id: str) -> None:
    """T4 is prohibition. A callable T4 operation is a contradiction."""
    for op in PORT_REGISTRY[port_id].descriptor.operations:
        assert not op.risk_tier.is_prohibited


@pytest.mark.parametrize("port_id", PORT_IDS)
def test_external_visibility_requires_approval(port_id: str) -> None:
    for op in PORT_REGISTRY[port_id].descriptor.operations:
        if op.externally_visible:
            assert op.risk_tier.requires_approval, (
                f"{port_id}.{op.name} is externally visible but auto-executable"
            )


@pytest.mark.parametrize("port_id", PORT_IDS)
def test_irreversible_operations_require_approval(port_id: str) -> None:
    for op in PORT_REGISTRY[port_id].descriptor.operations:
        if not op.reversible:
            assert op.risk_tier.requires_approval, (
                f"{port_id}.{op.name} is irreversible but auto-executable"
            )


@pytest.mark.parametrize("port_id", PORT_IDS)
def test_network_writing_operations_are_not_t0(port_id: str) -> None:
    """T0 means read-only. Writing to the network is never free of consequence."""
    for op in PORT_REGISTRY[port_id].descriptor.operations:
        if Capability.NETWORK_WRITE in op.capabilities:
            assert op.risk_tier >= RiskTier.T1, f"{port_id}.{op.name}"


@pytest.mark.parametrize("port_id", PORT_IDS)
def test_personal_data_ports_are_flagged(port_id: str) -> None:
    d = PORT_REGISTRY[port_id].descriptor
    touches_pii = any(
        c in op.capabilities
        for op in d.operations
        for c in (Capability.PERSONAL_DATA_READ, Capability.PERSONAL_DATA_WRITE)
    )
    assert touches_pii == d.handles_personal_data, (
        f"{port_id}: handles_personal_data={d.handles_personal_data} "
        f"but PII capabilities present={touches_pii}"
    )


@pytest.mark.parametrize("port_id", PORT_IDS)
def test_credential_keys_are_names_not_values(port_id: str) -> None:
    """Descriptors are serialised into audit records. A secret here would leak."""
    for key in PORT_REGISTRY[port_id].descriptor.auth.credential_keys:
        assert key.isupper() or "_" in key
        assert not key.startswith(("sk-", "ghp_", "xox"))


def test_registry_contains_only_capability_ports() -> None:
    for cls in PORT_REGISTRY.values():
        assert issubclass(cls, CapabilityPort)
