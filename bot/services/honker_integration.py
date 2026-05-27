"""
Honker integration layer for cross-process notifications,
durable queues, live updates, and scheduled-work locking.

Honker is a SQLite extension (alpha) that adds Postgres-style NOTIFY/LISTEN,
durable queues, streams, pub/sub, and named-lock support.  When the ``honker``
module is not installed or cannot be loaded, all helpers degrade gracefully to
no-ops so that the application runs exactly as before.

Environment variables:
    HONKER_ENABLED  (default ``auto``) — Set to ``true`` or ``false`` to
        force-enable or force-disable.  When ``auto``, Honker is enabled
        if the module imports successfully.
    HONKER_REQUIRED (default ``false``) — When true, any Honker failure
        (import, extension load, API call) raises a hard error instead of
        logging and falling back.
    HONKER_WORKER_ID — Worker/process identifier used for claim-group
        naming and lock identity.  Defaults to ``hostname-pid``.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import threading
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_honker_imported: bool = False
_honker_available: bool | None = None  # None = untested, True/False = cached
_honker_loaded_for: str | None = None  # db_path we loaded the extension for
_honker_lock = threading.Lock()

# Per-thread Honker connection cache so that ``Database.queue()``,
# ``Database.stream()``, and schema/bootstrap DDL run at most once per
# thread instead of on every helper call.  SQLite connections are not
# safe to share across threads, so each thread gets its own.
_thread_honker = threading.local()

# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------

_HONKER_ENABLED = os.getenv("HONKER_ENABLED", "auto").strip().lower()
_HONKER_REQUIRED = os.getenv("HONKER_REQUIRED", "false").strip().lower() in (
    "1", "true", "yes"
)
_HONKER_WORKER_ID = os.getenv(
    "HONKER_WORKER_ID",
    f"{platform.node() or 'unknown'}-{os.getpid()}",
)


def _honker_required() -> bool:
    """Return True if the caller should hard-fail on Honker errors."""
    return _HONKER_REQUIRED


def _is_honker_enabled_by_env() -> bool | None:
    """Return forced bool or None for ``auto``."""
    if _HONKER_ENABLED == "auto":
        return None  # probe at runtime
    return _HONKER_ENABLED in ("1", "true", "yes")


# ---------------------------------------------------------------------------
# Probe / availability
# ---------------------------------------------------------------------------

def _try_import_honker() -> bool:
    """Attempt to import the ``honker`` module once.

    Returns True on success, False otherwise.  The result is cached.
    """
    global _honker_imported
    if _honker_imported:
        return True

    try:
        import honker as _h  # type: ignore[import-untyped] # noqa: F401
        _honker_imported = True
        logger.info("[Honker] Module imported successfully")
        return True
    except ImportError:
        if _honker_required():
            raise RuntimeError(
                "Honker module is required (HONKER_REQUIRED=true) "
                "but could not be imported."
            )
        logger.info("[Honker] Module not installed — all Honker features disabled")
        return False
    except Exception as exc:
        logger.warning("[Honker] Unexpected error during import: %s", exc)
        if _honker_required():
            raise RuntimeError("Honker import failed unexpectedly") from exc
        return False


def availability() -> bool:
    """Return True if Honker is available for use in this process.

    Checks the module import, env overrides, and caches the result.
    """
    global _honker_available
    if _honker_available is not None:
        return _honker_available

    forced = _is_honker_enabled_by_env()
    if forced is False:
        _honker_available = False
        return False

    available = _try_import_honker()
    _honker_available = available if forced is None else (forced and available)
    return _honker_available


def ensure_available(db_path: str | None = None) -> bool:
    """Ensure Honker is importable and can open the configured database.

    When ``HONKER_REQUIRED=true``, any import or connection failure raises
    ``RuntimeError``.  When not required, returns ``False`` on failure and
    ``True`` on success, with no-ops for all callers.

    The ``db_path`` argument is optional — when omitted, the function only
    verifies the import.

    Returns:
        True when Honker is fully available, False when it is not and not
        required.
    """
    if not availability():
        return False

    if db_path is not None:
        try:
            conn = _get_honker_connection(db_path)
            # Close the probe connection immediately.
            import honker  # type: ignore[import-untyped]
            # Honker connections don't have a standard close method;
            # we just let it go out of scope.
        except RuntimeError:
            if _honker_required():
                raise
            return False
        except Exception as exc:
            if _honker_required():
                raise RuntimeError(
                    f"Honker failed to open database {db_path}: {exc}"
                ) from exc
            logger.warning(
                "[Honker] Failed to open database %s: %s", db_path, exc
            )
            return False

    logger.info(
        "[Honker] Honker is available%s",
        f" (db: {db_path})" if db_path else ""
    )
    return True


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

def _get_thread_honker_cache() -> dict[str, Any]:
    """Return the current thread's Honker connection cache dict."""
    if not hasattr(_thread_honker, "connections"):
        _thread_honker.connections = {}
    return _thread_honker.connections


