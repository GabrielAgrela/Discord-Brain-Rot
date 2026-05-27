"""
Flask app factory for the optional web UI.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import os
from pathlib import Path
import threading

from flask import Flask

from werkzeug.serving import is_running_from_reloader

from bot.web.route_helpers import _run_web_upload_job

from bot.repositories.web_upload_job import WebUploadJobRepository
from bot.services.web_auth import WebAuthService
from bot.services.text_censor import TextCensorService
from bot.repositories.web_system_status import WebSystemStatusRepository
from bot.services.web_system_monitor import WebSystemMonitorService
from bot.web.routes import register_web_routes


def create_app() -> Flask:
    """
    Build the Flask web application.

    Returns:
        Configured Flask application.
    """
    web_root = Path(__file__).resolve().parent
    project_root = web_root.parents[1]
    app = Flask(
        __name__,
        template_folder=str(web_root / "templates"),
    )
    app.config.setdefault("DATABASE_PATH", "data/database.db")
    app.config.setdefault("SOUNDS_DIR", str(project_root / "sounds"))
    app.config["SECRET_KEY"] = app.config.get("SECRET_KEY") or os.getenv(
        "WEB_SESSION_SECRET",
        "discord-brain-rot-web-dev",
    )
    app.config.setdefault("DISCORD_API_BASE_URL", "https://discord.com/api")
    app.config["SESSION_PERMANENT"] = app.config.get("SESSION_PERMANENT", True)
    app.config["SESSION_COOKIE_HTTPONLY"] = app.config.get(
        "SESSION_COOKIE_HTTPONLY",
        True,
    )
    app.config["SESSION_COOKIE_SAMESITE"] = (
        app.config.get("SESSION_COOKIE_SAMESITE") or "Lax"
    )
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(
        days=_get_web_session_lifetime_days()
    )

    if os.getenv("FLASK_ENV", "").strip().lower() == "development":
        app.config["SESSION_COOKIE_SECURE"] = app.config.get(
            "SESSION_COOKIE_SECURE",
            False,
        )
    else:
        app.config["SESSION_COOKIE_SECURE"] = app.config.get(
            "SESSION_COOKIE_SECURE",
            True,
        )

    app.extensions["web_auth_service"] = WebAuthService()
    app.extensions["web_text_censor_service"] = TextCensorService()
    app.extensions["web_system_monitor_service"] = WebSystemMonitorService(
        repository=WebSystemStatusRepository(
            db_path=app.config["DATABASE_PATH"],
            use_shared=False,
        )
    )
    app.extensions["web_upload_executor"] = ThreadPoolExecutor(
        max_workers=_get_web_upload_worker_count()
    )
    app.extensions["web_upload_jobs"] = {}

    # Validate Honker availability early (will fail fast if HONKER_REQUIRED=true).
    try:
        from bot.services.honker_integration import ensure_available as _ensure_honker
        _ensure_honker(app.config["DATABASE_PATH"])
    except ImportError:
        pass

    _start_honker_upload_workers(app)
    _resume_pending_upload_jobs(app)
    app.extensions["web_keyword_scan_executor"] = ThreadPoolExecutor(
        max_workers=_get_web_keyword_scan_worker_count()
    )
    app.extensions["web_keyword_scan_jobs"] = {}
    app.extensions["web_transcript_executor"] = ThreadPoolExecutor(
        max_workers=_get_web_transcript_worker_count()
    )
    app.extensions["web_transcript_jobs"] = {}

    register_web_routes(app)
    return app


def _get_web_session_lifetime_days() -> int:
    """
    Return the configured persistent login lifetime in days.

    Returns:
        Positive number of days to keep Discord web sessions signed in.
    """
    raw_value = os.getenv("WEB_SESSION_LIFETIME_DAYS", "30").strip()
    try:
        lifetime_days = int(raw_value)
    except ValueError:
        lifetime_days = 30
    return max(1, lifetime_days)


def _get_web_upload_worker_count() -> int:
    """
    Return the number of background workers for web upload processing.

    Returns:
        Positive worker count for async upload jobs.
    """
    raw_value = os.getenv("WEB_UPLOAD_WORKERS", "2").strip()
    try:
        worker_count = int(raw_value)
    except ValueError:
        worker_count = 2
    return max(1, min(worker_count, 8))


def _get_honker_upload_worker_count() -> int:
    """
    Return the number of Honker durable queue upload workers.

    Separate from ``WEB_UPLOAD_WORKERS`` so that the Honker claim loop
    can use fewer workers and reduce cross-process SQLite write-lock
    pressure. Defaults to **1**.

    Returns:
        Positive worker count bounded 1‑4.
    """
    raw_value = os.getenv("HONKER_UPLOAD_WORKERS", "1").strip()
    try:
        worker_count = int(raw_value)
    except ValueError:
        worker_count = 1
    return max(1, min(worker_count, 4))


def _should_start_honker_upload_workers(app: Flask) -> bool:
    """
    Return ``True`` if Honker upload workers should be started in this process.

    Guards against:
    * Starting workers in the Werkzeug debug reloader **parent** process
      (which would leave orphan workers after the child starts).
    * Starting workers more than once per app instance.

    ``is_running_from_reloader()`` returns ``True`` for the reloader child
    (the actual server) and ``False`` for the parent monitor process and
    for production (no reloader at all).  When ``False``, we distinguish
    by checking whether debug/reloader mode is likely active.

    Args:
        app: The Flask application instance.

    Returns:
        ``True`` when workers should be started.
    """
    # Idempotency guard — start workers at most once per app instance.
    already_started: bool = app.extensions.get(
        "honker_upload_workers_started", False
    )
    if already_started:
        return False

    app.extensions["honker_upload_workers_started"] = True

    # When the Werkzeug reloader is active, only the reloader child
    # should start background workers.  The reloader parent only
    # monitors files.
    if is_running_from_reloader():
        # Reloader child — the actual request-serving process.
        return True

    # Not the reloader child.  Could be the reloader parent (debug mode
    # active) or production (no reloader at all).  If debug env vars are
    # present, a reloader is likely active and this is the parent.
    if os.environ.get("FLASK_ENV", "").strip().lower() == "development" or \
       os.environ.get("FLASK_DEBUG", "").strip().lower() in ("1", "true", "yes"):
        return False

    # Production or no reloader — always start workers.
    return True


def _get_web_keyword_scan_worker_count() -> int:
    """
    Return the number of background workers for keyword scanning.

    Returns:
        Positive worker count for async keyword scan jobs, bounded 1‑8.
    """
    raw_value = os.getenv("WEB_KEYWORD_SCAN_WORKERS", "2").strip()
    try:
        worker_count = int(raw_value)
    except ValueError:
        worker_count = 2
    return max(1, min(worker_count, 8))


def _resume_pending_upload_jobs(app: Flask) -> None:
    """
    Resume recoverable web upload jobs from persistent storage.

    Jobs in 'queued' or stale 'processing' status (under max attempts)
    are re-submitted to the executor.  File-upload jobs whose temp file
    no longer exists are marked as error.
    """
    db_path = app.config["DATABASE_PATH"]
    sounds_dir = app.config["SOUNDS_DIR"]
    executor: ThreadPoolExecutor = app.extensions["web_upload_executor"]
    jobs: dict = app.extensions["web_upload_jobs"]

    try:
        repo = WebUploadJobRepository(db_path=db_path, use_shared=False)
        recoverable = repo.get_recoverable_jobs(max_attempts=3, stale_seconds=300)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "[WebUpload] Failed to scan for recoverable jobs: %s", exc
        )
        return

    for row in recoverable:
        job_id = str(row["job_id"])
        temp_path = row.get("temp_upload_path")

        # Mark queued -> processing in memory.
        jobs[job_id] = {"job_id": job_id, "status": "processing"}

        # Update DB status back to queued for retry.
        try:
            repo.update_status(job_id, status="queued")
        except Exception:
            pass

        # Check temp file existence for file-based jobs.
        temp_upload_path = str(temp_path) if temp_path else None
        if temp_upload_path and not Path(temp_upload_path).exists():
            # Temp file gone — can only resume URL-based jobs.
            source_url = str(row.get("source_url") or "").strip()
            if not source_url:
                repo.update_status(
                    job_id,
                    status="error",
                    error="Temp upload file no longer exists on disk after restart",
                )
                jobs[job_id] = {
                    "job_id": job_id,
                    "status": "error",
                    "error": "Temp upload file no longer exists on disk after restart",
                }
                continue
            # URL-based job: clear temp path, re-submit.
            temp_upload_path = None

        try:
            current_user_payload_str = row.get("current_user_json") or "{}"
            current_user_payload = json.loads(current_user_payload_str)
        except (json.JSONDecodeError, TypeError):
            repo.update_status(
                job_id,
                status="error",
                error="Invalid current_user_json after restart",
            )
            jobs[job_id] = {
                "job_id": job_id,
                "status": "error",
                "error": "Invalid user data after restart",
            }
            continue

        executor.submit(
            _run_web_upload_job,
            job_id=job_id,
            jobs=jobs,
            db_path=db_path,
            sounds_dir=sounds_dir,
            temp_upload_path=temp_upload_path,
            original_filename=str(row.get("original_filename") or ""),
            current_user_payload=current_user_payload,
            guild_id=row.get("guild_id"),
            custom_name=str(row.get("custom_name") or ""),
            source_url=str(row.get("source_url") or ""),
            time_limit=row.get("time_limit"),
        )


def _start_honker_upload_workers(app: Flask) -> None:
    """
    Start background daemon threads that consume Honker ``web_upload_jobs``
    queue and process them via ``_run_web_upload_job``.

    Guards against starting in the Werkzeug debug reloader parent process
    and against duplicate starts per app instance.  When Honker is
    unavailable, this is a no-op and the legacy ``ThreadPoolExecutor``
    fallback is used instead.

    .. note::
       Workers sleep for 10 s (instead of 1 s) when no jobs are found,
       reducing cross-process SQLite write-lock pressure during idle
       periods.
    """
    import logging as _logging
    _logger = _logging.getLogger(__name__)

    if not _should_start_honker_upload_workers(app):
        return

    db_path = app.config["DATABASE_PATH"]
    sounds_dir = app.config["SOUNDS_DIR"]
    jobs: dict = app.extensions.setdefault("web_upload_jobs", {})

    try:
        from bot.services.honker_integration import (
            availability as _honker_available,
            claim_jobs as _claim_honker,
            complete_job as _complete_honker,
        )
    except ImportError:
        return

    if not _honker_available():
        return

    worker_count = _get_honker_upload_worker_count()

    # Idle backoff: sleep longer when no jobs are found so that the
    # claim loop does not issue a write transaction every second on an
    # idle queue, which causes cross-process SQLite lock contention.
    _IDLE_SLEEP_SECONDS = 10.0
    _ACTIVE_SLEEP_SECONDS = 1.0

    def _honker_worker_loop(worker_id: str) -> None:
        """Daemon thread that claims and processes Honker upload jobs."""
        import time as _time
        import traceback as _tb

        consecutive_claim_errors = 0
        consecutive_idle_cycles = 0

        while True:
            try:
                claimed = _claim_honker(
                    db_path, "web_upload_jobs",
                    worker_id=worker_id, batch_size=1,
                )
                consecutive_claim_errors = 0  # reset on successful claim

                if not claimed:
                    # No jobs — idle backoff to reduce write-lock pressure.
                    consecutive_idle_cycles += 1
                    sleep_s = min(
                        _IDLE_SLEEP_SECONDS * consecutive_idle_cycles,
                        30.0,
                    )
                    _time.sleep(sleep_s)
                    continue

                # Reset idle counter when work is found.
                consecutive_idle_cycles = 0

                for job in claimed:
                    job_id = str(job.payload.get("job_id", ""))
                    if not job_id:
                        continue
                    _logger.info(
                        "[HonkerUpload] Worker %s claimed job %s",
                        worker_id, job_id,
                    )
                    # Load job params from DB
                    try:
                        repo = WebUploadJobRepository(
                            db_path=db_path, use_shared=False
                        )
                        row = repo.get_by_id(job_id)
                    except Exception:
                        row = None

                    if row is None:
                        _logger.warning(
                            "[HonkerUpload] Job %s not found in DB, acking",
                            job_id,
                        )
                        try:
                            _complete_honker(
                                db_path, "web_upload_jobs", job
                            )
                        except Exception:
                            pass
                        continue

                    # Mark queued -> processing in memory
                    jobs[job_id] = {"job_id": job_id, "status": "processing"}
                    try:
                        repo.update_status(job_id, status="queued")
                    except Exception:
                        pass

                    # Prepare params for _run_web_upload_job
                    temp_upload_path = row.get("temp_upload_path")
                    current_user_payload_str = (
                        row.get("current_user_json") or "{}"
                    )
                    try:
                        current_user_payload = json.loads(
                            current_user_payload_str
                        )
                    except (json.JSONDecodeError, TypeError):
                        current_user_payload = {}

                    # Run the upload job
                    _run_web_upload_job(
                        job_id=job_id,
                        jobs=jobs,
                        db_path=db_path,
                        sounds_dir=sounds_dir,
                        temp_upload_path=(
                            str(temp_upload_path) if temp_upload_path else None
                        ),
                        original_filename=(
                            str(row.get("original_filename") or "")
                        ),
                        current_user_payload=current_user_payload,
                        guild_id=row.get("guild_id"),
                        custom_name=str(row.get("custom_name") or ""),
                        source_url=str(row.get("source_url") or ""),
                        time_limit=row.get("time_limit"),
                    )

                    # Ack the Honker job
                    try:
                        _complete_honker(db_path, "web_upload_jobs", job)
                    except Exception:
                        pass

                # Brief sleep between claim cycles to avoid busy-looping
                _time.sleep(_ACTIVE_SLEEP_SECONDS)
            except RuntimeError as exc:
                # Transient Honker error (e.g. database locked) — concise log
                consecutive_claim_errors += 1
                backoff = min(5.0 * consecutive_claim_errors, 30.0)
                _logger.warning(
                    "[HonkerUpload] Worker %s transient error "
                    "(attempt %d, sleeping %.1fs): %s",
                    worker_id,
                    consecutive_claim_errors,
                    backoff,
                    exc,
                )
                _time.sleep(backoff)
            except Exception:
                # Unexpected processing error — show traceback
                consecutive_claim_errors = 0
                _logger.error(
                    "[HonkerUpload] Worker %s unexpected error:\n%s",
                    worker_id,
                    _tb.format_exc(),
                )
                _time.sleep(5.0)

    for i in range(worker_count):
        worker_id = f"honker-upload-{i + 1}"
        thread = threading.Thread(
            target=_honker_worker_loop,
            args=(worker_id,),
            daemon=True,
            name=worker_id,
        )
        thread.start()
        _logger.info(
            "[HonkerUpload] Started worker %s", worker_id
        )


def _get_web_transcript_worker_count() -> int:
    """
    Return the number of background workers for auto-transcript jobs.

    Returns:
        Positive worker count for async transcript jobs, bounded 1‑4.
    """
    raw_value = os.getenv("WEB_TRANSCRIPT_WORKERS", "1").strip()
    try:
        worker_count = int(raw_value)
    except ValueError:
        worker_count = 1
    return max(1, min(worker_count, 4))
