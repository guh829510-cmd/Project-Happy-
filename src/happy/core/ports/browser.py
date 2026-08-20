"""Browser — headless page rendering.

**No adapter ships in v1.** The port exists so the contract, its risk tiers and
its prohibitions are defined before anyone is tempted to implement one; a
declared, denied capability is safer than an undeclared one that arrives later
by accident.

Open Computer Use was excluded on FSL-1.1 Competing Use grounds
(DEVELOPMENT_PLAN.md §7.4). If browser automation is ever needed, it is built
clean-room over permissively licensed tooling, and it inherits the tiers below.
"""

from __future__ import annotations

from abc import abstractmethod
from datetime import datetime
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


class RenderRequest(PortInput):
    url: str
    wait_for_selector: str | None = None
    timeout_s: float = Field(default=30.0, gt=0, le=120)
    javascript_enabled: bool = True
    respect_robots: bool = True


class RenderedPage(PortOutput):
    url: str
    final_url: str
    text: str
    html_hash: str
    status_code: int
    rendered_at: datetime
    robots_allowed: bool = True


class ScreenshotRequest(PortInput):
    url: str
    width: int = Field(default=1280, ge=320, le=3840)
    height: int = Field(default=800, ge=240, le=2160)
    full_page: bool = False
    timeout_s: float = Field(default=30.0, gt=0, le=120)


class Screenshot(PortOutput):
    url: str
    image_ref: str
    """Storage reference, never inline bytes: outputs land in the audit log."""
    width: int
    height: int
    captured_at: datetime


@register_port
class BrowserPort(CapabilityPort):
    """Headless rendering of a page the system does not control.

    Read-only by contract. Every form of interaction that could act on a user's
    behalf — clicking, typing, authenticating, purchasing — is prohibited and
    has no method here.
    """

    descriptor: ClassVar[PortDescriptor] = PortDescriptor(
        port_id="browser",
        version="1.0",
        summary="Headless, read-only page rendering and screenshots.",
        provenance_kind=ProvenanceKind.FETCHED_DOCUMENT,
        auth=AuthRequirement.none(),
        rate_limit=RateLimit(
            requests=10,
            window_seconds=60,
            concurrent=1,
            notes="Rendering is the most expensive read we do; kept deliberately low.",
        ),
        operations=(
            OperationSpec(
                name="render",
                summary="Render a page and return its text.",
                risk_tier=RiskTier.T1,
                capabilities=frozenset({Capability.NETWORK_READ, Capability.PROCESS_EXECUTE}),
                input_model=RenderRequest,
                output_model=RenderedPage,
                idempotent=True,
                typical_cost=CostModel(kind=CostKind.FREE),
            ),
            OperationSpec(
                name="screenshot",
                summary="Capture a screenshot to the artifact store.",
                risk_tier=RiskTier.T1,
                capabilities=frozenset(
                    {
                        Capability.NETWORK_READ,
                        Capability.PROCESS_EXECUTE,
                        Capability.FILESYSTEM_WRITE,
                    }
                ),
                input_model=ScreenshotRequest,
                output_model=Screenshot,
                idempotent=True,
                typical_cost=CostModel(kind=CostKind.FREE),
            ),
        ),
        prohibited_operations=(
            ProhibitedOperationSpec(
                name="interact",
                reason="Clicking and typing on third-party sites acts on the "
                "Chairman's behalf without their knowledge.",
            ),
            ProhibitedOperationSpec(
                name="authenticate",
                reason="Entering credentials into a third-party site is never "
                "permitted; no adapter may hold session credentials.",
            ),
            ProhibitedOperationSpec(
                name="submit_form",
                reason="Form submission is an outward-facing commitment.",
            ),
            ProhibitedOperationSpec(
                name="complete_purchase",
                reason="Money movement is permanently prohibited.",
            ),
            ProhibitedOperationSpec(
                name="solve_captcha",
                reason="Circumventing anti-automation controls violates site "
                "terms and is a detection-evasion technique.",
            ),
        ),
        notes="No adapter is planned for v1. Rendered content is untrusted.",
    )

    @abstractmethod
    async def render(self, request: RenderRequest) -> RenderedPage: ...

    @abstractmethod
    async def screenshot(self, request: ScreenshotRequest) -> Screenshot: ...
