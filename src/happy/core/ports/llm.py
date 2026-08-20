"""LLMProvider — inference over an API. Never local, never GPU."""

from __future__ import annotations

from abc import abstractmethod
from decimal import Decimal
from enum import StrEnum
from typing import ClassVar

from pydantic import Field

from happy.core.capability import Capability
from happy.core.ports.base import (
    CapabilityPort,
    OperationSpec,
    PortDescriptor,
    PortInput,
    PortOutput,
    register_port,
)
from happy.core.provenance import ProvenanceKind
from happy.core.risk import RiskTier
from happy.core.terms import AuthRequirement, AuthScheme, CostKind, CostModel, RateLimit


class ModelTier(StrEnum):
    """Chosen by task, not by preference. Cost control starts here."""

    CHEAP = "cheap"
    """Routing, extraction, classification."""
    STANDARD = "standard"
    """Most department work."""
    JUDGMENT = "judgment"
    """Decisions that will be defended later. Used sparingly."""


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class Message(PortInput):
    role: Role
    content: str
    untrusted: bool = False
    """True when the content came from outside (a fetched page, an API).

    Untrusted content is data, never instructions. Adapters must fence it so a
    prompt-injection attempt in a scraped document cannot issue commands.
    """


class TokenUsage(PortOutput):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


class CompletionRequest(PortInput):
    messages: tuple[Message, ...]
    model_tier: ModelTier = ModelTier.STANDARD
    max_output_tokens: int = Field(default=2048, gt=0, le=32_000)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    response_schema_name: str | None = None
    """Name of the Pydantic model the response must validate against."""
    budget_usd: Decimal = Field(default=Decimal("0.25"), gt=0)
    """Hard cap for this single call. Exceeding it fails rather than truncates."""
    timeout_s: float = Field(default=120.0, gt=0)


class CompletionResult(PortOutput):
    text: str
    model: str
    """The model that actually served the call, which may differ from the tier."""
    usage: TokenUsage
    cost_usd: Decimal
    stop_reason: str
    schema_valid: bool | None = None
    """None when no schema was requested."""


class EmbeddingRequest(PortInput):
    texts: tuple[str, ...]
    budget_usd: Decimal = Field(default=Decimal("0.05"), gt=0)


class EmbeddingResult(PortOutput):
    vectors: tuple[tuple[float, ...], ...]
    model: str
    usage: TokenUsage
    cost_usd: Decimal


class TokenCountRequest(PortInput):
    messages: tuple[Message, ...]
    model_tier: ModelTier = ModelTier.STANDARD


class TokenCountResult(PortOutput):
    input_tokens: int = Field(ge=0)


@register_port
class LLMProviderPort(CapabilityPort):
    """Text and embedding inference behind a vendor-neutral contract.

    All inference is remote. There is no local-inference operation, which is
    what keeps the no-GPU constraint structural rather than aspirational.
    """

    descriptor: ClassVar[PortDescriptor] = PortDescriptor(
        port_id="llm_provider",
        version="1.0",
        summary="LLM text completion and embeddings over a vendor API.",
        provenance_kind=ProvenanceKind.MODEL_OUTPUT,
        auth=AuthRequirement(
            scheme=AuthScheme.API_KEY,
            required=True,
            credential_keys=("HAPPY_LLM_API_KEY",),
            supports_read_only_credential=False,
            notes="Key is read from env or keyring; never persisted to the database.",
        ),
        rate_limit=RateLimit(
            requests=50,
            window_seconds=60,
            concurrent=2,
            notes="Conservative default; real limits are provider-specific.",
        ),
        operations=(
            OperationSpec(
                name="complete",
                summary="Generate a completion, optionally schema-constrained.",
                risk_tier=RiskTier.T1,
                capabilities=frozenset({Capability.LLM_INFERENCE, Capability.NETWORK_READ}),
                input_model=CompletionRequest,
                output_model=CompletionResult,
                idempotent=False,
                typical_cost=CostModel(kind=CostKind.METERED, unit="per_1k_tokens"),
            ),
            OperationSpec(
                name="embed",
                summary="Embed texts. Optional; the default memory store is lexical.",
                risk_tier=RiskTier.T1,
                capabilities=frozenset({Capability.LLM_INFERENCE, Capability.NETWORK_READ}),
                input_model=EmbeddingRequest,
                output_model=EmbeddingResult,
                idempotent=True,
                typical_cost=CostModel(kind=CostKind.METERED, unit="per_1k_tokens"),
            ),
            OperationSpec(
                name="count_tokens",
                summary="Count input tokens before spending on a call.",
                risk_tier=RiskTier.T0,
                capabilities=frozenset({Capability.NETWORK_READ}),
                input_model=TokenCountRequest,
                output_model=TokenCountResult,
                idempotent=True,
                emits_provenance=False,
                typical_cost=CostModel(kind=CostKind.FREE),
            ),
        ),
        prohibited_operations=(),
        notes=(
            "Model output is evidence of nothing but the model's output. Claims "
            "derived from it require independent provenance."
        ),
    )

    @abstractmethod
    async def complete(self, request: CompletionRequest) -> CompletionResult: ...

    @abstractmethod
    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult: ...

    @abstractmethod
    async def count_tokens(self, request: TokenCountRequest) -> TokenCountResult: ...
