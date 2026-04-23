"""Distributed operational state substrate with Redis and persistent fallback.

This module centralizes state read/write, distributed lock handling,
and operational metrics for state freshness/synchronization health.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import redis as redis_sync
    from redis.exceptions import RedisError

    _REDIS_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency in local dev
    redis_sync = None  # type: ignore[assignment]
    RedisError = Exception  # type: ignore[assignment,misc]
    _REDIS_AVAILABLE = False


logger = logging.getLogger("state.operational")

STALE_STATE_RATE_GAUGE = "stale_state_rate"
LOCK_CONTENTION_RATE_GAUGE = "lock_contention_rate"
STATE_SYNC_FAILURE_RATE_GAUGE = "state_sync_failure_rate"


def _parse_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


@dataclass(frozen=True)
class StatePolicy:
    ttl_seconds: Optional[int] = None
    persistent: bool = True
    stale_after_seconds: Optional[int] = 600


_metrics_collector: Optional[Any] = None


def set_operational_state_metrics_collector(metrics_collector: Any) -> None:
    """Bind ops metrics collector for distributed-state SLO gauges."""
    global _metrics_collector
    _metrics_collector = metrics_collector


def _metrics_set_gauge(name: str, value: float) -> None:
    if _metrics_collector is None:
        return
    try:
        _metrics_collector.set_gauge(name, value)
    except Exception:
        logger.debug("state metrics gauge update failed", exc_info=True)


class _StateMetricTracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._reads = 0
        self._stale_reads = 0
        self._lock_attempts = 0
        self._lock_contentions = 0
        self._sync_attempts = 0
        self._sync_failures = 0

    def record_read(self, stale: bool) -> None:
        with self._lock:
            self._reads += 1
            if stale:
                self._stale_reads += 1
            denom = max(self._reads, 1)
            _metrics_set_gauge(STALE_STATE_RATE_GAUGE, self._stale_reads / denom)

    def record_lock(self, contended: bool) -> None:
        with self._lock:
            self._lock_attempts += 1
            if contended:
                self._lock_contentions += 1
            denom = max(self._lock_attempts, 1)
            _metrics_set_gauge(LOCK_CONTENTION_RATE_GAUGE, self._lock_contentions / denom)

    def record_sync(self, attempts: int, failures: int) -> None:
        with self._lock:
            self._sync_attempts += max(attempts, 0)
            self._sync_failures += max(failures, 0)
            denom = max(self._sync_attempts, 1)
            _metrics_set_gauge(STATE_SYNC_FAILURE_RATE_GAUGE, self._sync_failures / denom)


_metric_tracker = _StateMetricTracker()


class DistributedStateLock:
    def __init__(
        self,
        store: "OperationalStateStore",
        name: str,
        ttl_seconds: float,
        wait_timeout_seconds: float,
        retry_interval_seconds: float,
    ) -> None:
        self._store = store
        self._name = name
        self._ttl_seconds = max(float(ttl_seconds), 0.1)
        self._wait_timeout_seconds = max(float(wait_timeout_seconds), 0.0)
        self._retry_interval_seconds = max(float(retry_interval_seconds), 0.01)
        self._token = uuid.uuid4().hex
        self._acquired = False
        self._mode = "none"  # redis | local | none
        self._local_lock: Optional[threading.Lock] = None

    def _lock_key(self) -> str:
        return self._store._lock_key(self._name)

    def acquire(self) -> bool:
        deadline = time.time() + self._wait_timeout_seconds
        contended = False

        while True:
            client = self._store._get_redis_client()
            if client is not None:
                try:
                    acquired = bool(
                        client.set(
                            self._lock_key(),
                            self._token,
                            nx=True,
                            px=int(self._ttl_seconds * 1000),
                        )
                    )
                except RedisError:
                    acquired = False
                if acquired:
                    self._acquired = True
                    self._mode = "redis"
                    _metric_tracker.record_lock(contended=contended)
                    return True
            else:
                local_lock = self._store._get_local_lock(self._lock_key())
                acquired = local_lock.acquire(blocking=False)
                if acquired:
                    self._local_lock = local_lock
                    self._acquired = True
                    self._mode = "local"
                    _metric_tracker.record_lock(contended=contended)
                    return True

            if time.time() >= deadline:
                _metric_tracker.record_lock(contended=True)
                return False

            contended = True
            time.sleep(self._retry_interval_seconds)

    def release(self) -> None:
        if not self._acquired:
            return

        try:
            if self._mode == "redis":
                client = self._store._get_redis_client()
                if client is not None:
                    release_script = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""
                    try:
                        client.eval(release_script, 1, self._lock_key(), self._token)
                    except RedisError:
                        logger.debug("failed to release redis lock", exc_info=True)
            elif self._mode == "local" and self._local_lock is not None:
                self._local_lock.release()
        finally:
            self._acquired = False
            self._mode = "none"
            self._local_lock = None

    def __enter__(self) -> "DistributedStateLock":
        if not self.acquire():
            raise TimeoutError(f"failed to acquire distributed lock: {self._name}")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


class OperationalStateStore:
    """Unified state store with Redis primary and SQLite persistent fallback."""

    def __init__(self) -> None:
        self._root = Path(__file__).resolve().parents[2]
        default_sqlite = self._root / "storage" / "ops" / "operational_state.db"

        self._redis_url = os.getenv("OPS_STATE_REDIS_URL", os.getenv("RATE_LIMIT_REDIS_URL", "redis://localhost:6379/0"))
        self._redis_prefix = os.getenv("OPS_STATE_REDIS_PREFIX", "hdss:ops:state:v1")
        self._redis_socket_timeout = _safe_float(os.getenv("OPS_STATE_REDIS_SOCKET_TIMEOUT"), 0.4)
        self._redis_connect_timeout = _safe_float(os.getenv("OPS_STATE_REDIS_CONNECT_TIMEOUT"), 0.4)
        self._redis_enabled = _parse_bool(os.getenv("OPS_STATE_REDIS_ENABLED", "true"), True)
        self._fail_open = _parse_bool(os.getenv("OPS_STATE_FAIL_OPEN", "true"), True)

        sqlite_path = Path(os.getenv("OPS_STATE_SQLITE_PATH", str(default_sqlite)))
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self._sqlite_path = sqlite_path

        self._redis_client: Optional[Any] = None
        self._redis_lock = threading.Lock()
        self._local_locks: Dict[str, threading.Lock] = {}
        self._local_locks_guard = threading.Lock()

        self._init_sqlite()

    def _get_redis_client(self) -> Optional[Any]:
        if not self._redis_enabled or not _REDIS_AVAILABLE:
            return None

        if self._redis_client is not None:
            return self._redis_client

        with self._redis_lock:
            if self._redis_client is not None:
                return self._redis_client

            try:
                client = redis_sync.Redis.from_url(
                    self._redis_url,
                    decode_responses=True,
                    socket_timeout=self._redis_socket_timeout,
                    socket_connect_timeout=self._redis_connect_timeout,
                    health_check_interval=30,
                )
                client.ping()
                self._redis_client = client
                return client
            except Exception as exc:
                logger.warning("operational state redis unavailable: %s", exc)
                self._redis_client = None
                return None

    def _get_local_lock(self, key: str) -> threading.Lock:
        with self._local_locks_guard:
            if key not in self._local_locks:
                self._local_locks[key] = threading.Lock()
            return self._local_locks[key]

    def _data_key(self, namespace: str, state_key: str) -> str:
        return f"{self._redis_prefix}:data:{namespace}:{state_key}"

    def _events_key(self, namespace: str) -> str:
        return f"{self._redis_prefix}:events:{namespace}"

    def _lock_key(self, lock_name: str) -> str:
        return f"{self._redis_prefix}:lock:{lock_name}"

    def lock(
        self,
        name: str,
        ttl_seconds: float = 15.0,
        wait_timeout_seconds: float = 3.0,
        retry_interval_seconds: float = 0.05,
    ) -> DistributedStateLock:
        return DistributedStateLock(
            store=self,
            name=name,
            ttl_seconds=ttl_seconds,
            wait_timeout_seconds=wait_timeout_seconds,
            retry_interval_seconds=retry_interval_seconds,
        )

    def _init_sqlite(self) -> None:
        with sqlite3.connect(str(self._sqlite_path)) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS operational_state (
                    namespace TEXT NOT NULL,
                    state_key TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT,
                    PRIMARY KEY(namespace, state_key)
                );

                CREATE TABLE IF NOT EXISTS operational_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    namespace TEXT NOT NULL,
                    state_key TEXT,
                    event_type TEXT NOT NULL,
                    payload TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_operational_state_updated
                ON operational_state(updated_at);

                CREATE INDEX IF NOT EXISTS idx_operational_events_namespace
                ON operational_events(namespace, created_at DESC);
                """
            )

    def _build_envelope(self, value: Any, policy: StatePolicy) -> Dict[str, Any]:
        updated_at = _utc_now_iso()
        expires_at: Optional[str] = None
        if policy.ttl_seconds is not None:
            expires_at = (datetime.now(timezone.utc) + timedelta(seconds=policy.ttl_seconds)).isoformat()
        return {
            "value": value,
            "updated_at": updated_at,
            "expires_at": expires_at,
        }

    @staticmethod
    def _envelope_value(envelope: Dict[str, Any], default: Any) -> Any:
        if not isinstance(envelope, dict):
            return default
        return envelope.get("value", default)

    @staticmethod
    def _is_expired(envelope: Dict[str, Any]) -> bool:
        expires_at = envelope.get("expires_at")
        if not expires_at:
            return False
        try:
            return datetime.fromisoformat(expires_at) <= datetime.now(timezone.utc)
        except Exception:
            return False

    @staticmethod
    def _is_stale(envelope: Dict[str, Any], policy: StatePolicy) -> bool:
        if policy.stale_after_seconds is None:
            return False
        updated_at = envelope.get("updated_at")
        if not updated_at:
            return False
        try:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(updated_at)
        except Exception:
            return False
        return age.total_seconds() > policy.stale_after_seconds

    def _read_persistent_envelope(self, namespace: str, state_key: str) -> Optional[Dict[str, Any]]:
        with sqlite3.connect(str(self._sqlite_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT payload FROM operational_state
                WHERE namespace = ? AND state_key = ?
                """,
                (namespace, state_key),
            ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(row["payload"])
            if isinstance(payload, dict):
                return payload
        except Exception:
            logger.warning("invalid persistent state payload for %s:%s", namespace, state_key)
        return None

    def _write_persistent_envelope(self, namespace: str, state_key: str, envelope: Dict[str, Any]) -> None:
        payload = json.dumps(envelope, ensure_ascii=False)
        with sqlite3.connect(str(self._sqlite_path)) as conn:
            conn.execute(
                """
                INSERT INTO operational_state (namespace, state_key, payload, updated_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(namespace, state_key)
                DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = excluded.updated_at,
                    expires_at = excluded.expires_at
                """,
                (
                    namespace,
                    state_key,
                    payload,
                    envelope.get("updated_at", _utc_now_iso()),
                    envelope.get("expires_at"),
                ),
            )

    def get_json(
        self,
        namespace: str,
        state_key: str,
        default: Any = None,
        policy: Optional[StatePolicy] = None,
    ) -> Any:
        policy = policy or StatePolicy()

        envelope: Optional[Dict[str, Any]] = None
        from_redis = False

        client = self._get_redis_client()
        if client is not None:
            try:
                raw = client.get(self._data_key(namespace, state_key))
                if raw:
                    loaded = json.loads(raw)
                    if isinstance(loaded, dict):
                        envelope = loaded
                        from_redis = True
            except Exception:
                logger.debug("redis state read failed: %s:%s", namespace, state_key, exc_info=True)

        if envelope is None:
            envelope = self._read_persistent_envelope(namespace, state_key)

            # Hydrate Redis from persistence to recover distributed readers after failover.
            if envelope is not None and client is not None:
                ttl_seconds: Optional[int] = None
                expires_at = envelope.get("expires_at")
                if expires_at:
                    try:
                        ttl_seconds = max(
                            int((datetime.fromisoformat(expires_at) - datetime.now(timezone.utc)).total_seconds()),
                            1,
                        )
                    except Exception:
                        ttl_seconds = policy.ttl_seconds
                else:
                    ttl_seconds = policy.ttl_seconds

                attempts = 1
                failures = 0
                try:
                    payload = json.dumps(envelope, ensure_ascii=False)
                    if ttl_seconds is not None:
                        client.set(self._data_key(namespace, state_key), payload, ex=max(ttl_seconds, 1))
                    else:
                        client.set(self._data_key(namespace, state_key), payload)
                except Exception:
                    failures = 1
                _metric_tracker.record_sync(attempts=attempts, failures=failures)

        if envelope is None:
            _metric_tracker.record_read(stale=False)
            return default

        if self._is_expired(envelope):
            self.delete(namespace, state_key)
            _metric_tracker.record_read(stale=False)
            return default

        stale = self._is_stale(envelope, policy)
        _metric_tracker.record_read(stale=stale)

        # If Redis had a stale copy while persistence has fresher data, prefer persistence.
        if from_redis:
            persistent = self._read_persistent_envelope(namespace, state_key)
            if isinstance(persistent, dict):
                try:
                    redis_updated = datetime.fromisoformat(envelope.get("updated_at", ""))
                    persistent_updated = datetime.fromisoformat(persistent.get("updated_at", ""))
                    if persistent_updated > redis_updated:
                        envelope = persistent
                except Exception:
                    pass

        return self._envelope_value(envelope, default)

    def set_json(
        self,
        namespace: str,
        state_key: str,
        value: Any,
        policy: Optional[StatePolicy] = None,
    ) -> bool:
        policy = policy or StatePolicy()
        envelope = self._build_envelope(value, policy)
        payload = json.dumps(envelope, ensure_ascii=False)

        attempts = 0
        failures = 0
        success = False

        client = self._get_redis_client()
        if client is not None:
            attempts += 1
            try:
                if policy.ttl_seconds is not None:
                    client.set(self._data_key(namespace, state_key), payload, ex=max(policy.ttl_seconds, 1))
                else:
                    client.set(self._data_key(namespace, state_key), payload)
                success = True
            except Exception:
                failures += 1

        should_persist = policy.persistent or client is None
        if should_persist:
            attempts += 1
            try:
                self._write_persistent_envelope(namespace, state_key, envelope)
                success = True
            except Exception:
                failures += 1

        _metric_tracker.record_sync(attempts=attempts, failures=failures)

        if not success and not self._fail_open:
            raise RuntimeError(f"failed to persist state for {namespace}:{state_key}")

        return success

    def delete(self, namespace: str, state_key: str) -> None:
        client = self._get_redis_client()
        if client is not None:
            try:
                client.delete(self._data_key(namespace, state_key))
            except Exception:
                logger.debug("redis delete failed for %s:%s", namespace, state_key, exc_info=True)

        with sqlite3.connect(str(self._sqlite_path)) as conn:
            conn.execute(
                """
                DELETE FROM operational_state WHERE namespace = ? AND state_key = ?
                """,
                (namespace, state_key),
            )

    def append_event(
        self,
        namespace: str,
        event_type: str,
        payload: Dict[str, Any],
        state_key: str = "*",
        max_redis_events: int = 500,
    ) -> None:
        event = {
            "namespace": namespace,
            "state_key": state_key,
            "event_type": event_type,
            "payload": payload,
            "created_at": _utc_now_iso(),
        }

        client = self._get_redis_client()
        attempts = 0
        failures = 0

        if client is not None:
            attempts += 1
            try:
                events_key = self._events_key(namespace)
                serialized = json.dumps(event, ensure_ascii=False)
                client.lpush(events_key, serialized)
                client.ltrim(events_key, 0, max(max_redis_events - 1, 0))
            except Exception:
                failures += 1

        attempts += 1
        try:
            with sqlite3.connect(str(self._sqlite_path)) as conn:
                conn.execute(
                    """
                    INSERT INTO operational_events (namespace, state_key, event_type, payload, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        namespace,
                        state_key,
                        event_type,
                        json.dumps(payload, ensure_ascii=False),
                        event["created_at"],
                    ),
                )
        except Exception:
            failures += 1

        _metric_tracker.record_sync(attempts=attempts, failures=failures)

    def list_events(self, namespace: str, limit: int = 100) -> list[Dict[str, Any]]:
        with sqlite3.connect(str(self._sqlite_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT namespace, state_key, event_type, payload, created_at
                FROM operational_events
                WHERE namespace = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (namespace, max(limit, 1)),
            ).fetchall()

        events: list[Dict[str, Any]] = []
        for row in rows:
            payload: Dict[str, Any]
            try:
                loaded = json.loads(row["payload"] or "{}")
                payload = loaded if isinstance(loaded, dict) else {}
            except Exception:
                payload = {}
            events.append(
                {
                    "namespace": row["namespace"],
                    "state_key": row["state_key"],
                    "event_type": row["event_type"],
                    "payload": payload,
                    "created_at": row["created_at"],
                }
            )
        return events

    def health(self) -> Dict[str, Any]:
        client = self._get_redis_client()
        redis_ok = False
        if client is not None:
            try:
                client.ping()
                redis_ok = True
            except Exception:
                redis_ok = False

        sqlite_ok = True
        try:
            with sqlite3.connect(str(self._sqlite_path)) as conn:
                conn.execute("SELECT 1")
        except Exception:
            sqlite_ok = False

        return {
            "redis_enabled": self._redis_enabled,
            "redis_available": redis_ok,
            "sqlite_available": sqlite_ok,
            "sqlite_path": str(self._sqlite_path),
        }


_operational_state_store: Optional[OperationalStateStore] = None
_operational_state_store_guard = threading.Lock()


def get_operational_state_store() -> OperationalStateStore:
    global _operational_state_store
    if _operational_state_store is not None:
        return _operational_state_store

    with _operational_state_store_guard:
        if _operational_state_store is None:
            _operational_state_store = OperationalStateStore()
    return _operational_state_store
