"""CodeExecutor — run generated code inside a sandbox.

Generated code is the least trusted thing in the system: it is written by a
model, from a spec, possibly influenced by untrusted content the model read.
It therefore runs with no network, no secrets and no access outside its
workspace.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import ClassVar

from pydantic import Field

from happy.core.capability import Capability
from happy.core.ports.base import (
    CapabilityPort,
    OperationSpec,
    PortDescriptor,
    PortInput,
    PortOutput,
    ProhibitedOperationSpec,
    register_port,
)
from happy.core.provenance import ProvenanceKind
from happy.core.risk import RiskTier
from happy.core.terms import AuthRequirement, CostKind, CostModel, RateLimit


class WorkspaceRef(PortInput):
    workspace_id: str
    """Opaque id. Adapters map it to a directory; agents never see a path."""


class ReadFileRequest(PortInput):
    workspace: WorkspaceRef
    relative_path: str
    max_bytes: int = Field(default=1_000_000, gt=0)


class FileContent(PortOutput):
    relative_path: str
    text: str
    content_hash: str
    truncated: bool = False


class WriteFileRequest(PortInput):
    workspace: WorkspaceRef
    relative_path: str
    text: str


class WriteResult(PortOutput):
    relative_path: str
    bytes_written: int
    content_hash: str


class RunRequest(PortInput):
    workspace: WorkspaceRef
    command: tuple[str, ...]
    """Argv, never a shell string: there is no shell to inject into."""
    timeout_s: float = Field(default=120.0, gt=0, le=900)
    max_output_bytes: int = Field(default=256_000, gt=0)
    network_enabled: bool = False
    """Declared for clarity. Adapters must reject True; see prohibitions."""


class RunResult(PortOutput):
    exit_code: int
    stdout: str
    stderr: str
    duration_s: float
    timed_out: bool = False
    output_truncated: bool = False


@register_port
class CodeExecutorPort(CapabilityPort):
    """Sandboxed execution of generated code."""

    descriptor: ClassVar[PortDescriptor] = PortDescriptor(
        port_id="code_executor",
        version="1.0",
        summary="Run generated code in an isolated, offline workspace.",
        provenance_kind=ProvenanceKind.SYSTEM_EVENT,
        auth=AuthRequirement.none(),
        rate_limit=RateLimit(
            concurrent=1, notes="One sandbox at a time; a low-spec host cannot do more."
        ),
        operations=(
            OperationSpec(
                name="read_file",
                summary="Read a file from the workspace.",
                risk_tier=RiskTier.T0,
                capabilities=frozenset({Capability.FILESYSTEM_READ}),
                input_model=ReadFileRequest,
                output_model=FileContent,
                idempotent=True,
                typical_cost=CostModel(kind=CostKind.FREE),
            ),
            OperationSpec(
                name="write_file",
                summary="Write a file into the workspace.",
                risk_tier=RiskTier.T1,
                capabilities=frozenset({Capability.FILESYSTEM_WRITE}),
                input_model=WriteFileRequest,
                output_model=WriteResult,
                typical_cost=CostModel(kind=CostKind.FREE),
            ),
            OperationSpec(
                name="run",
                summary="Execute a command in the sandbox, offline.",
                risk_tier=RiskTier.T2,
                capabilities=frozenset(
                    {
                        Capability.PROCESS_EXECUTE,
                        Capability.FILESYSTEM_READ,
                        Capability.FILESYSTEM_WRITE,
                    }
                ),
                input_model=RunRequest,
                output_model=RunResult,
                typical_cost=CostModel(kind=CostKind.FREE),
            ),
        ),
        prohibited_operations=(
            ProhibitedOperationSpec(
                name="run_with_network",
                reason="Generated code must never reach the network; it is the "
                "shortest path from prompt injection to exfiltration.",
            ),
            ProhibitedOperationSpec(
                name="run_as_root",
                reason="Sandbox escape risk. Execution is unprivileged, always.",
            ),
            ProhibitedOperationSpec(
                name="mount_host_path",
                reason="The workspace is the boundary; the host filesystem is out "
                "of reach by construction.",
            ),
            ProhibitedOperationSpec(
                name="install_system_package",
                reason="Mutating the host is irreversible and outside the workspace.",
            ),
        ),
        notes=(
            "`run` is T2 rather than T1 because generated code is the least "
            "trusted input in the system, even offline."
        ),
    )

    @abstractmethod
    async def read_file(self, request: ReadFileRequest) -> FileContent: ...

    @abstractmethod
    async def write_file(self, request: WriteFileRequest) -> WriteResult: ...

    @abstractmethod
    async def run(self, request: RunRequest) -> RunResult: ...
