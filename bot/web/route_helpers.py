"""
Shared helpers for Flask web route modules.
"""

from __future__ import annotations

import logging
import os
import tempfile
import uuid
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Mapping

from flask import current_app, jsonify, request, session, url_for
from werkzeug.datastructures import FileStorage

from config import TTS_PROFILES
from bot.models.web import DiscordWebUser, PaginatedQuery
from bot.repositories.action import ActionRepository
from bot.repositories.event import EventRepository
from bot.repositories.list import ListRepository
from bot.repositories.sound import SoundRepository
from bot.repositories.voice_activity import VoiceActivityRepository
from bot.repositories.web_analytics import WebAnalyticsRepository
from bot.repositories.web_content import WebContentRepository
from bot.repositories.web_control_room import WebControlRoomRepository
from bot.repositories.web_guild import WebGuildRepository
from bot.repositories.web_upload import WebUploadRepository
from bot.repositories.web_user_access import WebUserAccessRepository
from bot.services.web_analytics import WebAnalyticsService
from bot.services.web_auth import WebAuthService
from bot.services.web_content import WebContentService
from bot.services.web_control_room import WebControlRoomService
from bot.services.web_guild import WebGuildService
from bot.services.web_playback import WebPlaybackService
from bot.services.web_sound_options import WebSoundOptionsService
from bot.services.web_tts_enhancer import WebTtsEnhancerService
from bot.services.web_upload import WebUploadService

logger = logging.getLogger(__name__)


def _get_auth_service() -> WebAuthService:
    """Return the shared web auth service."""
    return current_app.extensions["web_auth_service"]


def _get_web_content_service() -> WebContentService:
    """Build a content service for the current request config."""
    db_path = current_app.config["DATABASE_PATH"]
    return WebContentService(
        repository=WebContentRepository(
            db_path=db_path,
            use_shared=False,
        ),
        text_censor_service=current_app.extensions["web_text_censor_service"],
        user_access_repository=WebUserAccessRepository(
            db_path=db_path,
            use_shared=False,
        ),
        sounds_dir=current_app.config["SOUNDS_DIR"],
    )


def _get_web_analytics_service() -> WebAnalyticsService:
    """Build an analytics service for the current request config."""
    db_path = current_app.config["DATABASE_PATH"]
    return WebAnalyticsService(
        repository=WebAnalyticsRepository(
            db_path=db_path,
            use_shared=False,
        ),
        text_censor_service=current_app.extensions["web_text_censor_service"],
        user_access_repository=WebUserAccessRepository(
            db_path=db_path,
            use_shared=False,
        ),
    )


def _get_web_playback_service() -> WebPlaybackService:
    """Build a playback service for the current request config."""
    db_path = current_app.config["DATABASE_PATH"]
    return WebPlaybackService(
        sound_repository=SoundRepository(db_path=db_path, use_shared=False),
        db_path=db_path,
    )


def _get_web_sound_options_service() -> WebSoundOptionsService:
    """Build a sound-options service for the current request config."""
    db_path = current_app.config["DATABASE_PATH"]
    return WebSoundOptionsService(
        sound_repository=SoundRepository(db_path=db_path, use_shared=False),
        list_repository=ListRepository(db_path=db_path, use_shared=False),
        action_repository=ActionRepository(db_path=db_path, use_shared=False),
        event_repository=EventRepository(db_path=db_path, use_shared=False),
        voice_activity_repository=VoiceActivityRepository(db_path=db_path, use_shared=False),
    )


def _get_web_guild_service() -> WebGuildService:
    """Build a guild service for the current request config."""
    db_path = current_app.config["DATABASE_PATH"]
    return WebGuildService(
        repository=WebGuildRepository(db_path=db_path, use_shared=False),
    )


