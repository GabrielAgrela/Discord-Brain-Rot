"""
Tests for ``bot/web/app.py`` — Flask app factory and worker startup logic.
"""

import os
from unittest.mock import patch, MagicMock

import pytest
from flask import Flask


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def app():
    """Minimal Flask app with extensions dict for worker guard tests."""
    app = Flask(__name__)
    app.extensions["honker_upload_workers_started"] = False
    return app


# ============================================================================
# _get_web_upload_worker_count
# ============================================================================

class TestGetWebUploadWorkerCount:
    """Tests for the legacy ``WEB_UPLOAD_WORKERS`` env var parser."""

    def test_default(self):
        from bot.web.app import _get_web_upload_worker_count
        with patch.dict(os.environ, {}, clear=True):
            assert _get_web_upload_worker_count() == 2

    def test_custom_value(self):
        from bot.web.app import _get_web_upload_worker_count
        with patch.dict(os.environ, {"WEB_UPLOAD_WORKERS": "3"}, clear=True):
            assert _get_web_upload_worker_count() == 3

    def test_clamped_min(self):
        from bot.web.app import _get_web_upload_worker_count
        with patch.dict(os.environ, {"WEB_UPLOAD_WORKERS": "0"}, clear=True):
            assert _get_web_upload_worker_count() == 1

    def test_clamped_max(self):
        from bot.web.app import _get_web_upload_worker_count
        with patch.dict(os.environ, {"WEB_UPLOAD_WORKERS": "99"}, clear=True):
            assert _get_web_upload_worker_count() == 8

    def test_invalid_fallback(self):
        from bot.web.app import _get_web_upload_worker_count
        with patch.dict(os.environ, {"WEB_UPLOAD_WORKERS": "abc"}, clear=True):
            assert _get_web_upload_worker_count() == 2


# ============================================================================
# _get_honker_upload_worker_count
# ============================================================================

class TestGetHonkerUploadWorkerCount:
    """Tests for the Honker-specific ``HONKER_UPLOAD_WORKERS`` env var."""

    def test_default(self):
        from bot.web.app import _get_honker_upload_worker_count
        with patch.dict(os.environ, {}, clear=True):
            assert _get_honker_upload_worker_count() == 1

    def test_custom_value(self):
        from bot.web.app import _get_honker_upload_worker_count
        with patch.dict(os.environ, {"HONKER_UPLOAD_WORKERS": "2"}, clear=True):
            assert _get_honker_upload_worker_count() == 2

    def test_clamped_min(self):
        from bot.web.app import _get_honker_upload_worker_count
        with patch.dict(os.environ, {"HONKER_UPLOAD_WORKERS": "0"}, clear=True):
            assert _get_honker_upload_worker_count() == 1

    def test_clamped_max(self):
        from bot.web.app import _get_honker_upload_worker_count
        with patch.dict(os.environ, {"HONKER_UPLOAD_WORKERS": "9"}, clear=True):
            assert _get_honker_upload_worker_count() == 4

    def test_invalid_fallback(self):
        from bot.web.app import _get_honker_upload_worker_count
        with patch.dict(os.environ, {"HONKER_UPLOAD_WORKERS": "xyz"}, clear=True):
            assert _get_honker_upload_worker_count() == 1


# ============================================================================
# _should_start_honker_upload_workers
# ============================================================================

class TestShouldStartHonkerUploadWorkers:
    """Idempotency guard and reloader-parent detection."""

    # -- idempotency ---------------------------------------------------------

    def test_idempotency_returns_true_on_first_call(self, app):
        from bot.web.app import _should_start_honker_upload_workers
        assert _should_start_honker_upload_workers(app) is True

    def test_idempotency_returns_false_on_second_call(self, app):
        from bot.web.app import _should_start_honker_upload_workers
        assert _should_start_honker_upload_workers(app) is True
        assert _should_start_honker_upload_workers(app) is False

    # -- reloader child (is_running_from_reloader=True) ----------------------

    @patch("bot.web.app.is_running_from_reloader", return_value=True)
    def test_reloader_child_starts_workers(self, mock_reloader, app):
        from bot.web.app import _should_start_honker_upload_workers
        assert _should_start_honker_upload_workers(app) is True

    # -- reloader parent (is_running_from_reloader=False, debug env active) --

    @patch("bot.web.app.is_running_from_reloader", return_value=False)
    def test_reloader_parent_skips_workers_with_flask_env(self, mock_reloader, app):
        from bot.web.app import _should_start_honker_upload_workers
        with patch.dict(os.environ, {"FLASK_ENV": "development"}, clear=True):
            assert _should_start_honker_upload_workers(app) is False

    @patch("bot.web.app.is_running_from_reloader", return_value=False)
    def test_reloader_parent_skips_workers_with_flask_debug(self, mock_reloader, app):
        from bot.web.app import _should_start_honker_upload_workers
        with patch.dict(os.environ, {"FLASK_DEBUG": "1"}, clear=True):
            assert _should_start_honker_upload_workers(app) is False

    # -- production (is_running_from_reloader=False, no debug env) -----------

    @patch("bot.web.app.is_running_from_reloader", return_value=False)
    def test_production_starts_workers(self, mock_reloader, app):
        from bot.web.app import _should_start_honker_upload_workers
        with patch.dict(os.environ, {}, clear=True):
            # No FLASK_ENV/FLASK_DEBUG → production → start workers
            assert _should_start_honker_upload_workers(app) is True

    # -- idempotency across reloader scenarios -------------------------------

    @patch("bot.web.app.is_running_from_reloader", return_value=True)
    def test_idempotency_after_reloader_child(self, mock_reloader, app):
        from bot.web.app import _should_start_honker_upload_workers
        assert _should_start_honker_upload_workers(app) is True
        assert _should_start_honker_upload_workers(app) is False


# ============================================================================
# PRAGMA busy_timeout in BaseRepository
# ============================================================================

class TestBaseRepositoryBusyTimeout:
    """Verify that newly created connections have an explicit busy timeout."""

    def test_connection_sets_busy_timeout(self):
        """Non-shared connection should set PRAGMA busy_timeout."""
        # Use a concrete subclass to avoid abstract-class instantiation.
        from bot.repositories.web_upload_job import WebUploadJobRepository

        repo = WebUploadJobRepository.__new__(WebUploadJobRepository)
        # Skip __init__ (which calls ensure_schema on a non-existent db).
        repo._db_path = ":memory:"
        repo._use_shared = False

        conn = repo._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("PRAGMA busy_timeout")
            row = cursor.fetchone()
            assert row is not None
            # SQLite returns the timeout in milliseconds
            assert int(row[0]) == 5000
        finally:
            conn.close()
