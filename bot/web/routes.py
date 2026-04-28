"""Route registration for the optional Flask web UI."""

from __future__ import annotations

from flask import Flask

from bot.web.analytics_routes import register_analytics_routes
from bot.web.auth_routes import register_auth_routes
from bot.web.playback_routes import register_playback_routes
from bot.web.soundboard_routes import register_soundboard_routes
from bot.web.upload_routes import register_upload_routes


def register_web_routes(app: Flask) -> None:
    """
    Register all web routes and template helpers on the Flask app.

    Args:
        app: Flask application to configure.
    """
    register_auth_routes(app)
    register_soundboard_routes(app)
    register_playback_routes(app)
    register_upload_routes(app)
    register_analytics_routes(app)
