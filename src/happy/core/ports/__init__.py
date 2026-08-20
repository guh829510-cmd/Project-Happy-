"""Capability ports: the only way anything reaches the outside world.

A port is an abstract contract. It contains no implementation, no vendor
knowledge and no I/O. Adapters satisfy ports; integrations know vendors.

Department agents are constructed with port *interfaces*. The composition root
binds each interface to a governed proxy wrapping a real adapter, so a
department never holds a raw adapter and there is no path around the
governance kernel (ARCHITECTURE_V2.md, ADR-0002).

Every port declares, statically and without being instantiated:

* typed input and output models per operation
* the capabilities each operation exercises
* a risk tier per operation
* the kind of provenance its outputs carry
* its authentication requirements
* its rate-limit shape

and, per bound instance at runtime, the provider's commercial-use terms and
redistribution permission via `terms()`.
"""

from happy.core.ports.base import (
    PORT_REGISTRY,
    CapabilityPort,
    OperationSpec,
    PortDescriptor,
    PortInput,
    PortOutput,
    ProhibitedOperationSpec,
    register_port,
)
from happy.core.ports.browser import BrowserPort
from happy.core.ports.code_executor import CodeExecutorPort
from happy.core.ports.crm import CRMProviderPort
from happy.core.ports.data_source import DataSourcePort
from happy.core.ports.deployment import DeploymentProviderPort
from happy.core.ports.email import EmailProviderPort
from happy.core.ports.financial import FinancialAnalyzerPort
from happy.core.ports.git import GitProviderPort
from happy.core.ports.llm import LLMProviderPort
from happy.core.ports.notification import NotificationProviderPort
from happy.core.ports.payment import PaymentProviderPort
from happy.core.ports.research import ResearchProviderPort

REQUIRED_PORTS: frozenset[str] = frozenset(
    {
        "llm_provider",
        "research_provider",
        "data_source",
        "financial_analyzer",
        "browser",
        "code_executor",
        "git_provider",
        "email_provider",
        "notification_provider",
        "crm_provider",
        "payment_provider",
        "deployment_provider",
    }
)
"""Ports the architecture requires. Asserted against PORT_REGISTRY in tests."""

__all__ = [
    "PORT_REGISTRY",
    "REQUIRED_PORTS",
    "BrowserPort",
    "CRMProviderPort",
    "CapabilityPort",
    "CodeExecutorPort",
    "DataSourcePort",
    "DeploymentProviderPort",
    "EmailProviderPort",
    "FinancialAnalyzerPort",
    "GitProviderPort",
    "LLMProviderPort",
    "NotificationProviderPort",
    "OperationSpec",
    "PaymentProviderPort",
    "PortDescriptor",
    "PortInput",
    "PortOutput",
    "ProhibitedOperationSpec",
    "ResearchProviderPort",
    "register_port",
]