def _close_honker_connection(db_path: str) -> None:
    """Close and remove a cached Honker connection for *db_path*.

    Safe to call from any thread; no-op if no cached connection exists.
    Primarily useful in tests and clean shutdown paths.
    """
    cache = _get_thread_honker_cache()
    conn = cache.pop(db_path, None)
    if conn is not None:
        try:
            close_fn = getattr(conn, "close", None)
            if callable(close_fn):
                close_fn()
        except Exception:
            pass


def _get_honker_connection(db_path: str) -> Any:
    """Return a Honker-wrapped connection for *db_path*, caching per thread.

    Each thread keeps its own Honker connection so that ``Database.queue()``,
    ``Database.stream()``, and schema/bootstrap DDL run at most once per
    thread instead of repeating on every helper call.

    A bounded retry with exponential backoff handles transient ``database is
    locked`` failures during ``honker.open()``.

    Raises ``RuntimeError`` when Honker is not available or the extension
    cannot be loaded after exhausting retries.
    """
    if not availability():
        raise RuntimeError("Honker is not available")

    import honker  # type: ignore[import-untyped]

    # Check per-thread cache first — avoids re-opening and re-bootstrapping.
    cache = _get_thread_honker_cache()
    cached = cache.get(db_path)
    if cached is not None:
        return cached

    # Open a new connection with bounded retry for transient lock errors.
    import time as _time

    max_attempts = 5
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            conn = honker.open(db_path)
            cache[db_path] = conn
            logger.debug(
                "[Honker] Opened connection to %s (thread: %s)",
                db_path,
                threading.current_thread().name,
            )
            return conn
        except Exception as exc:
            last_exc = exc
            error_str = str(exc).lower()
            is_lock = "database is locked" in error_str or "locked" in error_str
            if is_lock and attempt < max_attempts:
                delay = min(0.1 * (2 ** (attempt - 1)), 1.0)  # 0.1, 0.2, 0.4, 0.8
                logger.warning(
                    "[Honker] Database locked on open (attempt %d/%d), "
                    "retrying in %.1fs: %s",
                    attempt,
                    max_attempts,
                    delay,
                    exc,
                )
                _time.sleep(delay)
                continue
            # Non-lock error or final attempt — fall through to raise.
            break

    # All attempts exhausted.
    msg = f"Honker failed to open {db_path}: {last_exc}"
    if _honker_required():
        raise RuntimeError(msg) from last_exc
    logger.warning("[Honker] %s", msg)
    raise last_exc  # type: ignore[return-value]


def _run_sql_function(
    db_path: str,
    sql: str,
    params: tuple[Any, ...] = (),
) -> Any | None:
    """Execute a SQL function on a Honker connection.

    Uses ``conn.transaction()`` to execute raw SQL for functions like
    ``honker_lock_acquire`` / ``honker_lock_release``.
    """
    conn = _get_honker_connection(db_path)
    with conn.transaction() as tx:
        result = tx.query(sql, params)
    # query returns a list of dicts or None
    return result


# ---------------------------------------------------------------------------
# Notification helpers (NOTIFY / LISTEN)
# ---------------------------------------------------------------------------