def _get_web_upload_service() -> WebUploadService:
    """Build an upload service for the current request config."""
    db_path = current_app.config["DATABASE_PATH"]
    return WebUploadService(
        upload_repository=WebUploadRepository(db_path=db_path, use_shared=False),
        sound_repository=SoundRepository(db_path=db_path, use_shared=False),
        action_repository=ActionRepository(db_path=db_path, use_shared=False),
        sounds_dir=current_app.config["SOUNDS_DIR"],
    )


def _queue_web_upload_job(
    *,
    uploaded_file: FileStorage | None,
    current_user: DiscordWebUser,
    guild_id: int | None,
    custom_name: str | None,
    source_url: str | None,
    time_limit: int | None,
) -> str:
    """Persist request-local upload data and submit background processing."""
    sounds_dir = Path(current_app.config["SOUNDS_DIR"])
    temp_upload_path: str | None = None
    original_filename: str | None = None
    if uploaded_file is not None and uploaded_file.filename:
        original_filename = uploaded_file.filename
        temp_dir = sounds_dir.parent
        temp_dir.mkdir(parents=True, exist_ok=True)
        suffix = ".mp3" if original_filename.lower().endswith(".mp3") else ".upload"
        with tempfile.NamedTemporaryFile(
            prefix="web_upload_",
            suffix=suffix,
            dir=str(temp_dir),
            delete=False,
        ) as temp_file:
            uploaded_file.save(temp_file)
            temp_upload_path = temp_file.name

    job_id = uuid.uuid4().hex
    jobs = current_app.extensions.setdefault("web_upload_jobs", {})
    jobs[job_id] = {"job_id": job_id, "status": "processing"}

    db_path = current_app.config["DATABASE_PATH"]
    executor = current_app.extensions["web_upload_executor"]
    executor.submit(
        _run_web_upload_job,
        job_id=job_id,
        jobs=jobs,
        db_path=db_path,
        sounds_dir=str(sounds_dir),
        temp_upload_path=temp_upload_path,
        original_filename=original_filename,
        current_user_payload=current_user.to_session_payload(),
        guild_id=guild_id,
        custom_name=custom_name,
        source_url=source_url,
        time_limit=time_limit,
    )
    return job_id


def _run_web_upload_job(
    *,
    job_id: str,
    jobs: dict[str, Any],
    db_path: str,
    sounds_dir: str,
    temp_upload_path: str | None,
    original_filename: str | None,
    current_user_payload: Mapping[str, Any],
    guild_id: int | None,
    custom_name: str | None,
    source_url: str | None,
    time_limit: int | None,
) -> None:
    """Process one queued web upload outside the Flask request thread."""
    file_handle = None
    try:
        uploaded_file = None
        if temp_upload_path:
            file_handle = open(temp_upload_path, "rb")
            uploaded_file = FileStorage(
                stream=file_handle,
                filename=original_filename or Path(temp_upload_path).name,
            )

        service = WebUploadService(
            upload_repository=WebUploadRepository(db_path=db_path, use_shared=False),
            sound_repository=SoundRepository(db_path=db_path, use_shared=False),
            action_repository=ActionRepository(db_path=db_path, use_shared=False),
            sounds_dir=sounds_dir,
        )
        current_user = DiscordWebUser.from_session_payload(current_user_payload)
        if current_user is None:
            raise ValueError("Discord login required")
        payload = service.save_upload(
            uploaded_file=uploaded_file,
            current_user=current_user,
            guild_id=guild_id,
            custom_name=custom_name,
            source_url=source_url,
            time_limit=time_limit,
        )
        jobs[job_id] = {"job_id": job_id, "status": "approved", **payload}
    except ValueError as exc:
        jobs[job_id] = {"job_id": job_id, "status": "error", "error": str(exc)}
    except Exception:
        logger.exception("Unexpected error processing web upload job")
        jobs[job_id] = {
            "job_id": job_id,
            "status": "error",
            "error": "Internal server error",
        }
    finally:
        if file_handle is not None:
            file_handle.close()
        if temp_upload_path:
            Path(temp_upload_path).unlink(missing_ok=True)


