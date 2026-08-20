"""The guarantee: AUTHORIZED_SPEND <= CONFIGURED_LIMIT, always.

Adversarial by construction. Every test here tries to get more money out of the
store than it was given, by whatever route: concurrency, restart, lying about
cost, replaying a request, or asking for something that cannot be priced.

The invariant is asserted on **authorised** spend — what the store agreed to
before the provider was contacted — because that is the only quantity the
circuit breaker controls. A provider that charges more than it was bounded to
is an anomaly, detected and recorded separately (see `test_provider_overrun_*`).
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from happy.governance.budget_store import BudgetStore, to_nano
from happy.governance.errors import AuditChainBroken, BudgetExceeded
from happy.governance.spend_gate import (
    Pricing,
    SpendGate,
    Unpriceable,
    estimate_max_cost,
)

pytestmark = pytest.mark.policy

NOW = datetime(2026, 8, 20, 12, 0, 0)
PRICING = Pricing(Decimal("0.000002"), Decimal("0.00001"))


@pytest.fixture
def store(tmp_path) -> BudgetStore:
    return BudgetStore(tmp_path / "budget.db")


def _all_limits(store: BudgetStore, amount: str = "1.00") -> dict[str, str]:
    """Declare every scope so a reservation can name all six."""
    scopes = {
        "request": "per-call",
        "agent": "research_analyst",
        "task": "task-1",
        "daily": "2026-08-20",
        "monthly": "2026-08",
        "company": "global",
    }
    for scope, key in scopes.items():
        store.set_limit(scope, key, amount)
    return scopes


# --------------------------------------------------------------------------
# The headline invariant, under concurrency
# --------------------------------------------------------------------------


class TestConcurrencyInvariant:
    def test_eight_workers_cannot_exceed_the_limit(self, tmp_path) -> None:
        """8 workers, 60 attempts each, against a budget that fits exactly 20."""
        db = tmp_path / "concurrent.db"
        BudgetStore(db).set_limit("company", "global", "1.00")

        per_call = Decimal("0.05")  # 1.00 / 0.05 = exactly 20 authorisations
        authorised: list[str] = []
        lock = threading.Lock()
        errors: list[BaseException] = []

        def worker(n: int) -> None:
            store = BudgetStore(db)  # its own connection, as a real process would
            for i in range(60):
                rid = f"w{n}-{i}"
                try:
                    store.reserve(
                        request_id=rid,
                        amount_usd=per_call,
                        scopes={"company": "global"},
                        now=NOW,
                    )
                except BudgetExceeded:
                    continue
                except sqlite3.OperationalError as exc:  # lock contention
                    with lock:
                        errors.append(exc)
                    continue
                with lock:
                    authorised.append(rid)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        store = BudgetStore(db)
        committed = store.committed("company", "global")

        assert not errors, f"lock contention leaked errors: {errors[:3]}"
        assert len(authorised) == 20, (
            f"expected exactly 20 authorisations, got {len(authorised)}"
        )
        assert committed == Decimal("1.000000000")
        assert committed <= Decimal("1.00"), "AUTHORIZED_SPEND exceeded CONFIGURED_LIMIT"

    def test_concurrent_settlement_never_drives_reserved_negative(self, tmp_path) -> None:
        db = tmp_path / "settle.db"
        store = BudgetStore(db)
        store.set_limit("company", "global", "10.00")
        reservations = [
            store.reserve(
                request_id=f"r{i}",
                amount_usd=Decimal("0.10"),
                scopes={"company": "global"},
                now=NOW,
            )
            for i in range(20)
        ]

        def settle(idx: int) -> None:
            BudgetStore(db).settle(reservations[idx], Decimal("0.01"), now=NOW)

        threads = [threading.Thread(target=settle, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        row = (
            BudgetStore(db)
            ._connect()
            .execute("SELECT settled_nano, reserved_nano FROM spend WHERE scope='company'")
            .fetchone()
        )
        assert row[1] == 0, "all reservations released"
        assert row[0] == to_nano(Decimal("0.20")), "20 x 0.01 settled"
        assert row[0] >= 0 and row[1] >= 0


# --------------------------------------------------------------------------
# Each of the six limits refuses independently
# --------------------------------------------------------------------------


class TestEachLimitEnforced:
    @pytest.mark.parametrize(
        ("scope", "key"),
        [
            ("request", "per-call"),
            ("agent", "research_analyst"),
            ("task", "task-1"),
            ("daily", "2026-08-20"),
            ("monthly", "2026-08"),
            ("company", "global"),
        ],
    )
    def test_limit_refuses_on_its_own(self, store: BudgetStore, scope: str, key: str) -> None:
        scopes = _all_limits(store, "10.00")
        store.set_limit(scope, key, "0.01")  # this one alone is tight

        with pytest.raises(BudgetExceeded) as exc:
            store.reserve(request_id="r1", amount_usd=Decimal("1.00"), scopes=scopes, now=NOW)
        assert exc.value.scope == scope
        assert exc.value.key == key

    def test_single_request_over_budget_is_refused(self, store: BudgetStore) -> None:
        scopes = _all_limits(store, "0.10")
        with pytest.raises(BudgetExceeded):
            store.reserve(request_id="big", amount_usd=Decimal("0.11"), scopes=scopes, now=NOW)
        assert store.committed("company", "global") == Decimal("0")

    def test_undeclared_scope_denies_rather_than_allows(self, store: BudgetStore) -> None:
        """No limit is not permission."""
        with pytest.raises(BudgetExceeded):
            store.reserve(
                request_id="r1",
                amount_usd=Decimal("0.01"),
                scopes={"agent": "never-configured"},
                now=NOW,
            )

    def test_reservation_must_name_a_scope(self, store: BudgetStore) -> None:
        with pytest.raises(ValueError, match="at least one scope"):
            store.reserve(request_id="r", amount_usd=Decimal("0.01"), scopes={}, now=NOW)

    def test_unknown_scope_name_rejected(self, store: BudgetStore) -> None:
        with pytest.raises(ValueError, match="unknown scopes"):
            store.reserve(
                request_id="r",
                amount_usd=Decimal("0.01"),
                scopes={"galaxy": "x"},
                now=NOW,
            )


# --------------------------------------------------------------------------
# Restart, crash and recovery
# --------------------------------------------------------------------------


class TestPersistenceAndRestart:
    def test_reservation_survives_restart(self, tmp_path) -> None:
        db = tmp_path / "restart.db"
        first = BudgetStore(db)
        first.set_limit("company", "global", "1.00")
        first.reserve(
            request_id="r1",
            amount_usd=Decimal("0.60"),
            scopes={"company": "global"},
            now=NOW,
        )
        del first

        reopened = BudgetStore(db)  # a new process
        assert reopened.committed("company", "global") == Decimal("0.600000000")
        assert reopened.open_reservations() == ("r1",)

        # The held budget is genuinely unavailable to the next request.
        with pytest.raises(BudgetExceeded):
            reopened.reserve(
                request_id="r2",
                amount_usd=Decimal("0.50"),
                scopes={"company": "global"},
                now=NOW,
            )

    def test_crashed_reservation_holds_budget_until_it_expires(self, tmp_path) -> None:
        """A crash must cost headroom, never control."""
        db = tmp_path / "crash.db"
        store = BudgetStore(db, ttl=timedelta(minutes=15))
        store.set_limit("company", "global", "1.00")
        store.reserve(
            request_id="orphan",
            amount_usd=Decimal("0.90"),
            scopes={"company": "global"},
            now=NOW,
        )

        # Still held five minutes later.
        assert store.expire_stale(NOW + timedelta(minutes=5)) == 0
        assert store.committed("company", "global") == Decimal("0.900000000")

        # Reclaimed once the TTL passes.
        assert store.expire_stale(NOW + timedelta(minutes=16)) == 1
        assert store.committed("company", "global") == Decimal("0")
        assert store.open_reservations() == ()

    def test_settled_spend_survives_restart(self, tmp_path) -> None:
        db = tmp_path / "settled.db"
        s1 = BudgetStore(db)
        s1.set_limit("daily", "2026-08-20", "1.00")
        r = s1.reserve(
            request_id="r1",
            amount_usd=Decimal("0.50"),
            scopes={"daily": "2026-08-20"},
            now=NOW,
        )
        s1.settle(r, Decimal("0.03"), now=NOW)
        assert BudgetStore(db).settled("daily", "2026-08-20") == Decimal("0.030000000")


# --------------------------------------------------------------------------
# Hostile and malformed provider responses
# --------------------------------------------------------------------------


class TestUntrustedCost:
    @pytest.mark.parametrize(
        "reported",
        [None, "not-a-number", float("nan"), float("inf"), Decimal("-1"), -0.5, object()],
    )
    def test_untrusted_cost_settles_at_the_reserved_maximum(
        self, store: BudgetStore, reported: object
    ) -> None:
        """We charge ourselves the maximum we authorised, never less."""
        store.set_limit("company", "global", "1.00")
        r = store.reserve(
            request_id="r1",
            amount_usd=Decimal("0.20"),
            scopes={"company": "global"},
            now=NOW,
        )
        charged = store.settle(r, reported, now=NOW)  # type: ignore[arg-type]
        assert charged == r.amount_usd
        assert store.settled("company", "global") == r.amount_usd

    def test_provider_overrun_is_recorded_not_hidden(self, store: BudgetStore) -> None:
        """Charging more than bounded is an anomaly: record the truth."""
        store.set_limit("company", "global", "1.00")
        r = store.reserve(
            request_id="r1",
            amount_usd=Decimal("0.10"),
            scopes={"company": "global"},
            now=NOW,
        )
        charged = store.settle(r, Decimal("0.90"), now=NOW)
        assert charged == Decimal("0.900000000")
        detail = next(e for e in store.audit_entries() if e["event"] == "settle")["detail"]
        assert "overrun" in detail

    def test_overrun_closes_the_budget_to_further_spend(self, store: BudgetStore) -> None:
        store.set_limit("company", "global", "1.00")
        r = store.reserve(
            request_id="r1",
            amount_usd=Decimal("0.10"),
            scopes={"company": "global"},
            now=NOW,
        )
        store.settle(r, Decimal("1.50"), now=NOW)  # provider overcharged past the limit
        with pytest.raises(BudgetExceeded):
            store.reserve(
                request_id="r2",
                amount_usd=Decimal("0.01"),
                scopes={"company": "global"},
                now=NOW,
            )

    def test_zero_cost_is_trusted_and_settles_at_zero(self, store: BudgetStore) -> None:
        store.set_limit("company", "global", "1.00")
        r = store.reserve(
            request_id="r1",
            amount_usd=Decimal("0.10"),
            scopes={"company": "global"},
            now=NOW,
        )
        assert store.settle(r, Decimal("0"), now=NOW) == Decimal("0")
        assert store.committed("company", "global") == Decimal("0")


# --------------------------------------------------------------------------
# Replay, double-settle, bypass
# --------------------------------------------------------------------------


class TestNoBypass:
    def test_the_same_request_cannot_reserve_twice(self, store: BudgetStore) -> None:
        store.set_limit("company", "global", "1.00")
        store.reserve(
            request_id="dup",
            amount_usd=Decimal("0.10"),
            scopes={"company": "global"},
            now=NOW,
        )
        with pytest.raises(ValueError, match="already authorised"):
            store.reserve(
                request_id="dup",
                amount_usd=Decimal("0.10"),
                scopes={"company": "global"},
                now=NOW,
            )

    def test_a_reservation_settles_exactly_once(self, store: BudgetStore) -> None:
        store.set_limit("company", "global", "1.00")
        r = store.reserve(
            request_id="r1",
            amount_usd=Decimal("0.10"),
            scopes={"company": "global"},
            now=NOW,
        )
        store.settle(r, Decimal("0.01"), now=NOW)
        with pytest.raises(ValueError, match="settles exactly once"):
            store.settle(r, Decimal("0.01"), now=NOW)

    def test_releasing_twice_is_harmless(self, store: BudgetStore) -> None:
        store.set_limit("company", "global", "1.00")
        r = store.reserve(
            request_id="r1",
            amount_usd=Decimal("0.10"),
            scopes={"company": "global"},
            now=NOW,
        )
        store.release(r, now=NOW, reason="first")
        store.release(r, now=NOW, reason="second")
        assert store.committed("company", "global") == Decimal("0")

    def test_settling_an_unknown_reservation_is_refused(self, store: BudgetStore) -> None:
        from happy.governance.budget_store import Reservation

        fake = Reservation("rsv_fake", "fake", 1000, (("company", "global"),), NOW)
        with pytest.raises(ValueError, match="unknown reservation"):
            store.settle(fake, Decimal("0.01"), now=NOW)


# --------------------------------------------------------------------------
# Money arithmetic
# --------------------------------------------------------------------------


class TestMoneyArithmetic:
    def test_sub_nanodollar_costs_round_up_not_to_zero(self) -> None:
        """A cost rounding to zero would let infinite requests through."""
        assert to_nano(Decimal("0.0000000001")) == 1

    def test_exact_amounts_do_not_gain_a_nanodollar(self) -> None:
        assert to_nano(Decimal("0.000000001")) == 1
        assert to_nano(Decimal("1.00")) == 1_000_000_000

    @pytest.mark.parametrize("bad", ["nan", "inf", "-inf", "-0.01", "abc", None])
    def test_invalid_amounts_are_rejected(self, bad: object) -> None:
        with pytest.raises(ValueError):
            to_nano(bad)  # type: ignore[arg-type]

    def test_no_float_drift_over_many_settlements(self, store: BudgetStore) -> None:
        store.set_limit("company", "global", "1.00")
        for i in range(100):
            r = store.reserve(
                request_id=f"r{i}",
                amount_usd=Decimal("0.001"),
                scopes={"company": "global"},
                now=NOW,
            )
            store.settle(r, Decimal("0.001"), now=NOW)
        assert store.settled("company", "global") == Decimal("0.100000000")

    def test_negative_limit_rejected(self, store: BudgetStore) -> None:
        with pytest.raises(ValueError):
            store.set_limit("company", "global", "-1.00")


# --------------------------------------------------------------------------
# Estimation is a bound, not a guess
# --------------------------------------------------------------------------


class TestEstimation:
    def test_bound_includes_margin_and_full_output(self) -> None:
        bound = estimate_max_cost(
            input_tokens=100,
            max_output_tokens=512,
            pricing=PRICING,
            input_margin=Decimal("0.25"),
        )
        # 125 padded input x 2e-6  +  512 x 1e-5
        assert bound == Decimal("125") * Decimal("0.000002") + Decimal("512") * Decimal(
            "0.00001"
        )

    def test_bound_exceeds_any_plausible_actual(self) -> None:
        bound = estimate_max_cost(input_tokens=100, max_output_tokens=512, pricing=PRICING)
        actual_if_output_maxed = (
            Decimal(100) * PRICING.input_cost_per_token
            + Decimal(512) * PRICING.output_cost_per_token
        )
        assert bound > actual_if_output_maxed

    def test_zero_output_bound_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="output bound"):
            estimate_max_cost(input_tokens=10, max_output_tokens=0, pricing=PRICING)

    def test_negative_pricing_rejected(self) -> None:
        with pytest.raises(ValueError):
            Pricing(Decimal("-1"), Decimal("0.00001"))


# --------------------------------------------------------------------------
# The gate: failure, timeout, unpriceable
# --------------------------------------------------------------------------


class TestSpendGate:
    def _gate(self, store: BudgetStore) -> SpendGate:
        return SpendGate(store, now=lambda: NOW)

    def test_happy_path_settles_actual_below_the_bound(self, store: BudgetStore) -> None:
        store.set_limit("company", "global", "1.00")
        out = self._gate(store).call(
            request_id="r1",
            scopes={"company": "global"},
            input_tokens=100,
            max_output_tokens=512,
            pricing=PRICING,
            invoke=lambda: {"cost": "0.0004"},
            cost_of=lambda r: r["cost"],
        )
        assert out.actual_usd == Decimal("0.000400000")
        assert out.actual_usd < out.authorised_usd
        assert store.committed("company", "global") == out.actual_usd

    def test_failed_call_releases_the_whole_hold(self, store: BudgetStore) -> None:
        store.set_limit("company", "global", "1.00")

        def boom() -> None:
            raise RuntimeError("provider 500")

        with pytest.raises(RuntimeError):
            self._gate(store).call(
                request_id="r1",
                scopes={"company": "global"},
                input_tokens=100,
                max_output_tokens=512,
                pricing=PRICING,
                invoke=boom,
                cost_of=lambda r: "0",
            )
        assert store.committed("company", "global") == Decimal("0")

    def test_timeout_releases_the_hold(self, store: BudgetStore) -> None:
        store.set_limit("company", "global", "1.00")

        def slow() -> None:
            raise TimeoutError("timed out after 30s")

        with pytest.raises(TimeoutError):
            self._gate(store).call(
                request_id="r1",
                scopes={"company": "global"},
                input_tokens=100,
                max_output_tokens=512,
                pricing=PRICING,
                invoke=slow,
                cost_of=lambda r: "0",
            )
        assert store.committed("company", "global") == Decimal("0")
        assert [e["event"] for e in store.audit_entries()][-1] == "release"

    def test_unknown_model_price_denies_without_calling(self, store: BudgetStore) -> None:
        store.set_limit("company", "global", "1.00")
        called = []
        with pytest.raises(Unpriceable, match="no pricing"):
            self._gate(store).call(
                request_id="r1",
                scopes={"company": "global"},
                input_tokens=100,
                max_output_tokens=512,
                pricing=None,
                invoke=lambda: called.append(1),
                cost_of=lambda r: "0",
            )
        assert called == [], "the provider must not be contacted"

    def test_missing_token_estimate_denies_without_calling(self, store: BudgetStore) -> None:
        store.set_limit("company", "global", "1.00")
        called = []
        with pytest.raises(Unpriceable, match="token count"):
            self._gate(store).call(
                request_id="r1",
                scopes={"company": "global"},
                input_tokens=None,
                max_output_tokens=512,
                pricing=PRICING,
                invoke=lambda: called.append(1),
                cost_of=lambda r: "0",
            )
        assert called == []

    def test_budget_denial_never_reaches_the_provider(self, store: BudgetStore) -> None:
        store.set_limit("company", "global", "0.000001")
        called = []
        with pytest.raises(BudgetExceeded):
            self._gate(store).call(
                request_id="r1",
                scopes={"company": "global"},
                input_tokens=100,
                max_output_tokens=512,
                pricing=PRICING,
                invoke=lambda: called.append(1),
                cost_of=lambda r: "0",
            )
        assert called == []

    def test_cost_reader_that_throws_settles_at_maximum(self, store: BudgetStore) -> None:
        store.set_limit("company", "global", "1.00")

        def explode(_response: object) -> Decimal:
            raise KeyError("usage")

        out = self._gate(store).call(
            request_id="r1",
            scopes={"company": "global"},
            input_tokens=100,
            max_output_tokens=512,
            pricing=PRICING,
            invoke=lambda: {"no": "usage"},
            cost_of=explode,
        )
        assert out.actual_usd == out.authorised_usd

    def test_gate_enforces_all_six_scopes_together(self, store: BudgetStore) -> None:
        scopes = _all_limits(store, "10.00")
        store.set_limit("task", "task-1", "0.001")
        with pytest.raises(BudgetExceeded) as exc:
            self._gate(store).call(
                request_id="r1",
                scopes=scopes,
                input_tokens=100,
                max_output_tokens=512,
                pricing=PRICING,
                invoke=lambda: {},
                cost_of=lambda r: "0",
            )
        assert exc.value.scope == "task"


# --------------------------------------------------------------------------
# Audit
# --------------------------------------------------------------------------


class TestAudit:
    def test_every_reservation_and_settlement_is_recorded(self, store: BudgetStore) -> None:
        store.set_limit("company", "global", "1.00")
        r = store.reserve(
            request_id="r1",
            amount_usd=Decimal("0.10"),
            scopes={"company": "global"},
            now=NOW,
        )
        store.settle(r, Decimal("0.01"), now=NOW)
        with pytest.raises(BudgetExceeded):
            store.reserve(
                request_id="r2",
                amount_usd=Decimal("99"),
                scopes={"company": "global"},
                now=NOW,
            )
        events = [e["event"] for e in store.audit_entries()]
        assert events == ["reserve.granted", "settle", "reserve.denied"]

    def test_denial_is_audited_even_though_it_raises(self, store: BudgetStore) -> None:
        """A refusal that leaves no trace is a refusal nobody can review."""
        store.set_limit("company", "global", "0.01")
        with pytest.raises(BudgetExceeded):
            store.reserve(
                request_id="r1",
                amount_usd=Decimal("1.00"),
                scopes={"company": "global"},
                now=NOW,
            )
        assert [e["event"] for e in store.audit_entries()] == ["reserve.denied"]

    def test_chain_verifies(self, store: BudgetStore) -> None:
        store.set_limit("company", "global", "1.00")
        for i in range(5):
            r = store.reserve(
                request_id=f"r{i}",
                amount_usd=Decimal("0.01"),
                scopes={"company": "global"},
                now=NOW,
            )
            store.settle(r, Decimal("0.001"), now=NOW)
        store.verify_audit()

    def test_tampering_with_an_entry_is_detected(self, store: BudgetStore) -> None:
        store.set_limit("company", "global", "1.00")
        r = store.reserve(
            request_id="r1",
            amount_usd=Decimal("0.10"),
            scopes={"company": "global"},
            now=NOW,
        )
        store.settle(r, Decimal("0.01"), now=NOW)
        store._connect().execute("UPDATE audit SET amount_nano = 1 WHERE seq = 1")
        with pytest.raises(AuditChainBroken):
            store.verify_audit()

    def test_deleting_an_entry_is_detected(self, store: BudgetStore) -> None:
        store.set_limit("company", "global", "1.00")
        for i in range(3):
            store.reserve(
                request_id=f"r{i}",
                amount_usd=Decimal("0.01"),
                scopes={"company": "global"},
                now=NOW,
            )
        store._connect().execute("DELETE FROM audit WHERE seq = 2")
        with pytest.raises(AuditChainBroken):
            store.verify_audit()

    def test_persisted_audit_survives_restart_and_verifies(self, tmp_path) -> None:
        db = tmp_path / "audit.db"
        s1 = BudgetStore(db)
        s1.set_limit("company", "global", "1.00")
        s1.reserve(
            request_id="r1",
            amount_usd=Decimal("0.10"),
            scopes={"company": "global"},
            now=NOW,
        )
        s2 = BudgetStore(db)
        s2.verify_audit()
        assert len(s2.audit_entries()) == 1
