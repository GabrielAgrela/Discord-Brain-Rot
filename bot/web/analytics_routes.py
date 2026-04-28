"""Analytics page and API routes."""

from __future__ import annotations

from typing import Any

from flask import Flask, jsonify, render_template

from bot.models.web import AnalyticsQuery
from bot.web.route_helpers import (
    _get_current_discord_user,
    _get_web_analytics_service,
    _parse_int_arg,
)


def register_analytics_routes(app: Flask) -> None:
    """Register analytics dashboard and API routes."""

    @app.route("/analytics")
    def analytics() -> str:
        """Render the analytics dashboard page."""
        return render_template("analytics.html")

    @app.route("/api/analytics/summary")
    def get_analytics_summary() -> Any:
        """Return summary statistics for the analytics dashboard."""
        return jsonify(_get_web_analytics_service().get_summary(_parse_int_arg("days", 0)))

    @app.route("/api/analytics/top_users")
    def get_analytics_top_users() -> Any:
        """Return top users for the analytics dashboard."""
        query = AnalyticsQuery(
            days=_parse_int_arg("days", 7),
            limit=_parse_int_arg("limit", 10),
        )
        return jsonify(
            _get_web_analytics_service().get_top_users(
                query,
                current_user=_get_current_discord_user(),
            )
        )

    @app.route("/api/analytics/top_sounds")
    def get_analytics_top_sounds() -> Any:
        """Return top sounds for the analytics dashboard."""
        query = AnalyticsQuery(
            days=_parse_int_arg("days", 7),
            limit=_parse_int_arg("limit", 10),
        )
        return jsonify(
            _get_web_analytics_service().get_top_sounds(
                query,
                current_user=_get_current_discord_user(),
            )
        )

    @app.route("/api/analytics/activity_heatmap")
    def get_analytics_heatmap() -> Any:
        """Return heatmap activity buckets for the analytics dashboard."""
        return jsonify(
            _get_web_analytics_service().get_activity_heatmap(
                _parse_int_arg("days", 30)
            )
        )

    @app.route("/api/analytics/activity_timeline")
    def get_analytics_timeline() -> Any:
        """Return timeline activity buckets for the analytics dashboard."""
        return jsonify(
            _get_web_analytics_service().get_activity_timeline(
                _parse_int_arg("days", 30)
            )
        )

    @app.route("/api/analytics/recent_activity")
    def get_analytics_recent() -> Any:
        """Return recent activity rows for the analytics dashboard."""
        return jsonify(
            _get_web_analytics_service().get_recent_activity(
                _parse_int_arg("limit", 20),
                current_user=_get_current_discord_user(),
            )
        )
