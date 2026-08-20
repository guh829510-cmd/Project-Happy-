"""The governance kernel.

Governance ships before any agent exists. Building capabilities first and
adding safety afterwards is how these systems end up with a gate that can be
walked around; the gate must predate the thing it gates.

The kernel may import `happy.core` and its ports, and nothing else. It cannot
see adapters, integrations, the runtime or the UI — so no vendor, no HTTP call
and no agent can reach in and adjust the rules it is judged by.

Six layers, each independently sufficient against the worst outcomes
(`ARCHITECTURE_V2.md` §5.1). This package implements layers 2 to 4: the deny
list, capability tokens and the approval gateway, with the audit chain and the
budget guard running underneath all of them. Layer 5 — instructions in a prompt
— is the weakest and is never relied upon.
"""

from happy.governance.action import ActionRequest
from happy.governance.audit import AuditChain, AuditDecision, AuditEvent
from happy.governance.budget_guard import (
    BudgetBreach,
    BudgetGuard,
    BudgetLimits,
    Reservation,
)
from happy.governance.capability import CapabilityToken, TokenIssuer
from happy.governance.classifier import Classification, ClassifierConfig, RiskClassifier
from happy.governance.denylist import RULE_IDS, T4_DENY_LIST, ProhibitionRule
from happy.governance.errors import (
    ApprovalInvalid,
    ApprovalRequired,
    AuditChainBroken,
    BudgetExceeded,
    CapabilityDenied,
    GovernanceError,
    KillSwitchEngaged,
    PolicyDenied,
    TokenInvalid,
)
from happy.governance.gateway import ApprovalGateway, ApprovalRecord, ApprovalStatus
from happy.governance.governed_port import GovernedPort
from happy.governance.kill_switch import KillSwitch
from happy.governance.policy import PolicyDecision, PolicyEngine, PolicyOutcome

__all__ = [
    "RULE_IDS",
    "T4_DENY_LIST",
    "ActionRequest",
    "ApprovalGateway",
    "ApprovalInvalid",
    "ApprovalRecord",
    "ApprovalRequired",
    "ApprovalStatus",
    "AuditChain",
    "AuditChainBroken",
    "AuditDecision",
    "AuditEvent",
    "BudgetBreach",
    "BudgetExceeded",
    "BudgetGuard",
    "BudgetLimits",
    "CapabilityDenied",
    "CapabilityToken",
    "Classification",
    "ClassifierConfig",
    "GovernanceError",
    "GovernedPort",
    "KillSwitch",
    "KillSwitchEngaged",
    "PolicyDecision",
    "PolicyDenied",
    "PolicyEngine",
    "PolicyOutcome",
    "ProhibitionRule",
    "Reservation",
    "RiskClassifier",
    "TokenInvalid",
    "TokenIssuer",
]
