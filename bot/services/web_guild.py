"""
Service layer for web guild selection.
"""

from __future__ import annotations

from typing import Any, Mapping

from bot.models.web import WebGuild
from bot.repositories.web_guild import WebGuildRepository


class WebGuildService:
    """
    Build guild selector payloads for the web UI.
    """

    def __init__(self, repository: WebGuildRepository) -> None:
        """
        Initialize the service.

        Args:
            repository: Repository used for persisted guild discovery.
        """
        self.repository = repository

    def get_guild_options(self, selected_guild_id: int | str | None = None) -> list[dict[str, Any]]:
        """
        Return known guilds for selector rendering.

        Args:
            selected_guild_id: Optional currently selected guild ID.

        Returns:
            JSON/template-ready guild option dictionaries.
        """
        rows = self.repository.get_known_guilds()
        selected = self._parse_guild_id(selected_guild_id)
        if selected is None and len(rows) == 1:
            selected = int(rows[0]["guild_id"])

        return [
            WebGuild(
                guild_id=int(row["guild_id"]),
                name=str(row["name"]),
                is_default=selected is not None and int(row["guild_id"]) == selected,
            ).to_payload()
            for row in rows
        ]

    def resolve_selected_guild_id(
        self,
        request_values: Mapping[str, Any],
        session_value: Any = None,
    ) -> int | None:
        """
        Resolve selected guild ID from request/session/known single-guild data.

        Args:
            request_values: Request args/form/json-like values.
            session_value: Optional saved session selection.

        Returns:
            Resolved guild ID, or ``None`` when ambiguous/unknown.
        """
        request_value = request_values.get("guild_id") if request_values else None
        selected = self._parse_guild_id(request_value)
        if selected is not None:
            return selected

        selected = self._parse_guild_id(session_value)
        if selected is not None:
            return selected

        rows = self.repository.get_known_guilds()
        if len(rows) == 1:
            return int(rows[0]["guild_id"])
        return None

    @staticmethod
    def _parse_guild_id(value: Any) -> int | None:
        """Parse a positive guild ID from arbitrary input."""
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        try:
            parsed = int(text)
        except ValueError:
            return None
        return parsed if parsed > 0 else None
