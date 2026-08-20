"""Provider terms, licensing and operational metadata.

Two distinctions drive the design of this module.

**Library licence is not service terms.** An MIT-licensed client for a paid API
grants nothing about the API. `DataSourceMetadata.license` describes the data;
the dependency's own licence is tracked separately in the license matrix.

**A port's contract is static; a provider's terms are not.** The `DataSource`
port is the same interface whether it is bound to SEC EDGAR (public domain) or
to a vendor whose terms forbid redistribution. Terms therefore live on the
bound instance, not on the abstract port.

Every tri-state field defaults to `UNKNOWN`, and `UNKNOWN` is treated as a
refusal by `happy.core.usage_policy`. Absence of evidence is not permission.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

DEFAULT_MAX_METADATA_AGE_DAYS = 180
"""Terms older than this are treated as unverified. Vendors change terms."""


class Permission(StrEnum):
    """A tri-state permission with an explicit unknown."""

    ALLOWED = "allowed"
    CONDITIONAL = "conditional"
    """Permitted only if the stated obligations are met (e.g. attribution)."""
    DENIED = "denied"
    UNKNOWN = "unknown"
    """UNKNOWN — REQUIRES REVIEW. Treated as DENIED until resolved."""


class CommercialUse(StrEnum):
    """Whether the source may be used in a commercial context."""

    PERMITTED = "permitted"
    REQUIRES_PAID_TIER = "requires_paid_tier"
    PROHIBITED = "prohibited"
    UNKNOWN = "unknown"
    """UNKNOWN — REQUIRES REVIEW. Treated as PROHIBITED until resolved."""


class CostKind(StrEnum):
    FREE = "free"
    FREEMIUM = "freemium"
    METERED = "metered"
    SUBSCRIPTION = "subscription"
    UNKNOWN = "unknown"


class AuthScheme(StrEnum):
    NONE = "none"
    API_KEY = "api_key"
    BEARER_TOKEN = "bearer_token"
    BASIC = "basic"
    OAUTH2 = "oauth2"
    SSH_KEY = "ssh_key"
    MTLS = "mtls"
    UNKNOWN = "unknown"


_SECRET_SHAPED = re.compile(
    r"(sk-|pk_|ghp_|xox[baprs]-|AKIA[0-9A-Z]{12,}|-----BEGIN)|^[A-Za-z0-9+/]{40,}={0,2}$"
)


class CostModel(BaseModel):
    """What an operation costs, in money rather than tokens."""

    model_config = ConfigDict(frozen=True)

    kind: CostKind = CostKind.UNKNOWN
    currency: str = "USD"
    unit: str | None = None
    """e.g. 'per_request', 'per_1k_input_tokens', 'per_month'."""
    amount: Decimal | None = None
    monthly_minimum: Decimal | None = None
    free_tier_notes: str = ""

    @property
    def is_free(self) -> bool:
        return self.kind is CostKind.FREE

    @property
    def requires_payment(self) -> bool:
        return self.kind in (CostKind.METERED, CostKind.SUBSCRIPTION)


class RateLimit(BaseModel):
    """Declared rate limits.

    A limit that is entirely undeclared is not the same as no limit. `declared`
    distinguishes them so callers can be conservative about the unknown case.
    """

    model_config = ConfigDict(frozen=True)

    requests: int | None = None
    window_seconds: int | None = None
    daily_quota: int | None = None
    concurrent: int | None = None
    burst: int | None = None
    notes: str = ""

    @property
    def declared(self) -> bool:
        """True when at least one concrete limit is known."""
        return any(
            v is not None
            for v in (self.requests, self.daily_quota, self.concurrent, self.burst)
        )

    @property
    def requests_per_second(self) -> float | None:
        if self.requests is None or not self.window_seconds:
            return None
        return self.requests / self.window_seconds

    @classmethod
    def unknown(cls, notes: str = "not documented by provider") -> RateLimit:
        return cls(notes=notes)


class AuthRequirement(BaseModel):
    """What credentials an adapter needs — by name, never by value."""

    model_config = ConfigDict(frozen=True)

    scheme: AuthScheme = AuthScheme.UNKNOWN
    required: bool = True
    credential_keys: tuple[str, ...] = ()
    """Environment variable or keyring entry NAMES. Never secret values."""
    scopes: tuple[str, ...] = ()
    supports_read_only_credential: bool = False
    """True when the provider can issue a credential that cannot write."""
    notes: str = ""

    @field_validator("credential_keys")
    @classmethod
    def _reject_secret_values(cls, keys: tuple[str, ...]) -> tuple[str, ...]:
        """Refuse anything that looks like a credential rather than its name.

        This is a guardrail, not a scanner. It exists because a descriptor is
        serialised into audit records, and a secret pasted here would leak into
        the audit log — the one place we most need to be safe to export.
        """
        for key in keys:
            if _SECRET_SHAPED.search(key):
                raise ValueError(
                    f"credential_keys must contain names, not values; {key[:8]!r}… "
                    "looks like a secret"
                )
            if not key.replace("_", "").replace("-", "").isalnum():
                raise ValueError(f"credential key {key!r} is not a plausible name")
        return keys

    @classmethod
    def none(cls) -> AuthRequirement:
        return cls(scheme=AuthScheme.NONE, required=False)


class ProviderTerms(BaseModel):
    """Terms common to every bound provider, whatever the port."""

    model_config = ConfigDict(frozen=True)

    provider: str
    terms_url: str | None = None
    commercial_use: CommercialUse = CommercialUse.UNKNOWN
    redistribution_allowed: Permission = Permission.UNKNOWN
    attribution_required: bool = True
    """Defaults to True: attributing when unnecessary is harmless."""
    authentication_required: bool = True
    cost: CostModel = Field(default_factory=CostModel)
    rate_limit: RateLimit = Field(default_factory=RateLimit)
    last_verified: date
    notes: str = ""

    def is_stale(
        self,
        *,
        today: date,
        max_age_days: int = DEFAULT_MAX_METADATA_AGE_DAYS,
    ) -> bool:
        """True when these terms are too old to rely on."""
        return today - self.last_verified > timedelta(days=max_age_days)

    def age_days(self, *, today: date) -> int:
        return (today - self.last_verified).days

    def attribution_text(self) -> str:
        """Human-readable attribution string, for use where it is required."""
        return self.provider if not self.terms_url else f"{self.provider} ({self.terms_url})"


class DataSourceMetadata(ProviderTerms):
    """Licensing and usage terms for one data source.

    This is the record the policy engine reads to decide whether an intended
    operation is permitted. Every field the audit called for is present, and
    every permission field fails closed.
    """

    model_config = ConfigDict(frozen=True)

    source_name: str
    license: str = "UNKNOWN — REQUIRES REVIEW"
    """SPDX identifier where one applies, or a description of the data terms."""
    derived_data_allowed: Permission = Permission.UNKNOWN
    """Whether analysis *derived* from the data may be used or shared."""

    @property
    def source_id(self) -> str:
        """Stable identifier used in provenance records and audit events."""
        return f"{self.provider}:{self.source_name}"

    def attribution_text(self) -> str:
        parts = [f"{self.provider} — {self.source_name}"]
        if self.license and not self.license.startswith("UNKNOWN"):
            parts.append(self.license)
        if self.terms_url:
            parts.append(self.terms_url)
        return ", ".join(parts)

    @property
    def requires_review(self) -> bool:
        """True when any permission-bearing field is unresolved."""
        return (
            self.commercial_use is CommercialUse.UNKNOWN
            or self.redistribution_allowed is Permission.UNKNOWN
            or self.derived_data_allowed is Permission.UNKNOWN
            or self.license.startswith("UNKNOWN")
        )
