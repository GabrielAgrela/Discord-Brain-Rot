"""Playback, control-room, and web TTS API routes."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from flask import Flask, jsonify, request

from bot.web.event_routes import publish_soundboard_event
from bot.web.route_helpers import (
    _build_read_cache_key,
    _get_current_discord_user,
    _get_response_cache,
    _get_web_control_room_service,
    _get_web_playback_service,
    _get_web_tts_enhancer_service,
    _get_web_tts_settings_service,
    _remember_selected_guild_id,
    _require_discord_login_api,
    _require_web_admin_api,
)


def _invalidate_playback_caches() -> None:
    """Clear the per-process response cache after a mutating playback action.

    Invalidate so that ``/api/web_control_state`` and other cached read
    endpoints return fresh data on the next SSE-triggered fetch.
    """
    cache = _get_response_cache()
    cache.invalidate()

logger = logging.getLogger(__name__)


def register_playback_routes(app: Flask) -> None:
    """Register web playback, bot control, and TTS routes."""

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
            event_data: dict = {"guild_id": data.get("guild_id")}
            if data.get("play_action"):
                event_data["play_action"] = data.get("play_action")
            publish_soundboard_event("playback_queued", event_data)
            _invalidate_playback_caches()
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
            publish_soundboard_event(
                "playback_queued",
                {"guild_id": data.get("guild_id"), "action": data.get("action")},
            )
            _invalidate_playback_caches()
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
        cache = _get_response_cache()
        key = _build_read_cache_key("/api/web_control_state", visibility="auth")
        try:
            payload = cache.get_or_set(
                key,
                ttl=1.0,
                producer=lambda: _get_web_playback_service().get_control_state(
                    request.args
                ),
            )
            response = jsonify(payload)
            response.headers["Cache-Control"] = "private, max-age=1"
            return response, 200
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except sqlite3.Error:
            logger.exception("Database error loading web control state")
            return jsonify({"error": "Database error"}), 500
        except Exception:
            logger.exception("Unexpected error loading web control state")
            return jsonify({"error": "Internal server error"}), 500

    @app.route("/api/tts/enhance", methods=["POST"])
    @_require_discord_login_api
    def enhance_tts_message() -> Any:
        """Enhance a web TTS message with ElevenLabs audio tags."""
        data = request.get_json(silent=True) or {}
        try:
            enhanced_text = _get_web_tts_enhancer_service().enhance(data.get("message", ""))
            return jsonify({"message": enhanced_text}), 200
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except RuntimeError as exc:
            logger.warning("TTS enhancement failed: %s", exc)
            return jsonify({"error": "TTS enhancement failed"}), 502
        except Exception:
            logger.exception("Unexpected error enhancing TTS message")
            return jsonify({"error": "Internal server error"}), 500

    @app.route("/api/tts/enhancer-settings")
    @_require_discord_login_api
    @_require_web_admin_api
    def get_tts_enhancer_settings() -> Any:
        """Return the current web TTS enhancer LLM model and provider."""

        try:
            settings = _get_web_tts_settings_service().get_enhancer_settings()
            return jsonify(settings), 200
        except sqlite3.Error:
            logger.exception("Database error reading LLM settings")
            return jsonify({"error": "Database error"}), 500
        except Exception:
            logger.exception("Unexpected error reading LLM settings")
            return jsonify({"error": "Internal server error"}), 500

    @app.route("/api/tts/enhancer-settings", methods=["POST"])
    @_require_discord_login_api
    @_require_web_admin_api
    def set_tts_enhancer_settings() -> Any:
        """Set or clear the web TTS enhancer LLM model/provider overrides.

        JSON body:
            ``model`` (str): Model ID to store.  Empty string clears the
            model override, reverting to the env/default.  Omitted/None
            leaves the model unchanged.
            ``provider`` (str): Provider name to store.  Empty string
            clears the provider override, reverting to the env/default.
            Omitted/None leaves the provider unchanged.
        """
        data = request.get_json(silent=True) or {}
        current_user = _get_current_discord_user()
        updated_by = current_user.global_name if current_user else "web-admin"
        settings_service = _get_web_tts_settings_service()

        try:
            # Convert values: present key but empty string → empty string
            # (which the service interprets as "clear that field").
            # Absent key → None (service leaves unchanged).
            model = str(data["model"]).strip() if "model" in data else None
            provider = str(data["provider"]).strip() if "provider" in data else None

            settings = settings_service.set_enhancer_settings(
                model=model,
                provider=provider,
                updated_by=updated_by,
            )
            return jsonify(settings), 200
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except sqlite3.Error:
            logger.exception("Database error writing LLM settings")
            return jsonify({"error": "Database error"}), 500
        except Exception:
            logger.exception("Unexpected error writing LLM settings")
            return jsonify({"error": "Internal server error"}), 500

    @app.route("/api/control_room/status")
    def get_control_room_status() -> Any:
        """Return live bot status for the web control room."""
        _remember_selected_guild_id(request.args.get("guild_id"))
        current_user = _get_current_discord_user()
        visibility = "auth" if current_user is not None else "anon"
        cache = _get_response_cache()
        key = _build_read_cache_key(
            "/api/control_room/status", visibility=visibility
        )
        try:
            payload = cache.get_or_set(
                key,
                ttl=0.9,
                producer=lambda: _get_web_control_room_service().get_status(
                    request.args,
                    current_user=current_user,
                ),
            )
            response = jsonify(payload)
            response.headers["Cache-Control"] = "private, max-age=0, must-revalidate"
            return response, 200
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except sqlite3.Error:
            logger.exception("Database error loading control room status")
            return jsonify({"error": "Database error"}), 500
        except Exception:
            logger.exception("Unexpected error loading control room status")
            return jsonify({"error": "Internal server error"}), 500
