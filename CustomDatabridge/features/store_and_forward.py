
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from contextlib import closing as _closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

log = logging.getLogger("StoreAndForward")

SenderFn = Callable[[str, object, str | None], bool]
"""Signature: (url, value, value_type) -> ok.

The sender must return ``True`` on HTTP 2xx, ``False`` on transport or
server error, and raise on programming mistakes. Any exception is treated
as a transport error (the entry is buffered)."""

@dataclass
class BufferStats:
    enqueued: int = 0
    flushed: int = 0
    failures: int = 0
    last_flush_at: float | None = None
    last_error: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def snapshot(self) -> dict[str, object]:
        with self.lock:
            return {
                "enqueued": self.enqueued,
                "flushed": self.flushed,
                "failures": self.failures,
                "lastFlushAt": self.last_flush_at,
                "lastError": self.last_error,
            }

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pending_writes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         REAL NOT NULL,
    url        TEXT NOT NULL,
    value      TEXT NOT NULL,
    value_type TEXT,
    attempts   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_pending_writes_ts
    ON pending_writes (ts);
"""

class BufferedAASWriter:

    def __init__(
        self,
        db_path: str | Path,
        sender: SenderFn,
        *,
        max_attempts: int = 20,
        max_flush_batch: int = 100,
    ) -> None:
        self.db_path = str(db_path)
        self.sender = sender
        self.max_attempts = max_attempts
        self.max_flush_batch = max_flush_batch
        self.stats = BufferStats()
        self._lock = threading.Lock()
        self._stop_flusher = threading.Event()
        self._flusher_thread: threading.Thread | None = None
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_schema(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._lock, _closing(self._connect()) as conn, conn:
            conn.executescript(_SCHEMA)

    def write(
        self,
        url: str,
        value: object,
        *,
        value_type: str | None = None,
        timestamp: float | None = None,
    ) -> bool:
        now = timestamp if timestamp is not None else time.time()

        if self._pending_count() > 0:
            self.flush()

        try:
            ok = self.sender(url, value, value_type)
        except Exception as exc:
            self._record_failure(str(exc))
            ok = False

        if ok:
            return True

        self._enqueue(url, value, value_type, now)
        return False

    def flush(self) -> int:
        flushed = 0
        while True:
            with self._lock, _closing(self._connect()) as conn, conn:
                rows = conn.execute(
                    "SELECT id, ts, url, value, value_type, attempts "
                    "FROM pending_writes ORDER BY ts ASC, id ASC LIMIT ?",
                    (self.max_flush_batch,),
                ).fetchall()
            if not rows:
                break
            all_sent_this_batch = True
            for rid, _ts, url, raw, vtype, attempts in rows:
                value = _decode_value(raw)
                try:
                    ok = self.sender(url, value, vtype)
                except Exception as exc:
                    ok = False
                    self._record_failure(str(exc))
                if ok:
                    with self._lock, _closing(self._connect()) as conn, conn:
                        conn.execute(
                            "DELETE FROM pending_writes WHERE id=?",
                            (rid,),
                        )
                    with self.stats.lock:
                        self.stats.flushed += 1
                    flushed += 1
                else:
                    all_sent_this_batch = False
                    new_attempts = attempts + 1
                    if new_attempts >= self.max_attempts:
                        log.warning(
                            "Dropping entry %s after %d attempts: %s",
                            rid, new_attempts, url,
                        )
                        with self._lock, _closing(self._connect()) as conn, conn:
                            conn.execute(
                                "DELETE FROM pending_writes WHERE id=?",
                                (rid,),
                            )
                    else:
                        with self._lock, _closing(self._connect()) as conn, conn:
                            conn.execute(
                                "UPDATE pending_writes SET attempts=? "
                                "WHERE id=?",
                                (new_attempts, rid),
                            )
                    break
            if not all_sent_this_batch:
                break
        with self.stats.lock:
            self.stats.last_flush_at = time.time()
        return flushed

    def pending(self) -> int:
        return self._pending_count()

    def start_background_flusher(self, interval_s: float = 10.0) -> None:
        if self._flusher_thread and self._flusher_thread.is_alive():
            return
        self._stop_flusher.clear()

        def _loop():
            while not self._stop_flusher.is_set():
                try:
                    if self._pending_count() > 0:
                        self.flush()
                except Exception as exc:
                    log.error("background flusher error: %s", exc)
                self._stop_flusher.wait(interval_s)

        self._flusher_thread = threading.Thread(
            target=_loop, name="SAF-Flusher", daemon=True,
        )
        self._flusher_thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_flusher.set()
        if self._flusher_thread:
            self._flusher_thread.join(timeout=timeout)

    def _pending_count(self) -> int:
        with self._lock, _closing(self._connect()) as conn, conn:
            (n,) = conn.execute(
                "SELECT COUNT(*) FROM pending_writes"
            ).fetchone()
        return int(n)

    def _enqueue(self, url: str, value: object, vtype: str | None,
                 ts: float) -> None:
        raw = _encode_value(value)
        with self._lock, _closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO pending_writes (ts, url, value, value_type) "
                "VALUES (?, ?, ?, ?)",
                (ts, url, raw, vtype),
            )
        with self.stats.lock:
            self.stats.enqueued += 1

    def _record_failure(self, msg: str) -> None:
        with self.stats.lock:
            self.stats.failures += 1
            self.stats.last_error = msg

def _encode_value(v: object) -> str:
    return json.dumps(v, ensure_ascii=False)

def _decode_value(s: str) -> object:
    try:
        return json.loads(s)
    except Exception:
        return s

def make_http_put_sender(timeout_s: float = 5.0) -> SenderFn:
    import requests

    def send(url: str, value: object, value_type: str | None) -> bool:
        try:
            body: dict[str, object] = {"value": value}
            if value_type:
                body["valueType"] = value_type
            resp = requests.put(url, json=body, timeout=timeout_s)
            return 200 <= resp.status_code < 300
        except Exception as exc:
            log.debug("HTTP PUT %s failed: %s", url, exc)
            return False

    return send

def drop_entries_older_than(db_path: str | Path,
                            max_age_seconds: float) -> int:
    cutoff = time.time() - max_age_seconds
    conn = sqlite3.connect(str(db_path), timeout=5.0)
    try:
        cur = conn.execute(
            "DELETE FROM pending_writes WHERE ts < ?", (cutoff,),
        )
        conn.commit()
        return int(cur.rowcount or 0)
    finally:
        conn.close()

def seed_entries(db_path: str | Path,
                 entries: Iterable[tuple[str, object, str | None, float]]
                 ) -> int:
    n = 0
    conn = sqlite3.connect(str(db_path), timeout=5.0)
    try:
        conn.executescript(_SCHEMA)
        for url, value, vtype, ts in entries:
            conn.execute(
                "INSERT INTO pending_writes (ts, url, value, value_type) "
                "VALUES (?, ?, ?, ?)",
                (ts, url, _encode_value(value), vtype),
            )
            n += 1
        conn.commit()
    finally:
        conn.close()
    return n
