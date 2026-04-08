"""
Service layer for web analytics endpoints.
"""

from __future__ import annotations

from typing import Any

from bot.models.web import AnalyticsQuery
from bot.repositories.web_analytics import WebAnalyticsRepository
from bot.services.text_censor import TextCensorService


class WebAnalyticsService:
    """
    Service for analytics dashboard responses.
    """

    def __init__(
        self,
        repository: WebAnalyticsRepository,
        text_censor_service: TextCensorService,
    ) -> None:
        """
        Initialize the service.

        Args:
            repository: Repository for analytics queries.
            text_censor_service: Service used to censor text for web output.
        """
        self.repository = repository
        self.text_censor_service = text_censor_service

    def get_summary(self, days: int) -> dict[str, int]:
        """
        Get summary dashboard metrics.

        Args:
            days: Optional day window. ``0`` means all time.

        Returns:
            Summary statistics payload.
        """
        return self.repository.get_summary_stats(days)

    def get_top_users(self, query: AnalyticsQuery) -> dict[str, list[dict[str, Any]]]:
        """
        Get top users payload for the dashboard.

        Args:
            query: Analytics query parameters.

        Returns:
            API response payload.
        """
        rows = self.repository.get_top_users(query)
        return {
            "users": [
                {
                    "display_username": self._censor_text(row["username"]),
                    "count": row["count"],
                }
                for row in rows
            ]
        }

    def get_top_sounds(self, query: AnalyticsQuery) -> dict[str, list[dict[str, Any]]]:
        """
        Get top sounds payload for the dashboard.

        Args:
            query: Analytics query parameters.

        Returns:
            API response payload.
        """
        rows = self.repository.get_top_sounds(query)
        return {
            "sounds": [
                {
                    "sound_id": row["sound_id"],
                    "display_filename": self._censor_text(row["filename"]),
                    "count": row["count"],
                }
                for row in rows
            ]
        }

    def get_activity_heatmap(self, days: int) -> dict[str, list[dict[str, Any]]]:
        """
        Get activity heatmap payload.

        Args:
            days: Optional day window. ``0`` means all time.

        Returns:
            API response payload.
        """
        return {"heatmap": self.repository.get_activity_heatmap(days)}

    def get_activity_timeline(self, days: int) -> dict[str, list[dict[str, Any]]]:
        """
        Get activity timeline payload.

        Args:
            days: Optional day window. ``0`` means all time.

        Returns:
            API response payload.
        """
        return {"timeline": self.repository.get_activity_timeline(days)}

    def get_recent_activity(self, limit: int) -> dict[str, list[dict[str, Any]]]:
        """
        Get recent activity feed payload.

        Args:
            limit: Maximum rows to return.

        Returns:
            API response payload.
        """
        rows = self.repository.get_recent_activity(limit)
        return {
            "activities": [
                {
                    "display_username": self._censor_text(row["username"]),
                    "action": row["action"],
                    "timestamp": row["timestamp"],
                    "display_sound": self._censor_text(row["filename"])
                    if row["filename"]
                    else None,
                }
                for row in rows
            ]
        }

    def _censor_text(self, value: str | None) -> str | None:
        """Censor hateful text for web responses."""
        return self.text_censor_service.censor_text(value)
