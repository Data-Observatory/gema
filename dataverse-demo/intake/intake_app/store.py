"""SQLite persistence: one ``resources`` table plus a tiny ``settings`` key/value table.

Every method opens its own short-lived connection (WAL mode), so the store is safe to use
from request threads and processing threads at once. All SQL is parameterized. State
changes that must not race (claiming a record for processing, deleting it) are single
conditional ``UPDATE``/``DELETE`` statements checked via ``rowcount``.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

PENDING = "pending"
PROCESSING = "processing"
DONE = "done"
FAILED = "failed"
STATUSES = (PENDING, PROCESSING, DONE, FAILED)
DELETABLE = (PENDING, FAILED)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS resources (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    url           TEXT NOT NULL,
    url_norm      TEXT NOT NULL UNIQUE,
    hints         TEXT NOT NULL DEFAULT '',
    pseudonym     TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending', 'processing', 'done', 'failed')),
    error         TEXT NOT NULL DEFAULT '',
    dataverse_pid TEXT NOT NULL DEFAULT '',
    dataverse_url TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_COLUMNS = (
    "id, url, url_norm, hints, pseudonym, status, error, dataverse_pid, dataverse_url, "
    "created_at, updated_at"
)


class DuplicateError(Exception):
    """The URL was already submitted; ``pseudonym`` is who did it."""

    def __init__(self, pseudonym: str) -> None:
        super().__init__(pseudonym)
        self.pseudonym = pseudonym


class LimitReachedError(Exception):
    """The configured maximum number of records is reached."""


@dataclass(frozen=True)
class Resource:
    id: int
    url: str
    url_norm: str
    hints: str
    pseudonym: str
    status: str
    error: str
    dataverse_pid: str
    dataverse_url: str
    created_at: str
    updated_at: str


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row(row: sqlite3.Row) -> Resource:
    return Resource(**{key: row[key] for key in row.keys()})  # noqa: SIM118


class Store:
    def __init__(self, path: Path) -> None:
        self._path = path

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def init(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)

    # -- reads ---------------------------------------------------------------------------

    def all_records(self) -> list[Resource]:
        with self._conn() as conn:
            rows = conn.execute(f"SELECT {_COLUMNS} FROM resources ORDER BY id DESC").fetchall()
        return [_row(r) for r in rows]

    def get(self, rid: int) -> Resource | None:
        with self._conn() as conn:
            row = conn.execute(f"SELECT {_COLUMNS} FROM resources WHERE id = ?", (rid,)).fetchone()
        return _row(row) if row else None

    def ids_with_status(self, status: str) -> list[int]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id FROM resources WHERE status = ? ORDER BY id", (status,)
            ).fetchall()
        return [int(r["id"]) for r in rows]

    def counts(self) -> dict[str, int]:
        result = dict.fromkeys(STATUSES, 0)
        with self._conn() as conn:
            for row in conn.execute("SELECT status, COUNT(*) AS n FROM resources GROUP BY status"):
                result[row["status"]] = int(row["n"])
        return result

    # -- writes --------------------------------------------------------------------------

    def add(
        self, *, url: str, url_norm: str, hints: str, pseudonym: str, max_records: int
    ) -> Resource:
        """Insert a ``pending`` record. Raises ``DuplicateError`` / ``LimitReachedError``."""
        now = _now()
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                dup = conn.execute(
                    "SELECT pseudonym FROM resources WHERE url_norm = ?", (url_norm,)
                ).fetchone()
                if dup:
                    raise DuplicateError(str(dup["pseudonym"]))
                total = conn.execute("SELECT COUNT(*) FROM resources").fetchone()[0]
                if total >= max_records:
                    raise LimitReachedError
                cur = conn.execute(
                    "INSERT INTO resources (url, url_norm, hints, pseudonym, status, "
                    "created_at, updated_at) VALUES (?, ?, ?, ?, 'pending', ?, ?)",
                    (url, url_norm, hints, pseudonym, now, now),
                )
                conn.execute("COMMIT")
                rid = cur.lastrowid
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        record = self.get(int(rid or 0))
        assert record is not None
        return record

    def delete(self, rid: int) -> bool:
        """Delete a record, only while ``pending`` or ``failed``. True if deleted."""
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM resources WHERE id = ? AND status IN (?, ?)", (rid, *DELETABLE)
            )
            return cur.rowcount == 1

    def claim(self, rid: int, from_status: str) -> Resource | None:
        """Atomically move ``from_status`` -> ``processing``; None if it was not in that state
        (already claimed, done, deleted...). The only way a record starts processing."""
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE resources SET status = 'processing', error = '', updated_at = ? "
                "WHERE id = ? AND status = ?",
                (_now(), rid, from_status),
            )
            claimed = cur.rowcount == 1
        return self.get(rid) if claimed else None

    def set_pid(self, rid: int, pid: str, url: str) -> None:
        """Record the Dataverse PID the moment the dataset exists, so a retry after a crash
        or timeout publishes it instead of creating a duplicate."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE resources SET dataverse_pid = ?, dataverse_url = ?, updated_at = ? "
                "WHERE id = ?",
                (pid, url, _now(), rid),
            )

    def mark_done(self, rid: int) -> bool:
        return self._finish(rid, DONE, "")

    def mark_failed(self, rid: int, error: str) -> bool:
        return self._finish(rid, FAILED, error)

    def _finish(self, rid: int, status: str, error: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE resources SET status = ?, error = ?, updated_at = ? "
                "WHERE id = ? AND status = 'processing'",
                (status, error, _now(), rid),
            )
            return cur.rowcount == 1

    def recover_stale(self) -> int:
        """Crash recovery at startup: nothing can legitimately be ``processing`` while the
        process is just starting. They go back to ``pending`` (a stored PID keeps the retry
        publish-only, so no duplicate dataset)."""
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE resources SET status = 'pending', "
                "error = 'Interrupted by a restart; will run again', updated_at = ? "
                "WHERE status = 'processing'",
                (_now(),),
            )
            return cur.rowcount

    # -- settings ------------------------------------------------------------------------

    def is_open(self) -> bool:
        with self._conn() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = 'intake_open'").fetchone()
        return row is None or row["value"] == "1"

    def set_open(self, is_open: bool) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES ('intake_open', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                ("1" if is_open else "0",),
            )