def publish_notification(
    db_path: str,
    channel: str,
    payload: dict[str, Any] | None = None,
) -> bool:
    """Publish a Honker NOTIFY on *channel* with an optional JSON payload.

    Args:
        db_path: Path to the SQLite database.
        channel: Notification channel name (e.g. ``playback_queue``).
        payload: Optional JSON-serializable dict sent as the notification body.

    Returns:
        True when the notification was published, False if Honker is
        unavailable or the call fails.
    """
    if not availability():
        return False

    if payload is None:
        payload = {}

    try:
        conn = _get_honker_connection(db_path)
        with conn.transaction() as tx:
            tx.notify(channel, payload)
        return True
    except RuntimeError:
        if _honker_required():
            raise
        return False
    except Exception as exc:
        logger.warning(
            "[Honker] Failed to publish notification on %s: %s",
            channel,
            exc,
        )
        if _honker_required():
            raise
        return False


def listen_notifications(
    db_path: str,
    channel: str,
    fallback_poll_s: float | None = None,
) -> Any:
    """Return an async iterator over notifications on *channel*.

    Usage::

        async for notification in listen_notifications(db_path, channel):
            payload = notification.payload  # dict
            # handle …

    When Honker is unavailable, returns an empty async iterator immediately.

    Args:
        db_path: Path to the SQLite database.
        channel: Notification channel name to subscribe to.
        fallback_poll_s: Optional polling interval (seconds) used by Honker's
            ``listen()`` when file-watch wake-ups are not available.  A shorter
            value (e.g. 1.0) reduces notification latency at the cost of more
            frequent internal DB polls.  ``None`` uses Honker's default.
    """
    if not availability():
        return _EmptyAsyncIterator()

    try:
        conn = _get_honker_connection(db_path)
        if fallback_poll_s is not None:
            try:
                return conn.listen(channel, fallback_poll_s=fallback_poll_s)
            except TypeError:
                # Honker version does not support fallback_poll_s.
                return conn.listen(channel)
        return conn.listen(channel)
    except RuntimeError:
        if _honker_required():
            raise
        return _EmptyAsyncIterator()
    except Exception as exc:
        logger.warning(
            "[Honker] Failed to listen on %s: %s",
            channel,
            exc,
        )
        if _honker_required():
            raise
        return _EmptyAsyncIterator()


class _EmptyAsyncIterator:
    """An async iterator that yields nothing (empty)."""

    def __aiter__(self) -> _EmptyAsyncIterator:
        return self

    async def __anext__(self) -> Any:
        raise StopAsyncIteration

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Queue helpers
# ---------------------------------------------------------------------------

def enqueue_job(
    db_path: str,
    queue_name: str,
    payload: dict[str, Any],
) -> bool:
    """Enqueue a job on a Honker durable queue.

    Args:
        db_path: Path to the SQLite database.
        queue_name: Queue name (e.g. ``web_upload_jobs``).
        payload: JSON-serializable dict with job data.

    Returns:
        True on success, False if Honker is unavailable or the call fails.
    """
    if not availability():
        return False

    try:
        conn = _get_honker_connection(db_path)
        queue = conn.queue(queue_name)
        queue.enqueue(payload)
        return True
    except RuntimeError:
        if _honker_required():
            raise
        return False
    except Exception as exc:
        logger.warning(
            "[Honker] Failed to enqueue job on %s: %s",
            queue_name,
            exc,
        )
        if _honker_required():
            raise
        return False


def claim_jobs(
    db_path: str,
    queue_name: str,
    worker_id: str | None = None,
    batch_size: int = 1,
) -> list[Any]:
    """Claim pending jobs from a Honker durable queue.

    Args:
        db_path: Path to the SQLite database.
        queue_name: Queue name.
        worker_id: Unique worker identifier.  Defaults to the process-wide
            ``HONKER_WORKER_ID``.
        batch_size: Maximum number of jobs to claim (default 1).

    Returns:
        List of claimed job objects (each has ``.payload``, ``.id``, etc.)
        or empty list when Honker is unavailable.
    """
    if not availability():
        return []

    worker = worker_id or _HONKER_WORKER_ID
    try:
        conn = _get_honker_connection(db_path)
        queue = conn.queue(queue_name)
        claimed = queue.claim_batch(worker, batch_size)
        return list(claimed) if claimed else []
    except RuntimeError:
        if _honker_required():
            raise
        return []
    except Exception as exc:
        logger.warning(
            "[Honker] Failed to claim jobs from %s: %s",
            queue_name,
            exc,
        )
        if _honker_required():
            raise
        return []


