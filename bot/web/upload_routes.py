"""Web upload and upload moderation API routes."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from flask import Flask, current_app, jsonify, request

from bot.web.route_helpers import (
    _get_current_discord_user,
    _get_selected_guild_id,
    _get_web_upload_service,
    _parse_optional_positive_int,
    _parse_positive_int_arg,
    _queue_web_upload_job,
    _remember_selected_guild_id,
    _require_discord_login_api,
    _require_web_admin_api,
)

logger = logging.getLogger(__name__)


def register_upload_routes(app: Flask) -> None:
    """Register upload queue and moderation routes."""

    @app.route("/api/upload_sound", methods=["POST"])
    @_require_discord_login_api
    def upload_sound() -> Any:
        """Queue an MP3 upload from the authenticated web user."""
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
            job_id = _queue_web_upload_job(
                uploaded_file=uploaded_file,
                current_user=current_user,
                guild_id=selected_guild_id,
                custom_name=request.form.get("custom_name"),
                source_url=source_url,
                time_limit=_parse_optional_positive_int(request.form.get("time_limit")),
            )
            return jsonify(
                {
                    "message": "Upload queued",
                    "job_id": job_id,
                    "status": "processing",
                }
            ), 202
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except sqlite3.Error:
            logger.exception("Database error saving web upload")
            return jsonify({"error": "Database error"}), 500
        except Exception:
            logger.exception("Unexpected error saving web upload")
            return jsonify({"error": "Internal server error"}), 500

    @app.route("/api/upload_sound/<job_id>")
    @_require_discord_login_api
    def get_upload_sound_job(job_id: str) -> Any:
        """Return status for a background web upload job."""
        job = current_app.extensions.get("web_upload_jobs", {}).get(job_id)
        if not job:
            return jsonify({"error": "Upload job not found"}), 404
        return jsonify(dict(job)), 200

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
                page=_parse_positive_int_arg("page", 1),
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
