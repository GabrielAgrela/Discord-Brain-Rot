"""
Flask app factory for the optional web UI.
"""

from __future__ import annotations

import os
from pathlib import Path

from flask import Flask

from bot.services.web_auth import WebAuthService
from bot.services.text_censor import TextCensorService
from bot.web.routes import register_web_routes


def create_app() -> Flask:
    """
    Build the Flask web application.

    Returns:
        Configured Flask application.
    """
    project_root = Path(__file__).resolve().parents[2]
    app = Flask(
        __name__,
        template_folder=str(project_root / "templates"),
    )
    app.config.setdefault("DATABASE_PATH", "Data/database.db")
    app.config["SECRET_KEY"] = app.config.get("SECRET_KEY") or os.getenv(
        "WEB_SESSION_SECRET",
        "discord-brain-rot-web-dev",
    )
    app.config.setdefault("DISCORD_API_BASE_URL", "https://discord.com/api")

    app.extensions["web_auth_service"] = WebAuthService()
    app.extensions["web_text_censor_service"] = TextCensorService()

    register_web_routes(app)
    return app
