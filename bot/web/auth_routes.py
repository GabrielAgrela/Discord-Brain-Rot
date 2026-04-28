"""Authentication routes for the Flask web UI."""

from __future__ import annotations

import os
from typing import Any

from flask import Flask, current_app, redirect, request, session, url_for

from bot.services.web_auth import DiscordOAuthError
from bot.web.route_helpers import (
    _build_discord_redirect_uri,
    _current_web_user_is_admin,
    _get_auth_service,
    _get_current_discord_user,
)


def register_auth_routes(app: Flask) -> None:
    """Register Discord OAuth and template auth-context routes."""

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
