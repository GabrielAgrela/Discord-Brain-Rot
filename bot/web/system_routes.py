"""
Flask routes for the /api/system_monitor/status endpoint.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Flask, jsonify, request

from bot.services.web_system_monitor import WebSystemMonitorService
from bot.web.route_helpers import _get_web_system_monitor_service

logger = logging.getLogger(__name__)


def register_system_routes(app: Flask) -> None:
    """Register system-monitor API routes on the Flask app."""

    @app.route("/api/system_monitor/status")
    def system_monitor_status() -> Any:
        """Return CPU, RAM, and top processes as JSON."""
        limit_raw = request.args.get("limit", "4")
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            limit = 4
        limit = max(1, min(8, limit))

        try:
            service: WebSystemMonitorService = _get_web_system_monitor_service()
            payload = service.get_snapshot(top_limit=limit)
            response = jsonify(payload)
            # Allow browser to serve cached response for 1 s to reduce
            # redundant requests from aggressive polling intervals.
            response.headers["Cache-Control"] = "private, max-age=1"
            return response, 200
        except Exception:
            logger.exception("System monitor route error")
            return jsonify(
                {
                    "available": False,
                    "error": "System monitor unavailable",
                    "total_cpu_percent": None,
                    "ram_total_bytes": 0,
                    "ram_available_bytes": 0,
                    "ram_used_bytes": 0,
                    "ram_percent": 0.0,
                    "cpu_warming": True,
                    "sample_interval_seconds": 0.0,
                    "updated_at_unix": 0.0,
                    "top_processes": [],
                    "cpu_temperature_celsius": None,
                    "cpu_fan_rpm": None,
                }
            ), 500
