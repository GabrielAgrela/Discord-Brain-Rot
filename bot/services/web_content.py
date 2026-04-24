"""
Service layer for web soundboard content endpoints.
"""

from __future__ import annotations

import math
from typing import Any

from bot.models.web import DiscordWebUser, PaginatedQuery
from bot.repositories.web_content import WebContentRepository
from bot.repositories.web_user_access import WebUserAccessRepository
from bot.services.text_censor import TextCensorService


class WebContentService:
    """
    Service for web soundboard table responses.
    """

    def __init__(
        self,
        repository: WebContentRepository,
        text_censor_service: TextCensorService,
        user_access_repository: WebUserAccessRepository,
    ) -> None:
        """
        Initialize the service.

        Args:
            repository: Repository for web content queries.
            text_censor_service: Service used to censor text for web output.
            user_access_repository: Repository for web-session access checks.
        """
        self.repository = repository
        self.text_censor_service = text_censor_service
        self.user_access_repository = user_access_repository

    def get_actions(
        self,
        query: PaginatedQuery,
        include_filters: bool = True,
        filter_keys: tuple[str, ...] | None = None,
        current_user: DiscordWebUser | None = None,
    ) -> dict[str, Any]:
        """
        Build the JSON payload for the web actions table.

        Args:
            query: Pagination, search, and filter parameters.
            include_filters: Whether to include filter metadata in the response.
            filter_keys: Optional subset of action filter groups to fetch.
            current_user: Optional authenticated Discord web user.

        Returns:
            API response payload.
        """
        rows = self.repository.get_actions_page(query)
        total_count = self.repository.count_actions(query)
        should_censor = self._should_censor(current_user)
        return {
            "items": [
                {
                    "display_filename": self._censor_text(
                        row["filename"] or row["target"],
                        should_censor=should_censor,
                    ),
                    "display_username": self._censor_text(
                        row["username"],
                        should_censor=should_censor,
                    ),
                    "action": row["action"],
                    "timestamp": row["timestamp"],
                }
                for row in rows
            ],
            "total_pages": self._calculate_total_pages(total_count, query.per_page),
            "filters": self._get_action_filters(query, include_filters, filter_keys),
        }

    def get_favorites(
        self,
        query: PaginatedQuery,
        include_filters: bool = True,
        filter_keys: tuple[str, ...] | None = None,
        current_user: DiscordWebUser | None = None,
    ) -> dict[str, Any]:
        """
        Build the JSON payload for the favorites table.

        Args:
            query: Pagination, search, and filter parameters.
            include_filters: Whether to include filter metadata in the response.
            filter_keys: Optional subset of favorite filter groups to fetch.
            current_user: Optional authenticated Discord web user.

        Returns:
            API response payload.
        """
        rows = self.repository.get_favorites_page(query)
        total_count = self.repository.count_favorites(query)
        should_censor = self._should_censor(current_user)
        return {
            "items": [
                {
                    "sound_id": row["sound_id"],
                    "display_filename": self._censor_text(
                        row["filename"],
                        should_censor=should_censor,
                    ),
                }
                for row in rows
            ],
            "total_pages": self._calculate_total_pages(total_count, query.per_page),
            "filters": self._get_favorite_filters(query, include_filters, filter_keys),
        }

    def get_all_sounds(
        self,
        query: PaginatedQuery,
        include_filters: bool = True,
        filter_keys: tuple[str, ...] | None = None,
        current_user: DiscordWebUser | None = None,
    ) -> dict[str, Any]:
        """
        Build the JSON payload for the all-sounds table.

        Args:
            query: Pagination, search, and filter parameters.
            include_filters: Whether to include filter metadata in the response.
            filter_keys: Optional subset of all-sounds filter groups to fetch.
            current_user: Optional authenticated Discord web user.

        Returns:
            API response payload.
        """
        rows = self.repository.get_all_sounds_page(query)
        total_count = self.repository.count_all_sounds(query)
        should_censor = self._should_censor(current_user)
        return {
            "items": [
                {
                    "sound_id": row["sound_id"],
                    "display_filename": self._censor_text(
                        row["filename"],
                        should_censor=should_censor,
                    ),
                    "timestamp": row["timestamp"],
                }
                for row in rows
            ],
            "total_pages": self._calculate_total_pages(total_count, query.per_page),
            "filters": self._get_all_sound_filters(query, include_filters, filter_keys),
        }

    def _get_action_filters(
        self,
        query: PaginatedQuery,
        include_filters: bool,
        filter_keys: tuple[str, ...] | None,
    ) -> dict[str, Any]:
        """Return scoped action filters when requested."""
        if not include_filters:
            return {}
        return self.repository.get_action_filters(filter_keys, guild_id=query.guild_id)

    def _get_favorite_filters(
        self,
        query: PaginatedQuery,
        include_filters: bool,
        filter_keys: tuple[str, ...] | None,
    ) -> dict[str, Any]:
        """Return scoped favorite filters when requested."""
        if not include_filters:
            return {}
        return self.repository.get_favorite_filters(filter_keys, guild_id=query.guild_id)

    def _get_all_sound_filters(
        self,
        query: PaginatedQuery,
        include_filters: bool,
        filter_keys: tuple[str, ...] | None,
    ) -> dict[str, Any]:
        """Return scoped all-sound filters when requested."""
        if not include_filters:
            return {}
        return self.repository.get_all_sound_filters(filter_keys, guild_id=query.guild_id)

    def _censor_text(self, value: str | None, should_censor: bool) -> str | None:
        """Censor hateful text for web responses when needed."""
        if not should_censor:
            return value
        return self.text_censor_service.censor_text(value)

    def _should_censor(self, current_user: DiscordWebUser | None) -> bool:
        """Return whether web labels should be censored for this request."""
        if current_user is None:
            return True
        return not self.user_access_repository.has_voice_activity_for_usernames(
            (current_user.username, current_user.global_name)
        )

    @staticmethod
    def _calculate_total_pages(total_count: int, per_page: int) -> int:
        """Calculate the total number of pages for a paginated response."""
        return math.ceil(total_count / per_page) if per_page > 0 else 0
