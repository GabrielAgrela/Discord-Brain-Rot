"""
Server-Sent Events (SSE) endpoint for live web UI updates.

Provides a ``/api/events`` endpoint that streams coarse-grained change
notifications to the soundboard frontend, reducing polling latency.

When Honker is available, the stream is driven by a background daemon
thread that subscribes to Honker stream events via an asyncio event loop
and pushes them to a thread-safe queue consumed by the Flask SSE generator.
When Honker is unavailable, the stream sends periodic heartbeats so the
EventSource stays open and the frontend can fall back to its existing polling.
"""

from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
import time
from typing import Any, Generator

from flask import Flask, Response, current_app, request, stream_with_context

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SSE endpoint
# ---------------------------------------------------------------------------

_HEARTBEAT_INTERVAL = 15.0  # seconds between heartbeat comments if idle


def _format_sse(data: Any, event: str | None = None) -> str:
    """Format a Server-Sent Event payload."""
    lines = [f"data: {json.dumps(data)}"]
    if event:
        lines.insert(0, f"event: {event}")
    body_lines = [f"{line}\n" for line in lines]
    return "".join(body_lines) + "\n"


def register_event_routes(app: Flask) -> None:
    """Register the SSE event stream route."""

    @app.route("/api/events")
    def stream_events() -> Response:
        """
        Return a Server-Sent Events stream for live web UI updates.

        The client sends an EventSource to this endpoint.  When Honker is
        available, the stream consumes events from a queue filled by a
        background Honker listener thread.  Otherwise the stream sends
        periodic heartbeats and the frontend relies on its existing polling
        fallback.
        """
        # Check for text/event-stream Accept to avoid breaking tooling.
        accept = request.headers.get("Accept", "")
        if "text/event-stream" not in accept and "text/html" not in accept:
            return Response(
                json.dumps({
                    "status": "sse_available",
                    "heartbeat_interval": _HEARTBEAT_INTERVAL,
                }),
                mimetype="application/json",
            )

        db_path = current_app.config["DATABASE_PATH"]

        def _generate() -> Generator[str, Any, None]:
            """Generate SSE events."""
            # Initial connected event.
            yield _format_sse(
                {"type": "connected", "heartbeat_interval": _HEARTBEAT_INTERVAL},
                event="connected",
            )

            # Try to start a Honker-based event listener bridge.
            event_queue: queue.Queue[dict[str, Any] | None] = queue.Queue()
            stop_event = threading.Event()
            honker_thread = _start_honker_listener_thread(
                db_path, event_queue, stop_event
            )
            uses_honker = honker_thread is not None

            last_poll = time.monotonic()
            try:
                while True:
                    now = time.monotonic()

                    # Check for Honker events with a short timeout.
                    if uses_honker:
                        try:
                            payload = event_queue.get(timeout=0.5)
                            if payload is not None:
                                event_type = payload.get("type", "unknown")
                                yield _format_sse(payload, event=event_type)
                                last_poll = now
                        except queue.Empty:
                            pass

                    # Send heartbeat if idle.
                    if now - last_poll >= _HEARTBEAT_INTERVAL:
                        last_poll = now
                        yield _format_sse(
                            {"type": "heartbeat", "timestamp": time.time()},
                            event="heartbeat",
                        )

                    time.sleep(0.1)
            except GeneratorExit:
                pass
            finally:
                stop_event.set()

        return Response(
            stream_with_context(_generate()),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )


# ---------------------------------------------------------------------------
# Honker listener bridge (async-to-sync via daemon thread + Queue)
# ---------------------------------------------------------------------------


def _start_honker_listener_thread(
    db_path: str,
    event_queue: queue.Queue[dict[str, Any] | None],
    stop_event: threading.Event,
) -> threading.Thread | None:
    """Start a daemon thread that listens for Honker NOTIFY events.

    The thread runs its own asyncio event loop and pushes notification
    payloads into *event_queue*.  Returns the thread or ``None`` if Honker
    is unavailable.

    Uses ``listen_notifications()`` from the integration layer so that the
    per-thread Honker connection cache is utilised and no direct
    ``honker.open()`` or ``stream.subscribe()`` is needed.
    """
    try:
        from bot.services.honker_integration import (
            availability as _honker_available,
            listen_notifications as _listen_notifications,
        )
    except ImportError:
        return None

    if not _honker_available():
        return None

    def _run_listener() -> None:
        """Daemon thread entry point: consume Honker notifications."""
        async def _listen() -> None:
            try:
                async for notification in _listen_notifications(
                    db_path, "soundboard_events", fallback_poll_s=1.0
                ):
                    if stop_event.is_set():
                        break
                    payload = getattr(notification, "payload", notification)
                    if isinstance(payload, dict):
                        event_queue.put(payload)
            except Exception as exc:
                if not stop_event.is_set():
                    logger.debug("[SSE] Honker listener stopped: %s", exc)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_listen())
        except Exception:
            pass
        finally:
            loop.close()

    thread = threading.Thread(
        target=_run_listener,
        daemon=True,
        name="honker-sse-listener",
    )
    thread.start()
    logger.info("[SSE] Started Honker notification listener thread")
    return thread


# ---------------------------------------------------------------------------
# Event publishing helper
# ---------------------------------------------------------------------------

def publish_soundboard_event(
    event_type: str,
    data: dict[str, Any] | None = None,
) -> None:
    """
    Publish a coarse soundboard change event for SSE consumers.

    This is a lightweight helper that calls the Honker integration
    layer when available.  It is safe to call from any Flask route
    or background thread.

    Args:
        event_type: One of ``playback_queued``, ``sound_imported``,
            ``upload_job_changed``, ``control_room_changed``,
            ``actions_changed``, ``sounds_changed``.
        data: Optional extra payload dict.
    """
    try:
        from bot.services.honker_integration import publish_soundboard_event as _publish
    except ImportError:
        return

    db_path = current_app.config.get("DATABASE_PATH", "")
    if not db_path:
        return

    try:
        started = time.monotonic()
        published = _publish(db_path, event_type, data)
        elapsed = time.monotonic() - started
        if elapsed > 0.2 or not published:
            logger.warning(
                "[SSE] publish event=%s published=%s duration=%.3fs data=%s",
                event_type,
                published,
                elapsed,
                data,
            )
    except Exception:
        logger.warning("[SSE] Failed to publish event %s", event_type, exc_info=True)
