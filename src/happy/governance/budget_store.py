"""The spending circuit breaker.

One SQLite file is the authority on what may be spent. Every LLM call reserves
its **worst-case** cost before the provider is contacted, and settles the actual
cost afterwards. A reservation that is never settled keeps holding budget until
it expires, so a crash costs headroom rather than control.

This is not a finance system. It is a table, a conditional `UPDATE`, and a hash
chain. Three design choices carry the guarantee:

**Integer nanodollars.** Money is never a float. All arithmetic is exact.

**One `BEGIN IMMEDIATE` transaction per decision.** The limit check and the
increment that consumes it are the same write, so two concurrent requests can
never both see room that only one of them can have.

**Fail closed.** Anything unknown — a missing limit, an unpriceable model, an
unparseable cost — denies or settles at the reserved maximum. The safe direction
is always to hold more, never less.
"""

from __future__ import annotations

import hmac
import os
import sqlite3
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Final

from happy.governance.errors import BudgetExceeded
from happy.governance.hashing import GENESIS_HASH, canonical_json, chain_hash

AUDIT_SECRET_ENV = "HAPPY_AUDIT_HMAC_SECRET"
"""Environment variable holding the audit-chain signing secret (hex).

Held outside the database on purpose. The plain SHA-256 chain is recomputable
by anyone who can write to the audit table; a keyed chain is not, unless they
also hold this secret. That is the whole difference between "detects
corruption" and "detects tampering".
"""

MIN_AUDIT_SECRET_BYTES = 32

NANO: Final = Decimal("1000000000")
"""Nanodollars per dollar. Costs below 1e-9 USD round up to 1, never to 0."""

DEFAULT_RESERVATION_TTL = timedelta(minutes=15)
"""How long an unsettled reservation keeps holding budget after a crash."""

SCOPES: Final = ("request", "agent", "task", "daily", "monthly", "company")
"""The six limits. Ordered widest-last only for readable error messages."""

