"""T4 — the actions that have no approval path.

This is enforcement layer 2 of `ARCHITECTURE_V2.md` §5.1, and the mechanism
behind `DEVELOPMENT_PLAN.md` §8.1. Three things about it are deliberate:

**It is data, not prose.** Every prohibition in the plan appears here as a rule
a test can assert against. Prompt-level instruction is layer 5 and is never
relied upon.

**It matches whole words, not substrings.** `complete` must not trigger a rule
written for `complete_purchase`, and `read_file` must not trigger one written
for a tax `filing`. Operation names are split on `_` and matched as words.

**It catches operations that do not exist yet.** A port cannot declare
`Capability.MONEY_MOVE` — `OperationSpec` refuses it — so by the time an action
reaches this module the obvious route is already closed. What remains is an
adapter inventing a plausible-looking method later, which is exactly what the
word rules are for.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from happy.core.capability import Capability
from happy.core.errors import ProhibitedAction
from happy.core.ports.base import PORT_REGISTRY
from happy.governance.action import ActionRequest


class ProhibitionRule(BaseModel):
    """One T4 rule. Matching it ends the action; there is no appeal."""

    model_config = ConfigDict(frozen=True)

    rule_id: str
    description: str
    rationale: str

    port_ids: frozenset[str] = frozenset()
    """Scopes the rule to these ports. Empty means every port."""
    operations: frozenset[str] = frozenset()
    """Exact operation names."""
    name_words: frozenset[str] = frozenset()
    """Words which, if they appear in an operation name, trigger the rule."""
    capability_sets: tuple[frozenset[Capability], ...] = ()
    """Capability combinations. A request holding all of any one set triggers."""

    def matches(self, request: ActionRequest) -> bool:
        if self.port_ids and request.port_id not in self.port_ids:
            return False

        has_matcher = bool(self.operations or self.name_words or self.capability_sets)
        if not has_matcher:
            # A port-scoped rule with no further matcher denies the whole port.
            return bool(self.port_ids)

        if request.operation in self.operations:
            return True
        if self.name_words & request.name_words:
            return True
        return any(
            required <= request.capabilities
            for required in self.capability_sets
            if required
        )


T4_DENY_LIST: tuple[ProhibitionRule, ...] = (
    ProhibitionRule(
        rule_id="money_movement",
        description="Initiating or authorising any movement of money.",
        rationale=(
            "The Chairman transacts; the system analyses. No approval raises an "
            "agent's authority to move value, so no approval path exists."
        ),
        name_words=frozenset(
            {
                "transfer",
                "payout",
                "payouts",
                "refund",
                "refunds",
                "charge",
                "debit",
                "wire",
                "remit",
                "disburse",
                "withdraw",
                "purchase",
                "checkout",
                "invoice",
                "pay",
                "payment",
            }
        ),
        capability_sets=(frozenset({Capability.MONEY_MOVE}),),
    ),
    ProhibitionRule(
        rule_id="contract_execution",
        description="Signing, accepting or agreeing to a binding commitment.",
        rationale=(
            "A contract binds a legal person. The system is not one, and cannot "
            "acquire the standing by being approved."
        ),
        name_words=frozenset(
            {"sign", "agree", "contract", "accept", "terms", "notarize", "countersign"}
        ),
    ),
    ProhibitionRule(
        rule_id="borrowing_and_credit",
        description="Borrowing, applying for credit, or incurring debt.",
        rationale="Debt is an irreversible obligation on the Chairman personally.",
        name_words=frozenset(
            {"borrow", "loan", "credit", "debt", "mortgage", "financing", "underwrite"}
        ),
    ),
    ProhibitionRule(
        rule_id="securities_issuance",
        description="Issuing, offering or transacting in securities.",
        rationale="Securities activity is regulated conduct with personal liability.",
        name_words=frozenset(
            {"securities", "equity", "shares", "stock", "ico", "offering", "prospectus"}
        ),
    ),
    ProhibitionRule(
        rule_id="autonomous_trading",
        description="Placing orders, executing trades, or connecting a brokerage.",
        rationale=(
            "Added after the upstream audit: a research system grows an execution "
            "capability very naturally. This one cannot — there is no exchange "
            "integration, no brokerage adapter and no order port."
        ),
        name_words=frozenset(
            {"trade", "trading", "order", "brokerage", "exchange", "portfolio", "rebalance"}
        ),
    ),
    ProhibitionRule(
        rule_id="regulatory_filing",
        description="Filing legal, tax or regulatory documents.",
        rationale="A filing is a sworn statement by a person, not an output of a model.",
        name_words=frozenset(
            {"filing", "filings", "tax", "irs", "hmrc", "vat", "regulatory", "regulator"}
        ),
    ),
    ProhibitionRule(
        rule_id="entity_and_representation",
        description="Creating legal entities or acting as a company representative.",
        rationale=(
            "Representation implies authority the Chairman cannot delegate to "
            "software, whatever the dashboard says."
        ),
        name_words=frozenset(
            {
                "incorporate",
                "incorporation",
                "entity",
                "llc",
                "trademark",
                "patent",
                "represent",
                "behalf",
                "attorney",
            }
        ),
    ),
    ProhibitionRule(
        rule_id="financial_rail_access",
        description="Any call against a payment, banking, brokerage or exchange API.",
        rationale=(
            "Layer 0 already withholds these credentials. This rule makes the "
            "attempt itself a refusal, so it is logged rather than merely failing."
        ),
        name_words=frozenset(
            {"bank", "banking", "ach", "sepa", "iban", "plaid", "stripe", "paypal"}
        ),
    ),
    ProhibitionRule(
        rule_id="irreversible_destruction",
        description="Destroying data or rewriting shared history.",
        rationale=(
            "Irreversibility is the whole objection: no approval can restore what "
            "a force-push or a purge removed."
        ),
        operations=frozenset(
            {
                "force_push",
                "push_to_default_branch",
                "delete_branch",
                "delete_environment",
                "delete_repository",
                "delete_messages",
                "drop_database",
            }
        ),
        name_words=frozenset(
            {"purge", "truncate", "wipe", "destroy", "erase", "shred", "force"}
        ),
    ),
    ProhibitionRule(
        rule_id="governance_bypass",
        description="Disabling, editing or working around the governance kernel.",
        rationale=(
            "A system that can widen its own authority has none. The kernel is "
            "changed by a reviewed commit, never at runtime."
        ),
        operations=frozenset(
            {
                "disable_governance",
                "edit_deny_list",
                "modify_policy",
                "issue_token",
                "grant_capability",
                "delete_audit",
                "rewrite_audit",
                "release_kill_switch",
            }
        ),
        name_words=frozenset(
            {"bypass", "impersonate", "spoof", "forge", "captcha", "exfiltrate"}
        ),
    ),
    ProhibitionRule(
        rule_id="credential_exfiltration",
        description="Sending secrets outward.",
        rationale=(
            "Reading a secret is ordinary; reading one while holding an outward "
            "channel is the exfiltration shape, and is refused on the combination."
        ),
        capability_sets=(
            frozenset({Capability.SECRET_READ, Capability.EXTERNAL_PUBLISH}),
            frozenset({Capability.SECRET_READ, Capability.OUTBOUND_MESSAGE}),
            frozenset({Capability.SECRET_READ, Capability.NETWORK_WRITE}),
        ),
    ),
)
"""Every T4 rule. `DEVELOPMENT_PLAN.md` §8.1 maps one-to-one onto these ids."""

RULE_IDS: frozenset[str] = frozenset(rule.rule_id for rule in T4_DENY_LIST)


def _port_declared_prohibition(
    request: ActionRequest, extra: frozenset[str]
) -> ProhibitionRule | None:
    """Honour the port's own `prohibited_operations`.

    The port declares what it will never do; the kernel repeats the refusal
    independently, so a caller that reached the kernel without going through
    `GovernedPort` is still stopped.
    """
    declared = set(extra)
    port_cls = PORT_REGISTRY.get(request.port_id)
    if port_cls is not None:
        declared |= set(port_cls.descriptor.prohibited_names)

    if request.operation not in declared:
        return None

    reason = ""
    if port_cls is not None:
        for prohibited in port_cls.descriptor.prohibited_operations:
            if prohibited.name == request.operation:
                reason = prohibited.reason
                break

    return ProhibitionRule(
        rule_id="port_declared_prohibition",
        description=f"{request.port_id} declares {request.operation!r} prohibited.",
        rationale=reason or "Declared prohibited by the port that would perform it.",
        port_ids=frozenset({request.port_id}),
        operations=frozenset({request.operation}),
    )


def evaluate(
    request: ActionRequest,
    *,
    prohibited_names: frozenset[str] = frozenset(),
) -> ProhibitionRule | None:
    """Return the rule this request violates, or None.

    Args:
        request: the action being attempted.
        prohibited_names: additional names the calling port declares prohibited,
            for ports not present in the global registry.
    """
    declared = _port_declared_prohibition(request, prohibited_names)
    if declared is not None:
        return declared

    for rule in T4_DENY_LIST:
        if rule.matches(request):
            return rule
    return None


def assert_permitted(
    request: ActionRequest,
    *,
    prohibited_names: frozenset[str] = frozenset(),
) -> None:
    """Raise `ProhibitedAction` if the request is T4.

    Raises:
        ProhibitedAction: always, when a rule matches. There is no variant of
            this call that takes an approval.
    """
    rule = evaluate(request, prohibited_names=prohibited_names)
    if rule is not None:
        raise ProhibitedAction(
            request.action_id, f"{rule.rule_id}: {rule.description} {rule.rationale}"
        )
