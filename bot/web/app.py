"""
Flask app factory for the optional web UI.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import os
from pathlib import Path

from flask import Flask

from bot.services.web_auth import WebAuthService
from bot.services.text_censor import TextCensorService
from bot.services.web_tts_enhancer import WebTtsEnhancerService
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
    app.config.setdefault("SOUNDS_DIR", str(project_root / "Sounds"))
    app.config["SECRET_KEY"] = app.config.get("SECRET_KEY") or os.getenv(
        "WEB_SESSION_SECRET",
        "discord-brain-rot-web-dev",
    )
    app.config.setdefault("DISCORD_API_BASE_URL", "https://discord.com/api")
    app.config["SESSION_PERMANENT"] = app.config.get("SESSION_PERMANENT", True)
    app.config["SESSION_COOKIE_HTTPONLY"] = app.config.get(
        "SESSION_COOKIE_HTTPONLY",
        True,
    )
    app.config["SESSION_COOKIE_SAMESITE"] = (
        app.config.get("SESSION_COOKIE_SAMESITE") or "Lax"
    )
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(
        days=_get_web_session_lifetime_days()
    )

    if os.getenv("FLASK_ENV", "").strip().lower() == "development":
        app.config["SESSION_COOKIE_SECURE"] = app.config.get(
            "SESSION_COOKIE_SECURE",
            False,
        )
    else:
        app.config["SESSION_COOKIE_SECURE"] = app.config.get(
            "SESSION_COOKIE_SECURE",
            True,
        )

    app.extensions["web_auth_service"] = WebAuthService()
    app.extensions["web_text_censor_service"] = TextCensorService()
    app.extensions["web_tts_enhancer_service"] = WebTtsEnhancerService()
    app.extensions["web_upload_executor"] = ThreadPoolExecutor(
        max_workers=_get_web_upload_worker_count()
    )
    app.extensions["web_upload_jobs"] = {}

    register_web_routes(app)
    return app


def _get_web_session_lifetime_days() -> int:
    """
    Return the configured persistent login lifetime in days.

    Returns:
        Positive number of days to keep Discord web sessions signed in.
    """
    raw_value = os.getenv("WEB_SESSION_LIFETIME_DAYS", "30").strip()
    try:
        lifetime_days = int(raw_value)
    except ValueError:
        lifetime_days = 30
    return max(1, lifetime_days)


def _get_web_upload_worker_count() -> int:
    """
    Return the number of background workers for web upload processing.

    Returns:
        Positive worker count for async upload jobs.
    """
    raw_value = os.getenv("WEB_UPLOAD_WORKERS", "2").strip()
    try:
        worker_count = int(raw_value)
    except ValueError:
        worker_count = 2
    return max(1, min(worker_count, 8))
