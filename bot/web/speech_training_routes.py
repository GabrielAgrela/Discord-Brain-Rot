"""
Speech training dataset labeling routes (admin-only).

Provides the HTML labeling page and JSON API endpoints for browsing,
playing back, labeling, and deleting captured speech clips.
"""

from __future__ import annotations

from typing import Any

from flask import Flask, jsonify, render_template, request, send_file

from bot.web.route_helpers import (
    _current_web_user_is_admin,
    _get_current_discord_user,
    _get_selected_guild_id,
    _get_web_guild_service,
    _get_web_speech_training_service,
    _parse_positive_int_arg,
    _remember_selected_guild_id,
    _require_discord_login_api,
    _require_web_admin_api,
)


def register_speech_training_routes(app: Flask) -> None:
    """Register speech training dataset routes."""

    @app.route("/speech-training")
    def speech_training() -> Any:
        """Render the speech training labeling page (admin-only)."""
        current_user = _get_current_discord_user()
        if current_user is None:
            from flask import url_for

            return _redirect_to_login("speech_training")

        if not _current_web_user_is_admin():
            return (
                render_template(
                    "error.html",
                    error_title="Admin Access Required",
                    error_message="Only bot admins can access the speech training dataset.",
                ),
                403,
            )

        selected_guild_id = _get_selected_guild_id(request.args)
        _remember_selected_guild_id(selected_guild_id)

        guild_service = _get_web_guild_service()
        guild_options = guild_service.get_guild_options(
            selected_guild_id=selected_guild_id
        )

        return render_template(
            "speech_training.html",
            guild_options=guild_options,
            discord_user=current_user,
            display_name=current_user.global_name or current_user.username,
            web_user_is_admin=_current_web_user_is_admin(),
            active_page="dataset",
        )

    # ------------------------------------------------------------------
    # API: Users
    # ------------------------------------------------------------------

    @app.route("/api/speech_training/users")
    @_require_discord_login_api
    @_require_web_admin_api
    def api_speech_training_users() -> Any:
        """Return per-user aggregation."""
        svc = _get_web_speech_training_service()
        guild_id = request.args.get("guild_id", "").strip() or None
        return jsonify(svc.get_users(guild_id=guild_id))

    # ------------------------------------------------------------------
    # API: Storage summary
    # ------------------------------------------------------------------

    @app.route("/api/speech_training/storage")
    @_require_discord_login_api
    @_require_web_admin_api
    def api_speech_training_storage() -> Any:
        """Return total MP3 storage used and clip count."""
        svc = _get_web_speech_training_service()
        guild_id = request.args.get("guild_id", "").strip() or None
        return jsonify(svc.get_storage_summary(guild_id=guild_id))

    # ------------------------------------------------------------------
    # API: Clips
    # ------------------------------------------------------------------

    @app.route("/api/speech_training/clips")
    @_require_discord_login_api
    @_require_web_admin_api
    def api_speech_training_clips() -> Any:
        """Return paginated clip list with optional sort."""
        svc = _get_web_speech_training_service()
        guild_id = request.args.get("guild_id", "").strip() or None
        user_id = request.args.get("user_id", "").strip() or None
        label = request.args.get("label", "").strip() or None
        search = request.args.get("search", "").strip()
        sort = request.args.get("sort", "newest").strip()
        page = _parse_positive_int_arg("page", 1)
        per_page = _parse_positive_int_arg("per_page", 20)
        return jsonify(
            svc.get_clips(
                guild_id=guild_id,
                user_id=user_id,
                label=label,
                page=page,
                per_page=per_page,
                search=search,
                sort=sort,
            )
        )

    # ------------------------------------------------------------------
    # API: Single clip audio
    # ------------------------------------------------------------------

    @app.route("/api/speech_training/clips/<int:clip_id>/audio")
    @_require_discord_login_api
    @_require_web_admin_api
    def api_speech_training_clip_audio(clip_id: int) -> Any:
        """Stream an MP3 clip for playback."""
        svc = _get_web_speech_training_service()
        clip = svc.get_clip(clip_id)
        if clip is None:
            return jsonify({"error": "Clip not found"}), 404
        path = svc.resolve_audio_path(clip)
        if path is None:
            return jsonify({"error": "Audio file not found"}), 404
        return send_file(str(path), mimetype="audio/mpeg", conditional=True)

    # ------------------------------------------------------------------
    # API: Update label
    # ------------------------------------------------------------------

    @app.route("/api/speech_training/clips/<int:clip_id>/label", methods=["POST"])
    @_require_discord_login_api
    @_require_web_admin_api
    def api_speech_training_clip_label(clip_id: int) -> Any:
        """Update the label, transcript, and notes for a clip."""
        svc = _get_web_speech_training_service()
        data = request.get_json(silent=True) or {}
        label = (data.get("label") or "").strip() or None
        transcript = (data.get("transcript") or "").strip() or None
        notes = (data.get("notes") or "").strip() or None

        current_user = _get_current_discord_user()

        success, error = svc.update_label(
            clip_id=clip_id,
            label=label,
            transcript=transcript,
            notes=notes,
            reviewer_user_id=str(current_user.id) if current_user else "",
            reviewer_username=str(current_user) if current_user else "",
        )
        if success:
            return jsonify({"status": "ok"})
        return jsonify({"error": error}), 400

    # ------------------------------------------------------------------
    # API: Delete single clip
    # ------------------------------------------------------------------

    @app.route("/api/speech_training/clips/<int:clip_id>", methods=["DELETE"])
    @_require_discord_login_api
    @_require_web_admin_api
    def api_speech_training_clip_delete(clip_id: int) -> Any:
        """Delete a single clip and its audio file."""
        svc = _get_web_speech_training_service()
        current_user = _get_current_discord_user()

        success, error = svc.delete_clip(
            clip_id=clip_id,
            reviewer_user_id=str(current_user.id) if current_user else "",
            reviewer_username=str(current_user) if current_user else "",
        )
        if success:
            return jsonify({"status": "ok"})
        return jsonify({"error": error}), 404

    # ------------------------------------------------------------------
    # API: Bulk operations
    # ------------------------------------------------------------------

    @app.route("/api/speech_training/clips/bulk", methods=["POST"])
    @_require_discord_login_api
    @_require_web_admin_api
    def api_speech_training_clips_bulk() -> Any:
        """Bulk label or delete clips.

        Request body::

            {"action": "label", "ids": [1,2,3], "label": "chapada"}
            {"action": "delete", "ids": [1,2,3]}
        """
        svc = _get_web_speech_training_service()
        data = request.get_json(silent=True) or {}
        action = data.get("action", "").strip()
        raw_ids = data.get("ids", [])
        current_user = _get_current_discord_user()

        # Validate ids is a list of ints
        if not isinstance(raw_ids, list) or not raw_ids:
            return jsonify({"error": "ids must be a non-empty list"}), 400
        clip_ids = []
        for v in raw_ids:
            try:
                clip_ids.append(int(v))
            except (TypeError, ValueError):
                return jsonify({"error": f"Invalid id value: {v}"}), 400

        if action == "label":
            label = (data.get("label") or "").strip() or None
            success, error = svc.bulk_label(
                clip_ids=clip_ids,
                label=label,
                reviewer_user_id=str(current_user.id) if current_user else "",
                reviewer_username=str(current_user) if current_user else "",
            )
            if success:
                return jsonify({"status": "ok"})
            return jsonify({"error": error}), 400

        elif action == "delete":
            success, error, count = svc.bulk_delete(
                clip_ids=clip_ids,
                reviewer_user_id=str(current_user.id) if current_user else "",
                reviewer_username=str(current_user) if current_user else "",
            )
            if success:
                return jsonify({"status": "ok", "deleted": count})
            return jsonify({"error": error}), 400

        else:
            return jsonify({"error": "Unknown action. Use 'label' or 'delete'."}), 400


def _redirect_to_login(route_name: str) -> Any:
    """Redirect to Discord login preserving the next route."""
    from flask import redirect, url_for

    return redirect(url_for("login", next=url_for(route_name)))
