"""
Web-facing models for the optional Flask application.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class DiscordWebUser:
    """
    Authenticated Discord user stored in the web session.
    """

    id: str
    username: str
    global_name: str
    avatar: str = ""

    @classmethod
    def from_discord_payload(cls, payload: Mapping[str, Any]) -> "DiscordWebUser":
        """
        Build a web-session user from Discord API payload data.

        Args:
            payload: Raw Discord user payload.

        Returns:
            Parsed authenticated user.
        """
        username = str(payload["username"])
        return cls(
            id=str(payload["id"]),
            username=username,
            global_name=str(payload.get("global_name") or username),
            avatar=str(payload.get("avatar") or ""),
        )

    @classmethod
    def from_session_payload(cls, payload: Any) -> "DiscordWebUser | None":
        """
        Parse a session value into a Discord web user.

        Args:
            payload: Arbitrary session payload.

        Returns:
            Parsed user when the payload is valid, otherwise ``None``.
        """
        if not isinstance(payload, Mapping):
            return None

        user_id = str(payload.get("id") or "").strip()
        username = str(payload.get("username") or "").strip()
        global_name = str(payload.get("global_name") or username).strip()
        avatar = str(payload.get("avatar") or "").strip()

        if not user_id or not username:
            return None

        return cls(
            id=user_id,
            username=username,
            global_name=global_name or username,
            avatar=avatar,
        )

    def to_session_payload(self) -> dict[str, str]:
        """
        Serialize the user for Flask session storage.

        Returns:
            JSON-serializable session payload.
        """
        return {
            "id": self.id,
            "username": self.username,
            "global_name": self.global_name,
            "avatar": self.avatar,
        }


@dataclass(frozen=True)
class PaginatedQuery:
    """
    Shared web query parameters for paginated endpoints.
    """

    page: int
    per_page: int
    search_query: str = ""
    filters: dict[str, list[str]] = field(default_factory=dict)

    @property
    def offset(self) -> int:
        """Return the SQL offset for the current page."""
        return (self.page - 1) * self.per_page


@dataclass(frozen=True)
class AnalyticsQuery:
    """
    Query parameters for analytics endpoints.
    """

    days: int
    limit: int = 10