def complete_job(db_path: str, queue_name: str, job: Any) -> bool:
    """Mark a claimed job as complete.

    Args:
        db_path: Path to the SQLite database.
        queue_name: Queue name.
        job: The job object returned by ``claim_jobs``.

    Returns:
        True on success.
    """
    if not availability():
        return False

    try:
        job.ack()
        return True
    except Exception as exc:
        logger.warning("[Honker] Failed to complete job: %s", exc)
        if _honker_required():
            raise
        return False


# ---------------------------------------------------------------------------
# Stream / event helpers
# ---------------------------------------------------------------------------

def publish_event(
    db_path: str,
    stream_name: str,
    payload: dict[str, Any],
) -> bool:
    """Publish an event to a Honker stream.

    Streams are append-only logs that subscribers can consume at their own
    pace.  This is useful for coarse-grained "something changed" signals.

    Args:
        db_path: Path to the SQLite database.
        stream_name: Stream name (e.g. ``soundboard_events``).
        payload: JSON-serializable event payload.

    Returns:
        True on success, False if Honker is unavailable.
    """
    if not availability():
        return False

    try:
        conn = _get_honker_connection(db_path)
        stream = conn.stream(stream_name)
        stream.publish(payload)
        return True
    except RuntimeError:
        if _honker_required():
            raise
        return False
    except Exception as exc:
        logger.warning(
            "[Honker] Failed to publish event on stream %s: %s",
            stream_name,
            exc,
        )
        if _honker_required():
            raise
        return False


# ---------------------------------------------------------------------------
# Named-lock helpers
#
# Honker named locks are accessed via SQL functions:
#   honker_lock_acquire(name, owner, ttl_s) -> int (1 = acquired, 0 = failed)
#   honker_lock_release(name, owner) -> None
# These are called through `conn.transaction().query(...)`.
# ---------------------------------------------------------------------------


class NamedLock:
    """A context manager for Honker named locks.

    Usage::

        lock = NamedLock(db_path, "my_lock_name")
        async with lock:
            # critical section — only one process enters
            ...

    When Honker is unavailable, the lock is a no-op (always acquired).
    """

    def __init__(
        self,
        db_path: str,
        lock_name: str,
        ttl_seconds: float = 60.0,
        owner_id: str | None = None,
    ) -> None:
        self._db_path = db_path
        self._lock_name = lock_name
        self._ttl = ttl_seconds
        self._owner = owner_id or _HONKER_WORKER_ID
        self._conn: Any = None
        self._acquired = False

    async def __aenter__(self) -> bool:
        if not availability():
            self._acquired = True
            return True

        try:
            conn = _get_honker_connection(self._db_path)
            self._conn = conn
            with conn.transaction() as tx:
                result = tx.query(
                    "SELECT honker_lock_acquire(?, ?, ?) AS acquired",
                    (self._lock_name, self._owner, int(self._ttl)),
                )
            acquired = bool(result[0]["acquired"]) if result else False
            self._acquired = acquired
            return self._acquired
        except RuntimeError:
            if _honker_required():
                raise
            self._acquired = True  # fallback: allow execution
            return True
        except Exception as exc:
            logger.warning(
                "[Honker] Failed to acquire lock '%s': %s",
                self._lock_name,
                exc,
            )
            if _honker_required():
                raise
            self._acquired = True  # fallback
            return True

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        if not self._acquired or self._conn is None:
            return
        try:
            with self._conn.transaction() as tx:
                tx.query(
                    "SELECT honker_lock_release(?, ?)",
                    (self._lock_name, self._owner),
                )
        except Exception as exc:
            logger.warning(
                "[Honker] Failed to release lock '%s': %s",
                self._lock_name,
                exc,
            )


