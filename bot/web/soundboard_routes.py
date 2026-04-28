"""Soundboard page and sound inventory API routes."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from flask import Flask, jsonify, render_template, request

from bot.web.route_helpers import (
    _build_initial_soundboard_data,
    _build_paginated_query,
    _build_tts_profile_options,
    _current_web_user_is_admin,
    _get_current_discord_user,
    _get_selected_guild_id,
    _get_web_content_service,
    _get_web_guild_service,
    _get_web_sound_options_service,
    _parse_include_filters_arg,
    _remember_selected_guild_id,
    _require_discord_login_api,
)

logger = logging.getLogger(__name__)


def register_soundboard_routes(app: Flask) -> None:
    """Register soundboard page, data, and sound-option routes."""

    @app.route("/")
    def index() -> str:
        """Render the soundboard page."""
        selected_guild_id = _get_selected_guild_id(request.args)
        return render_template(
            "index.html",
            initial_soundboard_data=_build_initial_soundboard_data(selected_guild_id),
            guild_options=_get_web_guild_service().get_guild_options(selected_guild_id),
            selected_guild_id=selected_guild_id,
            tts_profile_options=_build_tts_profile_options(),
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
        return jsonify(
            _get_web_content_service().get_actions(
                query,
                include_filters=_parse_include_filters_arg(),
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
                include_filters=_parse_include_filters_arg(),
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
                include_filters=_parse_include_filters_arg(),
                current_user=_get_current_discord_user(),
            )
        )

    @app.route("/api/sounds/<int:sound_id>/options")
    @_require_discord_login_api
    def get_sound_options(sound_id: int) -> Any:
        """Return long-press options for one sound."""
        selected_guild_id = _get_selected_guild_id(request.args)
        _remember_selected_guild_id(selected_guild_id)
        try:
            return jsonify(
                _get_web_sound_options_service().get_options(
                    sound_id,
                    guild_id=selected_guild_id,
                    current_user=_get_current_discord_user(),
                )
            ), 200
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except sqlite3.Error:
            logger.exception("Database error loading sound options")
            return jsonify({"error": "Database error"}), 500
        except Exception:
            logger.exception("Unexpected error loading sound options")
            return jsonify({"error": "Internal server error"}), 500

    @app.route("/api/sounds/<int:sound_id>/rename", methods=["POST"])
    @_require_discord_login_api
    def rename_sound(sound_id: int) -> Any:
        """Rename a sound from the web options modal."""
        data = request.get_json(silent=True) or {}
        _remember_selected_guild_id(data.get("guild_id"))
        current_user = _get_current_discord_user()
        if current_user is None:
            return jsonify({"error": "Discord login required"}), 401
        try:
            return jsonify(
                _get_web_sound_options_service().rename_sound(
                    sound_id,
                    str(data.get("new_name") or ""),
                    current_user,
                    guild_id=_get_selected_guild_id(data),
                )
            ), 200
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except sqlite3.Error:
            logger.exception("Database error renaming sound")
            return jsonify({"error": "Database error"}), 500
        except Exception:
            logger.exception("Unexpected error renaming sound")
            return jsonify({"error": "Internal server error"}), 500

    @app.route("/api/sounds/<int:sound_id>/favorite", methods=["POST"])
    @_require_discord_login_api
    def toggle_sound_favorite(sound_id: int) -> Any:
        """Toggle favorite state from the web options modal."""
        data = request.get_json(silent=True) or {}
        _remember_selected_guild_id(data.get("guild_id"))
        current_user = _get_current_discord_user()
        if current_user is None:
            return jsonify({"error": "Discord login required"}), 401
        try:
            return jsonify(
                _get_web_sound_options_service().toggle_favorite(
                    sound_id,
                    current_user,
                    guild_id=_get_selected_guild_id(data),
                )
            ), 200
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except sqlite3.Error:
            logger.exception("Database error toggling favorite")
            return jsonify({"error": "Database error"}), 500
        except Exception:
            logger.exception("Unexpected error toggling favorite")
            return jsonify({"error": "Internal server error"}), 500

    @app.route("/api/sounds/<int:sound_id>/slap", methods=["POST"])
    @_require_discord_login_api
    def toggle_sound_slap(sound_id: int) -> Any:
        """Toggle slap state from the web sound row context menu."""
        data = request.get_json(silent=True) or {}
        _remember_selected_guild_id(data.get("guild_id"))
        current_user = _get_current_discord_user()
        if current_user is None:
            return jsonify({"error": "Discord login required"}), 401
        try:
            return jsonify(
                _get_web_sound_options_service().toggle_slap(
                    sound_id,
                    current_user,
                    guild_id=_get_selected_guild_id(data),
                    current_user_is_admin=_current_web_user_is_admin(),
                )
            ), 200
        except PermissionError as exc:
            return jsonify({"error": str(exc)}), 403
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except sqlite3.Error:
            logger.exception("Database error toggling slap")
            return jsonify({"error": "Database error"}), 500
        except Exception:
            logger.exception("Unexpected error toggling slap")
            return jsonify({"error": "Internal server error"}), 500

    @app.route("/api/sounds/<int:sound_id>/lists", methods=["POST"])
    @_require_discord_login_api
    def add_sound_to_list(sound_id: int) -> Any:
        """Add a sound to a list from the web options modal."""
        data = request.get_json(silent=True) or {}
        _remember_selected_guild_id(data.get("guild_id"))
        current_user = _get_current_discord_user()
        if current_user is None:
            return jsonify({"error": "Discord login required"}), 401
        try:
            list_id = int(data.get("list_id"))
            return jsonify(
                _get_web_sound_options_service().add_to_list(
                    sound_id,
                    list_id,
                    current_user,
                    guild_id=_get_selected_guild_id(data),
                )
            ), 200
        except (TypeError, ValueError) as exc:
            return jsonify({"error": str(exc) or "Choose a list."}), 400
        except sqlite3.Error:
            logger.exception("Database error adding sound to list")
            return jsonify({"error": "Database error"}), 500
        except Exception:
            logger.exception("Unexpected error adding sound to list")
            return jsonify({"error": "Internal server error"}), 500

    @app.route("/api/sounds/<int:sound_id>/events", methods=["POST"])
    @_require_discord_login_api
    def toggle_sound_event(sound_id: int) -> Any:
        """Toggle a join/leave event sound from the web event modal."""
        data = request.get_json(silent=True) or {}
        _remember_selected_guild_id(data.get("guild_id"))
        current_user = _get_current_discord_user()
        if current_user is None:
            return jsonify({"error": "Discord login required"}), 401
        try:
            return jsonify(
                _get_web_sound_options_service().toggle_user_event(
                    sound_id,
                    str(data.get("target_user") or ""),
                    str(data.get("event") or ""),
                    current_user,
                    guild_id=_get_selected_guild_id(data),
                    current_user_is_admin=_current_web_user_is_admin(),
                )
            ), 200
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except sqlite3.Error:
            logger.exception("Database error toggling event sound")
            return jsonify({"error": "Database error"}), 500
        except Exception:
            logger.exception("Unexpected error toggling event sound")
            return jsonify({"error": "Internal server error"}), 500
