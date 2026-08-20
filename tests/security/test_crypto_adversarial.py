"""Independent adversarial tests for the frozen governance crypto.

Written against the *claims* in the modules, not derived from the author's own
tests. Where a property does not hold, the test asserts the real behaviour and
is named for the gap, so the defect is recorded rather than hidden.

Scope: HMAC signing, token construction and verification, replay, the
hash-chained audit, canonical serialisation, timing-safe comparison, secret
handling, and authorisation boundaries.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from happy.core.capability import Capability
from happy.core.risk import RiskTier
from happy.governance.capability import (
    MIN_SECRET_BYTES,
    CapabilityToken,
    TokenIssuer,
)
from happy.governance.errors import TokenInvalid
from happy.governance.hashing import (
    GENESIS_HASH,
    canonical_json,
    chain_hash,
    digest,
    redact_secrets,
)

pytestmark = pytest.mark.policy

SECRET = b"\x01" * 32
OTHER_SECRET = b"\x02" * 32
NOW = datetime(2026, 8, 20, 12, 0, 0)


class FrozenClock:
    def __init__(self, at: datetime = NOW) -> None:
        self.at = at

    def now(self) -> datetime:
        return self.at

    def today(self):  # pragma: no cover - satisfies the Clock protocol
        return self.at.date()


def issuer(secret: bytes = SECRET, clock: FrozenClock | None = None) -> TokenIssuer:
    return TokenIssuer(secret, clock or FrozenClock())


def a_token(iss: TokenIssuer) -> CapabilityToken:
    return iss.issue(
        subject="research_analyst",
        capabilities=frozenset({Capability.NETWORK_READ}),
        port_ids=frozenset({"research_provider"}),
        max_tier=RiskTier.T1,
        budget_usd=Decimal("1.00"),
    )


# ==========================================================================
# HMAC signing and token verification
# ==========================================================================


class TestSigning:
    def test_signature_depends_on_the_secret(self) -> None:
        """A token minted under one secret must not verify under another."""
        token = a_token(issuer(SECRET))
        with pytest.raises(TokenInvalid, match="signature"):
            issuer(OTHER_SECRET).verify(token)

    def test_signature_is_a_keyed_mac_not_a_bare_hash(self) -> None:
        """An attacker who knows the payload must not be able to recompute it."""
        token = a_token(issuer())
        bare = hashlib.sha256(canonical_json(token.signing_payload()).encode()).hexdigest()
        assert token.signature != bare

    def test_signature_matches_an_independent_hmac_computation(self) -> None:
        """Reimplement the MAC from the spec and compare."""
        token = a_token(issuer())
        expected = hmac.new(
            SECRET, canonical_json(token.signing_payload()).encode("utf-8"), "sha256"
        ).hexdigest()
        assert hmac.compare_digest(expected, token.signature)

    def test_empty_signature_is_rejected(self) -> None:
        token = a_token(issuer()).model_copy(update={"signature": ""})
        with pytest.raises(TokenInvalid):
            issuer().verify(token)

    def test_near_miss_signature_is_rejected(self) -> None:
        token = a_token(issuer())
        flipped = ("0" if token.signature[0] != "0" else "1") + token.signature[1:]
        with pytest.raises(TokenInvalid):
            issuer().verify(token.model_copy(update={"signature": flipped}))

    def test_truncated_signature_is_rejected(self) -> None:
        token = a_token(issuer())
        with pytest.raises(TokenInvalid):
            issuer().verify(token.model_copy(update={"signature": token.signature[:32]}))

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("subject", "someone_else"),
            ("port_ids", frozenset({"payment_provider"})),
            ("capabilities", frozenset({Capability.NETWORK_WRITE})),
            ("operations", frozenset({"transfer"})),
            ("max_tier", RiskTier.T3),
            ("budget_usd", Decimal("999999")),
            ("venture_id", "other-venture"),
            ("token_id", "tok_forged"),
            ("expires_at", NOW + timedelta(days=365)),
            ("issued_at", NOW - timedelta(days=365)),
        ],
    )
    def test_every_signed_field_is_tamper_evident(self, field: str, value: object) -> None:
        """Widening any part of the grant must invalidate the signature."""
        token = a_token(issuer())
        tampered = token.model_copy(update={field: value})
        with pytest.raises(TokenInvalid, match="signature"):
            issuer().verify(tampered)

    def test_short_secret_is_refused_at_construction(self) -> None:
        with pytest.raises(ValueError, match="at least"):
            TokenIssuer(b"x" * (MIN_SECRET_BYTES - 1), FrozenClock())

    def test_uses_constant_time_comparison(self) -> None:
        """Behavioural check: verification must go through compare_digest."""
        import inspect

        source = inspect.getsource(TokenIssuer.verify)
        assert "compare_digest" in source
        assert "==" not in source.split("compare_digest")[0].split("signature")[-1]


class TestExpiry:
    def test_expired_token_is_rejected(self) -> None:
        clock = FrozenClock()
        token = a_token(issuer(clock=clock))
        clock.at = NOW + timedelta(hours=2)
        with pytest.raises(TokenInvalid, match="expired"):
            issuer(clock=clock).verify(token)

    def test_expiry_boundary_is_exclusive_of_the_instant_itself(self) -> None:
        """At exactly expires_at the token is already dead."""
        clock = FrozenClock()
        token = a_token(issuer(clock=clock))
        clock.at = token.expires_at
        with pytest.raises(TokenInvalid, match="expired"):
            issuer(clock=clock).verify(token)

    def test_token_valid_one_microsecond_before_expiry(self) -> None:
        clock = FrozenClock()
        token = a_token(issuer(clock=clock))
        clock.at = token.expires_at - timedelta(microseconds=1)
        issuer(clock=clock).verify(token)


class TestIssuanceBoundaries:
    def test_cannot_mint_a_forbidden_capability(self) -> None:
        with pytest.raises(ValueError, match="forbidden capability"):
            issuer().issue(
                subject="a",
                capabilities=frozenset({Capability.MONEY_MOVE}),
                port_ids=frozenset({"payment_provider"}),
            )

    def test_cannot_mint_a_t4_token(self) -> None:
        with pytest.raises(ValueError, match="T4"):
            issuer().issue(
                subject="a",
                capabilities=frozenset({Capability.NETWORK_READ}),
                port_ids=frozenset({"x"}),
                max_tier=RiskTier.T4,
            )

    def test_cannot_mint_a_token_with_no_ports(self) -> None:
        with pytest.raises(ValueError, match="authorises nothing"):
            issuer().issue(
                subject="a",
                capabilities=frozenset({Capability.NETWORK_READ}),
                port_ids=frozenset(),
            )

    def test_cannot_mint_a_non_expiring_token(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            issuer().issue(
                subject="a",
                capabilities=frozenset({Capability.NETWORK_READ}),
                port_ids=frozenset({"x"}),
                ttl=timedelta(0),
            )

    def test_empty_operations_means_any_operation(self) -> None:
        """Recorded because it is a footgun: the empty set is the WIDER grant."""
        token = a_token(issuer())
        assert token.operations == frozenset()
        assert token.permits_operation("anything_at_all") is True


# ==========================================================================
# Replay
# ==========================================================================


class TestReplay:
    def test_DEFECT_token_can_be_replayed_indefinitely_before_expiry(self) -> None:
        """FINDING: there is no nonce, no jti registry and no revocation.

        A token captured from the database, a log or an audit export can be
        presented any number of times until it expires. Verification is a pure
        function of (payload, secret, clock) and keeps no used-token state.
        """
        iss = issuer()
        token = a_token(iss)
        for _ in range(100):
            iss.verify(token)  # never refused

    def test_DEFECT_no_revocation_mechanism_exists(self) -> None:
        """FINDING: a leaked token cannot be withdrawn before its TTL."""
        assert not hasattr(TokenIssuer, "revoke")
        assert not hasattr(TokenIssuer, "is_revoked")

    def test_replay_window_is_bounded_only_by_ttl(self) -> None:
        """The single mitigation that does exist: a one-hour default TTL."""
        from happy.governance.capability import DEFAULT_TOKEN_TTL

        assert timedelta(hours=1) >= DEFAULT_TOKEN_TTL


# ==========================================================================
# Canonical serialisation
# ==========================================================================


class TestCanonicalisation:
    def test_key_order_does_not_change_the_digest(self) -> None:
        assert digest({"a": 1, "b": 2}) == digest({"b": 2, "a": 1})

    def test_types_are_distinguished(self) -> None:
        assert digest({"a": 1}) != digest({"a": "1"})
        assert digest({"a": None}) != digest({"a": "None"})

    def test_nesting_is_not_flattened(self) -> None:
        assert digest({"a": {"b": "c"}}) != digest({"a.b": "c"})

    def test_unicode_is_stable(self) -> None:
        assert digest({"k": "café"}) == digest({"k": "café"})

    def test_decimal_precision_is_preserved(self) -> None:
        """1.0 and 1.00 are different grants and must sign differently."""
        assert digest({"v": Decimal("1.0")}) != digest({"v": Decimal("1.00")})

    def test_sets_serialise_as_sorted_json_arrays(self) -> None:
        """FIXED (was a defect): `default=str` emitted Python's set repr.

        Sets now render as sorted JSON arrays, so the output depends only on
        content. Before the fix this produced `{"s":"{'b', 'a'}"}` with
        seed-dependent ordering.
        """
        assert canonical_json({"s": {"b", "a"}}) == '{"s":["a","b"]}'
        assert canonical_json({"s": frozenset({"b", "a"})}) == '{"s":["a","b"]}'

    def test_set_digest_is_stable_across_processes(self) -> None:
        """Regression guard for the fix, across three PYTHONHASHSEED values."""
        code = (
            "import sys; sys.path.insert(0, 'src');"
            "from happy.governance.hashing import digest;"
            "print(digest({'s': {'alpha','beta','gamma','delta','epsilon'}}))"
        )
        results = set()
        for seed in ("0", "1", "12345"):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            out = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True,
                text=True,
                env=env,
                cwd=os.getcwd(),
                check=True,
            )
            results.add(out.stdout.strip())
        assert len(results) == 1, f"digest is seed-dependent: {results}"

    def test_set_order_does_not_change_the_digest(self) -> None:
        assert digest({"s": {"a", "b", "c"}}) == digest({"s": {"c", "b", "a"}})

    def test_token_payload_avoids_the_set_defect(self) -> None:
        """The mitigation that makes the defect non-exploitable for tokens."""
        payload = a_token(issuer()).signing_payload()
        for value in payload.values():
            assert not isinstance(value, (set, frozenset))
        assert payload["capabilities"] == sorted(payload["capabilities"])
        assert payload["port_ids"] == sorted(payload["port_ids"])


# ==========================================================================
# Hash-chained audit
# ==========================================================================


class TestHashChain:
    def _chain(self, payloads: list[dict]) -> list[tuple[str, str, dict]]:
        entries = []
        prev = GENESIS_HASH
        for p in payloads:
            h = chain_hash(prev, p)
            entries.append((prev, h, p))
            prev = h
        return entries

    def test_entry_hash_covers_content(self) -> None:
        a = chain_hash(GENESIS_HASH, {"x": 1})
        b = chain_hash(GENESIS_HASH, {"x": 2})
        assert a != b

    def test_entry_hash_covers_position(self) -> None:
        """The same content at a different point in history hashes differently."""
        a = chain_hash(GENESIS_HASH, {"x": 1})
        b = chain_hash("f" * 64, {"x": 1})
        assert a != b

    def test_prev_hash_is_fixed_width_so_concatenation_is_unambiguous(self) -> None:
        """A variable-length prefix would allow a boundary-shifting collision."""
        assert len(GENESIS_HASH) == 64
        assert len(chain_hash(GENESIS_HASH, {"x": 1})) == 64

    def test_DEFECT_chain_is_unkeyed_so_it_can_be_recomputed(self) -> None:
        """FINDING: the chain is tamper-EVIDENT, not tamper-PROOF.

        `chain_hash` uses no secret, so anyone who can write to the audit store
        can alter an entry and recompute every hash after it. The chain detects
        careless edits and database corruption; it does not detect an attacker
        with write access and knowledge of the scheme.
        """
        original = self._chain([{"e": "a"}, {"e": "b"}, {"e": "c"}])
        forged = self._chain([{"e": "a"}, {"e": "TAMPERED"}, {"e": "c"}])
        # A verifier walking the forged chain finds it internally consistent.
        prev = GENESIS_HASH
        for prev_hash, entry_hash, payload in forged:
            assert prev_hash == prev
            assert entry_hash == chain_hash(prev_hash, payload)
            prev = entry_hash
        assert original[-1][1] != forged[-1][1], "only an external witness differs"

    def test_sha256_length_extension_is_not_exploitable_here(self) -> None:
        """No secret prefix, so the classic attack buys an attacker nothing."""
        import inspect

        source = inspect.getsource(chain_hash)
        assert "hmac" not in source  # confirms it is unkeyed, per the finding above
        assert "prev_hash + canonical_json" in source


# ==========================================================================
# Secret handling
# ==========================================================================


class TestSecretRedaction:
    @pytest.mark.parametrize(
        "secret",
        [
            "sk-ant-api03-abcdefghijklmnop",
            "sk-proj-abcdefghijklmnop",
            "ghp_abcdefghijklmnopqrstuvwxyz",
            "xoxb-1234567890-abcdefghij",
            "AKIAIOSFODNN7EXAMPLE",
            "-----BEGIN RSA PRIVATE KEY-----",
            "pk_live_abcdefghijklmnop",
        ],
    )
    def test_known_credential_shapes_are_redacted(self, secret: str) -> None:
        out = redact_secrets(f"authorization: {secret} trailing")
        assert secret not in out
        assert "[redacted]" in out

    @pytest.mark.parametrize(
        "secret",
        [
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abc123",  # JWT
            "AIzaSyA1234567890abcdefghijklmnopqrstu",  # Google API key
            "dop_v1_0123456789abcdef0123456789abcdef",  # DigitalOcean
            "postgres://user:hunter2@host:5432/db",  # password in a DSN
            "A" * 64,  # bare hex/base64 blob
        ],
    )
    def test_DEFECT_unknown_credential_shapes_survive_redaction(self, secret: str) -> None:
        """FINDING: redaction is an allowlist of six patterns, not a scanner.

        Its own docstring says so. Recorded because audit records are the
        artifact most likely to be exported, and anything not on the list
        travels with them.
        """
        assert secret in redact_secrets(f"value: {secret}")

    def test_signing_secret_is_not_exposed_on_the_issuer(self) -> None:
        iss = issuer()
        assert not hasattr(iss, "secret")
        assert "_secret" in vars(iss), "private by convention only"

    def test_token_repr_does_not_leak_the_secret(self) -> None:
        token = a_token(issuer())
        assert SECRET.hex() not in repr(token)
        assert SECRET.decode("latin-1") not in repr(token)

    def test_signing_payload_excludes_the_signature(self) -> None:
        """Signing over your own signature is a self-reference bug."""
        assert "signature" not in a_token(issuer()).signing_payload()


# ==========================================================================
# Authorisation boundaries
# ==========================================================================


class TestAuthorisationBoundary:
    def test_token_cannot_be_widened_by_copy(self) -> None:
        """A model_copy that widens scope must fail verification."""
        token = a_token(issuer())
        widened = token.model_copy(update={"port_ids": token.port_ids | {"payment_provider"}})
        with pytest.raises(TokenInvalid):
            issuer().verify(widened)

    def test_token_is_frozen(self) -> None:
        from pydantic import ValidationError

        token = a_token(issuer())
        with pytest.raises(ValidationError):
            token.subject = "someone_else"  # type: ignore[misc]

    def test_serialised_token_round_trips_and_still_verifies(self) -> None:
        token = a_token(issuer())
        restored = CapabilityToken.model_validate(json.loads(token.model_dump_json()))
        issuer().verify(restored)

    def test_round_tripped_token_cannot_be_edited_in_transit(self) -> None:
        token = a_token(issuer())
        raw = json.loads(token.model_dump_json())
        raw["budget_usd"] = "999999"
        with pytest.raises(TokenInvalid):
            issuer().verify(CapabilityToken.model_validate(raw))
