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
                    "cpu_history": [],
                    "ram_history": [],
                    "disk_history": [],
                    "temp_history": [],
                    "process_cpu_history": [],
                    "cpu_temperature_celsius": None,
                    "cpu_fan_rpm": None,
                    "disk_active_percent": None,
                    "disk_read_bytes_per_second": 0.0,
                    "disk_write_bytes_per_second": 0.0,
                }
            ), 500

    @app.route("/api/system_monitor/history")
    def system_monitor_history() -> Any:
        """Return historical time-series data for a metric."""
        metric_type = request.args.get("metric", "cpu")
        range_raw = request.args.get("range", "60")
        metric_key = request.args.get("key", "")

        try:
            range_seconds = int(range_raw)
        except (TypeError, ValueError):
            range_seconds = 60

        valid_ranges = {60, 3600, 86400}
        if range_seconds not in valid_ranges:
            range_seconds = 60

        try:
            service: WebSystemMonitorService = _get_web_system_monitor_service()
            payload = service.get_history(
                metric_type=metric_type,
                range_seconds=range_seconds,
                metric_key=metric_key,
            )
            response = jsonify(payload)
            response.headers["Cache-Control"] = "private, max-age=1"
            return response, 200
        except Exception:
            logger.exception("System monitor history error")
            return jsonify({"samples": [], "range_seconds": range_seconds}), 500

    @app.route("/api/system_monitor/processes_at_time")
    def system_monitor_processes_at_time() -> Any:
        """Return process data at a specific historical timestamp."""
        timestamp_raw = request.args.get("time", "")
        limit_raw = request.args.get("limit", "8")

        try:
            timestamp = int(timestamp_raw)
        except (TypeError, ValueError):
            return jsonify({"processes": [], "timestamp": 0}), 400

        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            limit = 8
        limit = max(1, min(16, limit))

        try:
            service: WebSystemMonitorService = _get_web_system_monitor_service()
            payload = service.get_processes_at_time(
                timestamp=timestamp,
                tolerance_seconds=5,
                limit=limit,
            )
            response = jsonify(payload)
            response.headers["Cache-Control"] = "private, max-age=60"
            return response, 200
        except Exception:
            logger.exception("System monitor processes_at_time error")
            return jsonify({"processes": [], "timestamp": timestamp}), 500
