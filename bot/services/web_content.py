"""
Service layer for web soundboard content endpoints.
"""

from __future__ import annotations

import math
from typing import Any

from bot.models.web import PaginatedQuery
from bot.repositories.web_content import WebContentRepository
from bot.services.text_censor import TextCensorService


class WebContentService:
    """
    Service for web soundboard table responses.
    """

    def __init__(
        self,
        repository: WebContentRepository,
        text_censor_service: TextCensorService,
    ) -> None:
        """
        Initialize the service.

        Args:
            repository: Repository for web content queries.
            text_censor_service: Service used to censor text for web output.
        """
        self.repository = repository
        self.text_censor_service = text_censor_service

    def get_actions(
        self,
        query: PaginatedQuery,
        include_filters: bool = True,
        filter_keys: tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        """
        Build the JSON payload for the web actions table.

        Args:
            query: Pagination, search, and filter parameters.
            include_filters: Whether to include filter metadata in the response.
            filter_keys: Optional subset of action filter groups to fetch.

        Returns:
            API response payload.
        """
        rows = self.repository.get_actions_page(query)
        total_count = self.repository.count_actions(query)
        return {
            "items": [
                {
                    "display_filename": self._censor_text(row["filename"] or row["target"]),
                    "display_username": self._censor_text(row["username"]),
                    "action": row["action"],
                    "timestamp": row["timestamp"],
                }
                for row in rows
            ],
            "total_pages": self._calculate_total_pages(total_count, query.per_page),
            "filters": (
                self.repository.get_action_filters(filter_keys)
                if include_filters
                else {}
            ),
        }

    def get_favorites(
        self,
        query: PaginatedQuery,
        include_filters: bool = True,
    ) -> dict[str, Any]:
        """
        Build the JSON payload for the favorites table.

        Args:
            query: Pagination, search, and filter parameters.
            include_filters: Whether to include filter metadata in the response.

        Returns:
            API response payload.
        """
        rows = self.repository.get_favorites_page(query)
        total_count = self.repository.count_favorites(query)
        return {
            "items": [
                {
                    "sound_id": row["sound_id"],
                    "display_filename": self._censor_text(row["filename"]),
                }
                for row in rows
            ],
            "total_pages": self._calculate_total_pages(total_count, query.per_page),
            "filters": self.repository.get_favorite_filters() if include_filters else {},
        }

    def get_all_sounds(
        self,
        query: PaginatedQuery,
        include_filters: bool = True,
    ) -> dict[str, Any]:
        """
        Build the JSON payload for the all-sounds table.

        Args:
            query: Pagination, search, and filter parameters.
            include_filters: Whether to include filter metadata in the response.

        Returns:
            API response payload.
        """
        rows = self.repository.get_all_sounds_page(query)
        total_count = self.repository.count_all_sounds(query)
        return {
            "items": [
                {
                    "sound_id": row["sound_id"],
                    "display_filename": self._censor_text(row["filename"]),
                    "timestamp": row["timestamp"],
                }
                for row in rows
            ],
            "total_pages": self._calculate_total_pages(total_count, query.per_page),
            "filters": self.repository.get_all_sound_filters() if include_filters else {},
        }

    def _censor_text(self, value: str | None) -> str | None:
        """Censor hateful text for web responses."""
        return self.text_censor_service.censor_text(value)

    @staticmethod
    def _calculate_total_pages(total_count: int, per_page: int) -> int:
        """Calculate the total number of pages for a paginated response."""
        return math.ceil(total_count / per_page) if per_page > 0 else 0