_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS limits (
    scope TEXT NOT NULL,
    key   TEXT NOT NULL,
    limit_nano INTEGER NOT NULL CHECK (limit_nano >= 0),
    PRIMARY KEY (scope, key)
);
CREATE TABLE IF NOT EXISTS spend (
    scope TEXT NOT NULL,
    key   TEXT NOT NULL,
    settled_nano  INTEGER NOT NULL DEFAULT 0 CHECK (settled_nano  >= 0),
    reserved_nano INTEGER NOT NULL DEFAULT 0 CHECK (reserved_nano >= 0),
    PRIMARY KEY (scope, key)
);
CREATE TABLE IF NOT EXISTS reservations (
    id           TEXT PRIMARY KEY,
    request_id   TEXT NOT NULL UNIQUE,
    amount_nano  INTEGER NOT NULL CHECK (amount_nano >= 0),
    scopes_json  TEXT NOT NULL,
    state        TEXT NOT NULL CHECK (state IN ('open','settled','released','expired')),
    created_at   TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    settled_nano INTEGER
);
CREATE TABLE IF NOT EXISTS audit (
    seq        INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at TEXT NOT NULL,
    event      TEXT NOT NULL,
    request_id TEXT NOT NULL,
    amount_nano INTEGER NOT NULL,
    detail     TEXT NOT NULL,
    prev_hash  TEXT NOT NULL,
    entry_hash TEXT NOT NULL
);
"""


def to_nano(usd: Decimal | int | float | str) -> int:
    """Convert dollars to integer nanodollars, rounding **up**.

    Rounding up matters: a cost that rounds to zero would let an unbounded
    number of requests through a finite budget.
    """
    try:
        value = Decimal(str(usd))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"not a usable amount: {usd!r}") from exc
    if not value.is_finite() or value < 0:
        raise ValueError(f"amount must be finite and non-negative, got {usd!r}")
    nano = value * NANO
    whole = int(nano)
    return whole + 1 if nano != whole else whole


def to_usd(nano: int) -> Decimal:
    """Convert integer nanodollars back to dollars."""
    return (Decimal(nano) / NANO).quantize(Decimal("0.000000001"))


@dataclass(frozen=True)
class Reservation:
    """A hold on budget. Settle it or release it; never simply forget it."""

    id: str
    request_id: str
    amount_nano: int
    scopes: tuple[tuple[str, str], ...]
    expires_at: datetime

    @property
    def amount_usd(self) -> Decimal:
        return to_usd(self.amount_nano)


@dataclass(frozen=True)
class Denial:
    """Why a request was refused, naming the limit that refused it."""

    scope: str
    key: str
    limit_nano: int
    committed_nano: int
    requested_nano: int

    @property
    def message(self) -> str:
        return (
            f"{self.scope} budget '{self.key}' would be exceeded: "
            f"committed {to_usd(self.committed_nano)} + requested "
            f"{to_usd(self.requested_nano)} > limit {to_usd(self.limit_nano)}"
        )


class BudgetStore:
    """SQLite-backed pre-call authorisation.

    Every method that changes money takes one `BEGIN IMMEDIATE` transaction, so
    the check and the write cannot be separated by another writer.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        ttl: timedelta = DEFAULT_RESERVATION_TTL,
        audit_secret: bytes | None = None,
    ) -> None:
        """Open the store.

        Args:
            audit_secret: key for the audit chain. Defaults to the hex value in
                `$HAPPY_AUDIT_HMAC_SECRET`. When absent the chain falls back to
                the unkeyed SHA-256 form, which is tamper-*evident* only — see
                `chain_mode`.
        """
        self._path = str(path)
        self._ttl = ttl
        self._secret = audit_secret if audit_secret is not None else _secret_from_env()
        if self._secret is not None and len(self._secret) < MIN_AUDIT_SECRET_BYTES:
            raise ValueError(
                f"audit secret must be at least {MIN_AUDIT_SECRET_BYTES} bytes, "
                f"got {len(self._secret)}"
            )
        self._local = threading.local()
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @property
    def chain_mode(self) -> str:
        """`"hmac-sha256"` when a secret is held, `"sha256"` when not."""
        return "hmac-sha256" if self._secret else "sha256"

    def _entry_hash(self, prev_hash: str, payload: dict[str, Any]) -> str:
        if self._secret is None:
            return chain_hash(prev_hash, payload)
        material = (prev_hash + canonical_json(payload)).encode("utf-8")
        return hmac.new(self._secret, material, "sha256").hexdigest()

    def _connect(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._path, timeout=30.0, isolation_level=None)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return conn

    # -- configuration ------------------------------------------------------

    def set_limit(self, scope: str, key: str, limit_usd: Decimal | str) -> None:
        """Declare a ceiling. A scope with no limit denies rather than allows."""
        if scope not in SCOPES:
            raise ValueError(f"unknown scope {scope!r}; expected one of {SCOPES}")
        nano = to_nano(limit_usd)
        conn = self._connect()
        with _immediate(conn):
            conn.execute(
                "INSERT INTO limits(scope,key,limit_nano) VALUES(?,?,?) "
                "ON CONFLICT(scope,key) DO UPDATE SET "
                "limit_nano=excluded.limit_nano",
                (scope, key, nano),
            )
            conn.execute(
                "INSERT OR IGNORE INTO spend(scope,key,settled_nano,reserved_nano) "
                "VALUES(?,?,0,0)",
                (scope, key),
            )

    def committed(self, scope: str, key: str) -> Decimal:
        """Settled plus currently reserved — what the limit is measured against."""
        row = (
            self._connect()
            .execute(
                "SELECT settled_nano + reserved_nano FROM spend WHERE scope=? AND key=?",
                (scope, key),
            )
            .fetchone()
        )
        return to_usd(row[0] if row else 0)

    def settled(self, scope: str, key: str) -> Decimal:
        row = (
            self._connect()
            .execute("SELECT settled_nano FROM spend WHERE scope=? AND key=?", (scope, key))
            .fetchone()
        )
        return to_usd(row[0] if row else 0)

    def remaining(self, scope: str, key: str) -> Decimal | None:
        row = (
            self._connect()
            .execute(
                "SELECT l.limit_nano - COALESCE(s.settled_nano,0) - "
                "COALESCE(s.reserved_nano,0) "
                "FROM limits l LEFT JOIN spend s ON s.scope=l.scope AND s.key=l.key "
                "WHERE l.scope=? AND l.key=?",
                (scope, key),
            )
            .fetchone()
        )
        return None if row is None else to_usd(max(0, row[0]))

    # -- the decision -------------------------------------------------------

    def reserve(
        self,
        *,
        request_id: str,
        amount_usd: Decimal,
        scopes: Mapping[str, str],
        now: datetime,
    ) -> Reservation:
        """Hold `amount_usd` against every applicable limit, or refuse.

        Raises:
            BudgetExceeded: a limit would be breached, or a scope has no limit.
            ValueError: the request was already authorised, or inputs are unusable.
        """
        unknown = set(scopes) - set(SCOPES)
        if unknown:
            raise ValueError(f"unknown scopes {sorted(unknown)}")
        if not scopes:
            raise ValueError("a reservation must name at least one scope")
        amount_nano = to_nano(amount_usd)
        reservation_id = f"rsv_{request_id}"
        expires_at = now + self._ttl
        pairs = tuple(sorted(scopes.items()))

        conn = self._connect()
        # A denial is recorded, then raised *outside* the transaction. Raising
        # inside would roll back the very audit row that records the refusal.
        denial: Denial | None = None
        duplicate = False

        with _immediate(conn):
            self._expire_locked(conn, now)

            if conn.execute(
                "SELECT 1 FROM reservations WHERE request_id=?", (request_id,)
            ).fetchone():
                duplicate = True
            else:
                for scope, key in pairs:
                    row = conn.execute(
                        "SELECT l.limit_nano, COALESCE(s.settled_nano,0), "
                        "       COALESCE(s.reserved_nano,0) "
                        "FROM limits l LEFT JOIN spend s "
                        "  ON s.scope=l.scope AND s.key=l.key "
                        "WHERE l.scope=? AND l.key=?",
                        (scope, key),
                    ).fetchone()
                    if row is None:
                        # No declared limit is not permission. Refuse.
                        denial = Denial(scope, key, 0, 0, amount_nano)
                        break
                    limit_nano, settled_nano, reserved_nano = row
                    committed = settled_nano + reserved_nano
                    if committed + amount_nano > limit_nano:
                        denial = Denial(scope, key, limit_nano, committed, amount_nano)
                        break

                if denial is None:
                    for scope, key in pairs:
                        conn.execute(
                            "UPDATE spend SET reserved_nano = reserved_nano + ? "
                            "WHERE scope=? AND key=?",
                            (amount_nano, scope, key),
                        )
                    conn.execute(
                        "INSERT INTO reservations"
                        "(id,request_id,amount_nano,scopes_json,state,created_at,expires_at) "
                        "VALUES(?,?,?,?,'open',?,?)",
                        (
                            reservation_id,
                            request_id,
                            amount_nano,
                            _dumps(pairs),
                            now.isoformat(),
                            expires_at.isoformat(),
                        ),
                    )
                    self._audit_locked(
                        conn,
                        now,
                        "reserve.granted",
                        request_id,
                        amount_nano,
                        f"held against {len(pairs)} scope(s)",
                    )
                else:
                    self._audit_locked(
                        conn,
                        now,
                        "reserve.denied",
                        request_id,
                        amount_nano,
                        denial.message
                        if denial.limit_nano
                        else f"no limit declared for {denial.scope}:{denial.key}",
                    )

        if duplicate:
            raise ValueError(
                f"request {request_id!r} is already authorised; "
                "an authorised request must not be re-reserved"
            )
        if denial is not None:
            raise BudgetExceeded(
                scope=denial.scope,
                key=denial.key,
                limit=to_usd(denial.limit_nano),
                attempted=to_usd(denial.committed_nano + denial.requested_nano),
            )

        return Reservation(reservation_id, request_id, amount_nano, pairs, expires_at)

    def settle(
        self,
        reservation: Reservation,
        actual_usd: Decimal | int | float | str | None,
        *,
        now: datetime,
    ) -> Decimal:
        """Record the real cost and release the unused hold.

        An actual cost that cannot be trusted — missing, negative, non-finite,
        unparseable — settles at the **full reserved amount**. Charging
        ourselves the maximum we authorised is the only safe reading of a
        provider response we cannot believe.

        Returns:
            The amount actually charged, in dollars.
        """
        detail = ""
        try:
            if actual_usd is None:
                raise ValueError("no cost reported")
            actual_nano = to_nano(actual_usd)
        except (ValueError, TypeError) as exc:
            actual_nano = reservation.amount_nano
            detail = f"untrusted cost ({exc}); settled at reserved maximum"

        if actual_nano > reservation.amount_nano:
            # The provider charged more than we bounded. Record the truth: the
            # limit is now breached and further reservations will refuse.
            detail = (
                f"overrun: actual {to_usd(actual_nano)} exceeded reserved "
                f"{reservation.amount_usd}"
            )

        conn = self._connect()
        with _immediate(conn):
            state = conn.execute(
                "SELECT state FROM reservations WHERE id=?", (reservation.id,)
            ).fetchone()
            if state is None:
                raise ValueError(f"unknown reservation {reservation.id!r}")
            if state[0] != "open":
                raise ValueError(
                    f"reservation {reservation.id!r} is already {state[0]}; "
                    "a reservation settles exactly once"
                )
            for scope, key in reservation.scopes:
                conn.execute(
                    "UPDATE spend SET "
                    "  reserved_nano = MAX(0, reserved_nano - ?), "
                    "  settled_nano  = settled_nano + ? "
                    "WHERE scope=? AND key=?",
                    (reservation.amount_nano, actual_nano, scope, key),
                )
            conn.execute(
                "UPDATE reservations SET state='settled', settled_nano=? WHERE id=?",
                (actual_nano, reservation.id),
            )
            self._audit_locked(
                conn,
                now,
                "settle",
                reservation.request_id,
                actual_nano,
                detail or "settled",
            )
        return to_usd(actual_nano)

    def release(self, reservation: Reservation, *, now: datetime, reason: str) -> None:
        """Return the whole hold. For a call that never reached the provider."""
        conn = self._connect()
        with _immediate(conn):
            state = conn.execute(
                "SELECT state FROM reservations WHERE id=?", (reservation.id,)
            ).fetchone()
            if state is None or state[0] != "open":
                return  # releasing twice is a no-op, not an error
            for scope, key in reservation.scopes:
                conn.execute(
                    "UPDATE spend SET reserved_nano = MAX(0, reserved_nano - ?) "
                    "WHERE scope=? AND key=?",
                    (reservation.amount_nano, scope, key),
                )
            conn.execute(
                "UPDATE reservations SET state='released' WHERE id=?", (reservation.id,)
            )
            self._audit_locked(
                conn,
                now,
                "release",
                reservation.request_id,
                reservation.amount_nano,
                reason,
            )

    # -- recovery -----------------------------------------------------------

    def expire_stale(self, now: datetime) -> int:
        """Release reservations whose owner never came back. Returns the count."""
        conn = self._connect()
        with _immediate(conn):
            return self._expire_locked(conn, now)

    def _expire_locked(self, conn: sqlite3.Connection, now: datetime) -> int:
        rows = conn.execute(
            "SELECT id, request_id, amount_nano, scopes_json FROM reservations "
            "WHERE state='open' AND expires_at <= ?",
            (now.isoformat(),),
        ).fetchall()
        for rid, request_id, amount_nano, scopes_json in rows:
            for scope, key in _loads(scopes_json):
                conn.execute(
                    "UPDATE spend SET reserved_nano = MAX(0, reserved_nano - ?) "
                    "WHERE scope=? AND key=?",
                    (amount_nano, scope, key),
                )
            conn.execute("UPDATE reservations SET state='expired' WHERE id=?", (rid,))
            self._audit_locked(
                conn, now, "expire", request_id, amount_nano, "reservation timed out"
            )
        return len(rows)

    def open_reservations(self) -> tuple[str, ...]:
        rows = (
            self._connect()
            .execute(
                "SELECT request_id FROM reservations WHERE state='open' ORDER BY created_at"
            )
            .fetchall()
        )
        return tuple(r[0] for r in rows)

    # -- audit --------------------------------------------------------------

    def _audit_locked(
        self,
        conn: sqlite3.Connection,
        now: datetime,
        event: str,
        request_id: str,
        amount_nano: int,
        detail: str,
    ) -> None:
        prev = conn.execute(
            "SELECT entry_hash FROM audit ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        prev_hash = prev[0] if prev else GENESIS_HASH
        payload = {
            "recorded_at": now.isoformat(),
            "event": event,
            "request_id": request_id,
            "amount_nano": amount_nano,
            "detail": detail,
        }
        conn.execute(
            "INSERT INTO audit(recorded_at,event,request_id,amount_nano,"
            "detail,prev_hash,entry_hash) VALUES(?,?,?,?,?,?,?)",
            (
                now.isoformat(),
                event,
                request_id,
                amount_nano,
                detail,
                prev_hash,
                self._entry_hash(prev_hash, payload),
            ),
        )

    def audit_entries(self) -> tuple[dict[str, Any], ...]:
        rows = (
            self._connect()
            .execute(
                "SELECT seq,recorded_at,event,request_id,amount_nano,"
                "detail,prev_hash,entry_hash FROM audit ORDER BY seq"
            )
            .fetchall()
        )
        cols = (
            "seq",
            "recorded_at",
            "event",
            "request_id",
            "amount_nano",
            "detail",
            "prev_hash",
            "entry_hash",
        )
        return tuple(dict(zip(cols, r, strict=True)) for r in rows)

    def verify_audit(self) -> None:
        """Walk the chain. Raises `AuditChainBroken` if an entry was altered."""
        from happy.governance.errors import AuditChainBroken

        prev_hash = GENESIS_HASH
        for entry in self.audit_entries():
            if entry["prev_hash"] != prev_hash:
                raise AuditChainBroken(
                    entry["seq"],
                    f"expected prev_hash {prev_hash}, found {entry['prev_hash']}",
                )
            payload = {
                "recorded_at": entry["recorded_at"],
                "event": entry["event"],
                "request_id": entry["request_id"],
                "amount_nano": entry["amount_nano"],
                "detail": entry["detail"],
            }
            expected = self._entry_hash(prev_hash, payload)
            if not hmac.compare_digest(expected, entry["entry_hash"]):
                raise AuditChainBroken(entry["seq"], "entry content was altered")
            prev_hash = entry["entry_hash"]


class _immediate:
    """`BEGIN IMMEDIATE` … `COMMIT`/`ROLLBACK` as a context manager.

    The write lock is taken up front, so the limit check and the increment that
    consumes it cannot be interleaved with another writer.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def __enter__(self) -> sqlite3.Connection:
        self._conn.execute("BEGIN IMMEDIATE")
        return self._conn

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if exc_type is None:
            self._conn.execute("COMMIT")
        else:
            self._conn.execute("ROLLBACK")


def _dumps(pairs: Sequence[tuple[str, str]]) -> str:
    import json

    return json.dumps([list(p) for p in pairs], separators=(",", ":"))


def _loads(raw: str) -> tuple[tuple[str, str], ...]:
    import json

    return tuple((a, b) for a, b in json.loads(raw))


def _secret_from_env() -> bytes | None:
    """Read the audit signing secret from the environment, if present."""
    raw = os.environ.get(AUDIT_SECRET_ENV, "").strip()
    if not raw:
        return None
    try:
        return bytes.fromhex(raw)
    except ValueError:
        return raw.encode("utf-8")