def _get_web_control_room_service() -> WebControlRoomService:
    """Build a control-room service for the current request config."""
    db_path = current_app.config["DATABASE_PATH"]
    return WebControlRoomService(
        repository=WebControlRoomRepository(db_path=db_path, use_shared=False),
        db_path=db_path,
    )


def _get_web_tts_enhancer_service() -> WebTtsEnhancerService:
    """Return the shared web TTS enhancer service."""
    service = current_app.extensions.get("web_tts_enhancer_service")
    if service is None:
        service = WebTtsEnhancerService()
        current_app.extensions["web_tts_enhancer_service"] = service
    return service


def _build_tts_profile_options() -> list[dict[str, str]]:
    """Return TTS profile options for the web control-room modal."""
    return [
        {
            "value": key,
            "label": str(profile.get("display") or key),
            "provider": str(profile.get("provider") or "gtts"),
        }
        for key, profile in TTS_PROFILES.items()
    ]


def _build_discord_redirect_uri() -> str:
    """Return the Discord OAuth callback URL."""
    oauth_config = _get_auth_service().get_oauth_config()
    if oauth_config["redirect_uri"]:
        return oauth_config["redirect_uri"]
    return url_for("discord_callback", _external=True)


def _get_current_discord_user() -> DiscordWebUser | None:
    """Return the authenticated Discord user from session state."""
    return _get_auth_service().get_current_user(session.get("discord_user"))


def _require_discord_login_api(view_func: Callable[..., Any]) -> Callable[..., Any]:
    """Require Discord authentication for JSON API access."""

    @wraps(view_func)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        if _get_current_discord_user() is None:
            return jsonify(
                {
                    "error": "Discord login required",
                    "login_url": url_for("login", next=request.path),
                }
            ), 401
        return view_func(*args, **kwargs)

    return wrapped


def _require_web_admin_api(view_func: Callable[..., Any]) -> Callable[..., Any]:
    """Require owner allowlist admin rights for web moderation APIs."""

    @wraps(view_func)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        if not _current_web_user_is_admin():
            return jsonify({"error": "Admin access required"}), 403
        return view_func(*args, **kwargs)

    return wrapped


def _build_paginated_query(filter_names: tuple[str, ...]) -> PaginatedQuery:
    """Build a paginated query model from request args."""
    selected_guild_id = _get_selected_guild_id(request.args)
    _remember_selected_guild_id(selected_guild_id)
    return PaginatedQuery(
        page=_parse_positive_int_arg("page", 1),
        per_page=_parse_positive_int_arg("per_page", 10),
        search_query=request.args.get("search", "").strip(),
        guild_id=selected_guild_id,
        filters={name: _get_filter_values(name) for name in filter_names},
    )


def _parse_include_filters_arg() -> bool:
    """Return whether a paginated endpoint should include filter metadata."""
    return request.args.get("include_filters", "1").strip().lower() not in {
        "0",
        "false",
        "no",
    }


def _parse_positive_int_arg(name: str, default: int) -> int:
    """Return a positive integer query arg or the provided default."""
    parsed = _parse_optional_positive_int(request.args.get(name, default))
    return parsed if parsed is not None else default