def lock_acquire(
    db_path: str,
    lock_name: str,
    owner: str | None = None,
    ttl_seconds: float = 60.0,
) -> bool:
    """Acquire a named lock synchronously using the SQL function.

    Uses ``honker_lock_acquire(name, owner, ttl_s)`` internally.

    Returns True if the lock was acquired or Honker is unavailable.
    """
    if not availability():
        return True

    try:
        conn = _get_honker_connection(db_path)
        with conn.transaction() as tx:
            result = tx.query(
                "SELECT honker_lock_acquire(?, ?, ?) AS acquired",
                (lock_name, owner or _HONKER_WORKER_ID, int(ttl_seconds)),
            )
        return bool(result[0]["acquired"]) if result else False
    except RuntimeError:
        if _honker_required():
            raise
        return True
    except Exception as exc:
        logger.warning("[Honker] Failed to acquire lock '%s': %s", lock_name, exc)
        if _honker_required():
            raise
        return True


def lock_release(
    db_path: str,
    lock_name: str,
    owner: str | None = None,
) -> bool:
    """Release a named lock synchronously using the SQL function.

    Uses ``honker_lock_release(name, owner)`` internally.
    """
    if not availability():
        return True

    try:
        conn = _get_honker_connection(db_path)
        with conn.transaction() as tx:
            tx.query(
                "SELECT honker_lock_release(?, ?)",
                (lock_name, owner or _HONKER_WORKER_ID),
            )
        return True
    except Exception as exc:
        logger.warning("[Honker] Failed to release lock '%s': %s", lock_name, exc)
        if _honker_required():
            raise
        return True


# ---------------------------------------------------------------------------
# Scheduler helpers
# ---------------------------------------------------------------------------

def schedule_once(
    db_path: str,
    task_name: str,
    run_at: str,
    payload: dict[str, Any] | None = None,
) -> bool:
    """Schedule a one-shot task via Honker's scheduler.

    Args:
        db_path: Path to the SQLite database.
        task_name: Unique task identifier.
        run_at: ISO 8601 UTC datetime string.
        payload: Optional task payload.

    Returns:
        True if scheduled, False if Honker is unavailable.
    """
    if not availability():
        return False

    try:
        conn = _get_honker_connection(db_path)
        conn.schedule(task_name, run_at, payload or {})
        return True
    except RuntimeError:
        if _honker_required():
            raise
        return False
    except Exception as exc:
        logger.warning("[Honker] Failed to schedule task '%s': %s", task_name, exc)
        if _honker_required():
            raise
        return False


# ---------------------------------------------------------------------------
# Convenience: publish a "soundboard event" that triggers SSE or polling
# ---------------------------------------------------------------------------

def publish_soundboard_event(
    db_path: str,
    event_type: str,
    data: dict[str, Any] | None = None,
) -> bool:
    """Publish a coarse soundboard change event.

    These events drive Server-Sent Events (SSE) and cross-process live
    updates.  When Honker is unavailable, this is a no-op and the web
    UI falls back to polling.

    Event types (``event_type``):
        ``playback_queued`` — A sound or control request was just queued.
        ``sound_imported`` — A new sound was approved/inserted.
        ``upload_job_changed`` — An upload job status changed.
        ``control_room_changed`` — Bot control-room status changed.  Also
            published centrally from ``AudioService`` on every actual playback
            start (``reason=playback_started``) and finish
            (``reason=playback_finished``) so the web control room refreshes
            consistently regardless of which code path initiated playback.
        ``actions_changed`` — A new action was logged.
        ``sounds_changed`` — Sound inventory changed.
    """
    if not availability():
        return False

    payload: dict[str, Any] = {"type": event_type}
    if data:
        payload["data"] = data

    try:
        # Publish both as a notification (hot wake) and stream event
        # (replay for slow consumers).
        conn = _get_honker_connection(db_path)
        with conn.transaction() as tx:
            tx.notify("soundboard_events", payload)

        stream = conn.stream("soundboard_events")
        stream.publish(payload)
        return True
    except RuntimeError:
        if _honker_required():
            raise
        return False
    except Exception as exc:
        logger.warning(
            "[Honker] Failed to publish soundboard event '%s': %s",
            event_type,
            exc,
        )
        if _honker_required():
            raise
        return False
