"""Playback, control-room, and web TTS API routes."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from flask import Flask, jsonify, request

from bot.web.route_helpers import (
    _get_current_discord_user,
    _get_web_control_room_service,
    _get_web_playback_service,
    _get_web_tts_enhancer_service,
    _remember_selected_guild_id,
    _require_discord_login_api,
)

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

    @app.route("/api/control_room/status")
    def get_control_room_status() -> Any:
        """Return live bot status for the web control room."""
        _remember_selected_guild_id(request.args.get("guild_id"))
        try:
            return jsonify(
                _get_web_control_room_service().get_status(
                    request.args,
                    current_user=_get_current_discord_user(),
                )
            ), 200
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except sqlite3.Error:
            logger.exception("Database error loading control room status")
            return jsonify({"error": "Database error"}), 500
        except Exception:
            logger.exception("Unexpected error loading control room status")
            return jsonify({"error": "Internal server error"}), 500
