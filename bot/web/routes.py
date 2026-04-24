"""
Route registration for the optional Flask web UI.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable, Mapping

import sqlite3
from flask import (
    Flask,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from bot.models.web import AnalyticsQuery, DiscordWebUser, PaginatedQuery
from bot.repositories.action import ActionRepository
from bot.repositories.sound import SoundRepository
from bot.repositories.web_analytics import WebAnalyticsRepository
from bot.repositories.web_content import WebContentRepository
from bot.repositories.web_control_room import WebControlRoomRepository
from bot.repositories.web_guild import WebGuildRepository
from bot.repositories.web_upload import WebUploadRepository
from bot.repositories.web_user_access import WebUserAccessRepository
from bot.services.web_analytics import WebAnalyticsService
from bot.services.web_auth import DiscordOAuthError, WebAuthService
from bot.services.web_content import WebContentService
from bot.services.web_control_room import WebControlRoomService
from bot.services.web_guild import WebGuildService
from bot.services.web_playback import WebPlaybackService
from bot.services.web_upload import WebUploadService

logger = logging.getLogger(__name__)


def register_web_routes(app: Flask) -> None:
    """
    Register all web routes and template helpers on the Flask app.

    Args:
        app: Flask application to configure.
    """

    @app.context_processor
    def inject_auth_context() -> dict[str, Any]:
        """Expose Discord auth state to templates."""
        return {
            "discord_user": _get_current_discord_user(),
            "web_user_is_admin": _current_web_user_is_admin(),
            "discord_oauth_configured": _get_auth_service().oauth_is_configured(),
            "discord_login_url": url_for("login", next=request.path),
        }

    @app.route("/login")
    def login() -> Any:
        """Start Discord OAuth login."""
        auth_service = _get_auth_service()
        if not auth_service.oauth_is_configured():
            return "Discord OAuth is not configured on this server.", 503

        session.permanent = True
        next_path = auth_service.sanitize_next_path(
            request.args.get("next"),
            url_for("index"),
        )
        session["oauth_next_path"] = next_path
        state = os.urandom(24).hex()
        session["discord_oauth_state"] = state

        return redirect(
            auth_service.build_authorize_url(
                state=state,
                redirect_uri=_build_discord_redirect_uri(),
            )
        )

    @app.route("/auth/discord/callback")
    def discord_callback() -> Any:
        """Handle Discord OAuth callback and persist the user in session."""
        auth_service = _get_auth_service()
        if not auth_service.oauth_is_configured():
            return "Discord OAuth is not configured on this server.", 503

        if request.args.get("error"):
            return f"Discord login failed: {request.args['error']}", 400

        expected_state = session.pop("discord_oauth_state", None)
        returned_state = request.args.get("state", "")
        if not expected_state or expected_state != returned_state:
            return "Discord login failed: invalid state", 400

        code = request.args.get("code", "").strip()
        if not code:
            return "Discord login failed: missing code", 400

        try:
            user = auth_service.exchange_code_for_user(
                code,
                redirect_uri=_build_discord_redirect_uri(),
                api_base_url=current_app.config["DISCORD_API_BASE_URL"],
            )
        except DiscordOAuthError as exc:
            return str(exc), exc.status_code

        session.permanent = True
        session["discord_user"] = user.to_session_payload()
        return redirect(
            auth_service.sanitize_next_path(
                session.pop("oauth_next_path", None),
                url_for("index"),
            )
        )

    @app.route("/logout")
    def logout() -> Any:
        """Clear the current Discord web session."""
        auth_service = _get_auth_service()
        session.pop("discord_user", None)
        session.pop("discord_oauth_state", None)
        return redirect(
            auth_service.sanitize_next_path(
                request.args.get("next") or url_for("index"),
                url_for("index"),
            )
        )

    @app.route("/")
    def index() -> str:
        """Render the soundboard page."""
        selected_guild_id = _get_selected_guild_id(request.args)
        return render_template(
            "index.html",
            initial_soundboard_data=_build_initial_soundboard_data(selected_guild_id),
            guild_options=_get_web_guild_service().get_guild_options(selected_guild_id),
            selected_guild_id=selected_guild_id,
        )

    @app.route("/api/guilds")
    def get_guilds() -> Any:
        """Return web-visible guild options."""
        selected_guild_id = _get_selected_guild_id(request.args)
        return jsonify(
            {
                "guilds": _get_web_guild_service().get_guild_options(selected_guild_id),
                "selected_guild_id": selected_guild_id,
            }
        )

    @app.route("/api/actions")
    def get_actions() -> Any:
        """Return paginated recent actions for the web soundboard."""
        query = _build_paginated_query(filter_names=("action", "user", "sound"))
        include_filters = request.args.get("include_filters", "1").strip().lower() not in {
            "0",
            "false",
            "no",
        }
        return jsonify(
            _get_web_content_service().get_actions(
                query,
                include_filters=include_filters,
                current_user=_get_current_discord_user(),
            )
        )

    @app.route("/api/favorites")
    def get_favorites() -> Any:
        """Return paginated favorite sounds for the web soundboard."""
        query = _build_paginated_query(filter_names=("sound", "user"))
        return jsonify(
            _get_web_content_service().get_favorites(
                query,
                current_user=_get_current_discord_user(),
            )
        )

    @app.route("/api/all_sounds")
    def get_all_sounds() -> Any:
        """Return paginated sound inventory for the web soundboard."""
        query = _build_paginated_query(filter_names=("sound", "date", "list"))
        return jsonify(
            _get_web_content_service().get_all_sounds(
                query,
                current_user=_get_current_discord_user(),
            )
        )

    @app.route("/api/play_sound", methods=["POST"])
    @_require_discord_login_api
    def request_play_sound() -> Any:
        """Send a sound playback request from the authenticated web user."""
        data = request.get_json(silent=True) or {}
        _remember_selected_guild_id(data.get("guild_id"))
        current_user = _get_current_discord_user()
        if current_user is None:
            return jsonify({"error": "Discord login required"}), 401

        try:
            _get_web_playback_service().queue_request(data, current_user)
            return jsonify({"message": "Playback request sent"}), 200
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except sqlite3.Error:
            logger.exception("Database error queuing playback request")
            return jsonify({"error": "Database error"}), 500
        except Exception:
            logger.exception("Unexpected error queuing playback request")
            return jsonify({"error": "Internal server error"}), 500

    @app.route("/api/web_control", methods=["POST"])
    @_require_discord_login_api
    def request_web_control() -> Any:
        """Send a bot control request from the authenticated web user."""
        data = request.get_json(silent=True) or {}
        _remember_selected_guild_id(data.get("guild_id"))
        current_user = _get_current_discord_user()
        if current_user is None:
            return jsonify({"error": "Discord login required"}), 401

        try:
            _get_web_playback_service().queue_control_request(data, current_user)
            return jsonify({"message": "Control request sent"}), 200
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except sqlite3.Error:
            logger.exception("Database error queuing web control request")
            return jsonify({"error": "Database error"}), 500
        except Exception:
            logger.exception("Unexpected error queuing web control request")
            return jsonify({"error": "Internal server error"}), 500

    @app.route("/api/web_control_state")
    @_require_discord_login_api
    def get_web_control_state() -> Any:
        """Return current bot control state for the authenticated web user."""
        _remember_selected_guild_id(request.args.get("guild_id"))
        try:
            return jsonify(_get_web_playback_service().get_control_state(request.args)), 200
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except sqlite3.Error:
            logger.exception("Database error loading web control state")
            return jsonify({"error": "Database error"}), 500
        except Exception:
            logger.exception("Unexpected error loading web control state")
            return jsonify({"error": "Internal server error"}), 500

    @app.route("/api/control_room/status")
    def get_control_room_status() -> Any:
        """Return live bot status for the web control room."""
        _remember_selected_guild_id(request.args.get("guild_id"))
        try:
            return jsonify(_get_web_control_room_service().get_status(request.args)), 200
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except sqlite3.Error:
            logger.exception("Database error loading control room status")
            return jsonify({"error": "Database error"}), 500
        except Exception:
            logger.exception("Unexpected error loading control room status")
            return jsonify({"error": "Internal server error"}), 500

    @app.route("/api/upload_sound", methods=["POST"])
    @_require_discord_login_api
    def upload_sound() -> Any:
        """Upload an MP3 from the authenticated web user."""
        current_user = _get_current_discord_user()
        if current_user is None:
            return jsonify({"error": "Discord login required"}), 401

        uploaded_file = request.files.get("sound_file")
        source_url = request.form.get("source_url", "").strip()
        if (uploaded_file is None or not uploaded_file.filename) and not source_url:
            return jsonify({"error": "Please provide a URL or upload an MP3 file."}), 400

        selected_guild_id = _get_selected_guild_id(request.form)
        _remember_selected_guild_id(selected_guild_id)
        try:
            payload = _get_web_upload_service().save_upload(
                uploaded_file=uploaded_file,
                current_user=current_user,
                guild_id=selected_guild_id,
                custom_name=request.form.get("custom_name"),
                source_url=source_url,
                time_limit=_parse_optional_positive_int(request.form.get("time_limit")),
            )
            return jsonify({"message": "Upload approved", **payload}), 200
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except sqlite3.Error:
            logger.exception("Database error saving web upload")
            return jsonify({"error": "Database error"}), 500
        except Exception:
            logger.exception("Unexpected error saving web upload")
            return jsonify({"error": "Internal server error"}), 500

    @app.route("/api/uploads")
    @_require_discord_login_api
    @_require_web_admin_api
    def get_uploads() -> Any:
        """Return admin-only upload inbox records."""
        selected_guild_id = _get_selected_guild_id(request.args)
        _remember_selected_guild_id(selected_guild_id)
        return jsonify(
            _get_web_upload_service().get_inbox(
                limit=_parse_positive_int_arg("limit", 50),
                guild_id=selected_guild_id,
            )
        )

    @app.route("/api/uploads/<int:upload_id>/moderation", methods=["POST"])
    @_require_discord_login_api
    @_require_web_admin_api
    def moderate_upload(upload_id: int) -> Any:
        """Apply an admin-only upload moderation decision."""
        current_user = _get_current_discord_user()
        if current_user is None:
            return jsonify({"error": "Discord login required"}), 401

        data = request.get_json(silent=True) or {}
        status = str(data.get("status") or "").strip().lower()
        try:
            return jsonify(
                _get_web_upload_service().moderate_upload(
                    upload_id,
                    status=status,
                    moderator=current_user,
                )
            ), 200
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except sqlite3.Error:
            logger.exception("Database error moderating web upload")
            return jsonify({"error": "Database error"}), 500
        except Exception:
            logger.exception("Unexpected error moderating web upload")
            return jsonify({"error": "Internal server error"}), 500

    @app.route("/analytics")
    def analytics() -> str:
        """Render the analytics dashboard page."""
        return render_template("analytics.html")

    @app.route("/api/analytics/summary")
    def get_analytics_summary() -> Any:
        """Return summary statistics for the analytics dashboard."""
        return jsonify(_get_web_analytics_service().get_summary(_parse_int_arg("days", 0)))

    @app.route("/api/analytics/top_users")
    def get_analytics_top_users() -> Any:
        """Return top users for the analytics dashboard."""
        query = AnalyticsQuery(
            days=_parse_int_arg("days", 7),
            limit=_parse_int_arg("limit", 10),
        )
        return jsonify(
            _get_web_analytics_service().get_top_users(
                query,
                current_user=_get_current_discord_user(),
            )
        )

    @app.route("/api/analytics/top_sounds")
    def get_analytics_top_sounds() -> Any:
        """Return top sounds for the analytics dashboard."""
        query = AnalyticsQuery(
            days=_parse_int_arg("days", 7),
            limit=_parse_int_arg("limit", 10),
        )
        return jsonify(
            _get_web_analytics_service().get_top_sounds(
                query,
                current_user=_get_current_discord_user(),
            )
        )

    @app.route("/api/analytics/activity_heatmap")
    def get_analytics_heatmap() -> Any:
        """Return heatmap activity buckets for the analytics dashboard."""
        return jsonify(
            _get_web_analytics_service().get_activity_heatmap(
                _parse_int_arg("days", 30)
            )
        )

    @app.route("/api/analytics/activity_timeline")
    def get_analytics_timeline() -> Any:
        """Return timeline activity buckets for the analytics dashboard."""
        return jsonify(
            _get_web_analytics_service().get_activity_timeline(
                _parse_int_arg("days", 30)
            )
        )

    @app.route("/api/analytics/recent_activity")
    def get_analytics_recent() -> Any:
        """Return recent activity rows for the analytics dashboard."""
        return jsonify(
            _get_web_analytics_service().get_recent_activity(
                _parse_int_arg("limit", 20),
                current_user=_get_current_discord_user(),
            )
        )


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


def _get_web_control_room_service() -> WebControlRoomService:
    """Build a control-room service for the current request config."""
    db_path = current_app.config["DATABASE_PATH"]
    return WebControlRoomService(
        repository=WebControlRoomRepository(db_path=db_path, use_shared=False),
        db_path=db_path,
    )


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
