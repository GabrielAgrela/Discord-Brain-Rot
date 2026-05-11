"""
Service layer for web analytics endpoints.
"""

from __future__ import annotations

from typing import Any

from bot.models.web import AnalyticsQuery, DiscordWebUser
from bot.repositories.web_analytics import WebAnalyticsRepository
from bot.repositories.web_user_access import WebUserAccessRepository
from bot.services.text_censor import TextCensorService


class WebAnalyticsService:
    """
    Service for analytics dashboard responses.
    """

    def __init__(
        self,
        repository: WebAnalyticsRepository,
        text_censor_service: TextCensorService,
        user_access_repository: WebUserAccessRepository,
    ) -> None:
        """
        Initialize the service.

        Args:
            repository: Repository for analytics queries.
            text_censor_service: Service used to censor text for web output.
            user_access_repository: Repository for web-session access checks.
        """
        self.repository = repository
        self.text_censor_service = text_censor_service
        self.user_access_repository = user_access_repository

    def get_summary(self, days: int) -> dict[str, int]:
        """
        Get summary dashboard metrics.

        Args:
            days: Optional day window. ``0`` means all time.

        Returns:
            Summary statistics payload.
        """
        return self.repository.get_summary_stats(days)

    def get_top_users(
        self,
        query: AnalyticsQuery,
        current_user: DiscordWebUser | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """
        Get top users payload for the dashboard.

        Args:
            query: Analytics query parameters.
            current_user: Optional authenticated Discord web user.

        Returns:
            API response payload.
        """
        rows = self.repository.get_top_users(query)
        return {
            "users": [
                {
                    "display_username": self._censor_username(
                        row["username"],
                        current_user=current_user,
                    ),
                    "count": row["count"],
                }
                for row in rows
            ]
        }

    def get_top_sounds(
        self,
        query: AnalyticsQuery,
        current_user: DiscordWebUser | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """
        Get top sounds payload for the dashboard.

        Args:
            query: Analytics query parameters.
            current_user: Optional authenticated Discord web user.

        Returns:
            API response payload.
        """
        rows = self.repository.get_top_sounds(query)
        should_censor = self._should_censor(current_user)
        return {
            "sounds": [
                {
                    "sound_id": row["sound_id"],
                    "display_filename": self._censor_text(
                        row["filename"],
                        should_censor=should_censor,
                    ),
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

    def get_recent_activity(
        self,
        limit: int,
        current_user: DiscordWebUser | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """
        Get recent activity feed payload.

        Args:
            limit: Maximum rows to return.
            current_user: Optional authenticated Discord web user.

        Returns:
            API response payload.
        """
        rows = self.repository.get_recent_activity(limit)
        should_censor = self._should_censor(current_user)
        return {
            "activities": [
                {
                    "display_username": self._censor_username(
                        row["username"],
                        current_user=current_user,
                    ),
                    "action": row["action"],
                    "timestamp": row["timestamp"],
                    "display_sound": self._censor_text(
                        row["filename"],
                        should_censor=should_censor,
                    )
                    if row["filename"]
                    else None,
                }
                for row in rows
            ]
        }

    def _censor_text(self, value: str | None, should_censor: bool) -> str | None:
        """Censor hateful text for web responses when needed."""
        if not should_censor:
            return value
        return self.text_censor_service.censor_text(value)

    def _censor_username(
        self,
        value: str | None,
        current_user: DiscordWebUser | None,
    ) -> str | None:
        """Mask usernames only for anonymous web responses."""
        if current_user is not None:
            return value
        return self.text_censor_service.censor_username(value)

    def _should_censor(self, current_user: DiscordWebUser | None) -> bool:
        """Return whether web labels should be censored for this request."""
        if current_user is None:
            return True
        return not self.user_access_repository.has_voice_activity_for_usernames(
            (current_user.username, current_user.global_name)
        )