def _parse_optional_positive_int(value: Any) -> int | None:
    """Return a positive integer value, or None when absent/invalid."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _parse_int_arg(name: str, default: int) -> int:
    """Return an integer query arg or the provided default."""
    try:
        return int(request.args.get(name, default))
    except (TypeError, ValueError):
        return default


def _get_filter_values(param_name: str) -> list[str]:
    """Return normalized multi-value filters from the query string."""
    return [value.strip() for value in request.args.getlist(param_name) if value.strip()]


def _build_initial_soundboard_data(selected_guild_id: int | None = None) -> dict[str, dict[str, Any]]:
    """Return first-page soundboard data for the initial HTML paint."""
    service = _get_web_content_service()
    base_query = PaginatedQuery(page=1, per_page=7, guild_id=selected_guild_id)

    return {
        "actions": _prepare_initial_payload(
            service.get_actions(
                base_query,
                filter_keys=("action", "user"),
                current_user=_get_current_discord_user(),
            ),
            filter_keys=("action", "user"),
        ),
        "favorites": _prepare_initial_payload(
            service.get_favorites(
                base_query,
                current_user=_get_current_discord_user(),
            ),
            filter_keys=("user",),
        ),
        "all_sounds": _prepare_initial_payload(
            service.get_all_sounds(
                base_query,
                filter_keys=("list",),
                current_user=_get_current_discord_user(),
            ),
            filter_keys=("list",),
        ),
    }


def _prepare_initial_payload(
    payload: dict[str, Any],
    filter_keys: tuple[str, ...],
) -> dict[str, Any]:
    """Add template-only display fields without changing API payloads."""
    items = []
    for item in payload.get("items", []):
        display_item = dict(item)
        if display_item.get("timestamp"):
            display_item["display_time_ago"] = _format_time_ago(display_item["timestamp"])
        items.append(display_item)

    filters = payload.get("filters", {})
    visible_filters = {key: filters.get(key, []) for key in filter_keys}

    return {
        **payload,
        "items": items,
        "filters": visible_filters,
    }


def _format_time_ago(timestamp: str) -> str:
    """Format a database timestamp similarly to the browser table renderer."""
    parsed_timestamp = _parse_web_timestamp(timestamp)
    if parsed_timestamp is None:
        return timestamp or ""

    now = datetime.now(timezone.utc)
    diff_seconds = max(0, int((now - parsed_timestamp).total_seconds()))
    diff_minutes = diff_seconds // 60
    diff_hours = diff_seconds // 3600
    diff_days = diff_seconds // 86400

    if diff_minutes < 1:
        return "now"
    if diff_minutes < 60:
        return f"{diff_minutes}m"
    if diff_hours < 24:
        return f"{diff_hours}h"
    if diff_days < 30:
        return f"{diff_days}d"
    return parsed_timestamp.strftime("%x")


def _parse_web_timestamp(timestamp: str) -> datetime | None:
    """Parse a SQLite timestamp as UTC unless it already has a timezone."""
    value = str(timestamp or "").strip()
    if not value:
        return None

    normalized = value.replace(" ", "T")
    if normalized.endswith(("Z", "z")):
        normalized = f"{normalized[:-1]}+00:00"

    try:
        parsed_timestamp = datetime.fromisoformat(normalized)
    except ValueError:
        return None

    if parsed_timestamp.tzinfo is None:
        return parsed_timestamp.replace(tzinfo=timezone.utc)
    return parsed_timestamp.astimezone(timezone.utc)


def _get_selected_guild_id(values: Mapping[str, Any]) -> int | None:
    """Resolve selected guild ID from request values and session."""
    return _get_web_guild_service().resolve_selected_guild_id(
        values,
        session.get("selected_guild_id"),
    )


def _remember_selected_guild_id(guild_id: Any) -> None:
    """Persist a selected guild ID in the web session."""
    try:
        parsed = int(str(guild_id).strip())
    except (TypeError, ValueError):
        return
    if parsed > 0:
        session["selected_guild_id"] = str(parsed)


def _current_web_user_is_admin() -> bool:
    """Return whether the current web user matches bot admin/mod rules."""
    current_user = _get_current_discord_user()
    if current_user is None:
        return False
    owner_ids = {
        value.strip()
        for value in os.getenv("OWNER_USER_IDS", "").split(",")
        if value.strip()
    }
    if current_user.id in owner_ids:
        return True

    selected_guild_id = _get_selected_guild_id(request.values)
    admin_guild_ids = {str(guild_id) for guild_id in current_user.admin_guild_ids}
    if selected_guild_id is not None:
        return str(selected_guild_id) in admin_guild_ids
    return bool(admin_guild_ids)
