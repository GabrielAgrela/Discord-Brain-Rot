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
    admin_guild_ids: tuple[str, ...] = ()

    @classmethod
    def from_discord_payload(
        cls,
        payload: Mapping[str, Any],
        admin_guild_ids: tuple[str, ...] = (),
    ) -> "DiscordWebUser":
        """
        Build a web-session user from Discord API payload data.

        Args:
            payload: Raw Discord user payload.
            admin_guild_ids: Guild IDs where the user has bot admin/mod permissions.

        Returns:
            Parsed authenticated user.
        """
        username = str(payload["username"])
        return cls(
            id=str(payload["id"]),
            username=username,
            global_name=str(payload.get("global_name") or username),
            avatar=str(payload.get("avatar") or ""),
            admin_guild_ids=tuple(str(guild_id) for guild_id in admin_guild_ids),
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
        raw_admin_guild_ids = payload.get("admin_guild_ids") or ()
        if not isinstance(raw_admin_guild_ids, (list, tuple, set)):
            raw_admin_guild_ids = ()
        admin_guild_ids = tuple(
            str(guild_id).strip()
            for guild_id in raw_admin_guild_ids
            if str(guild_id).strip()
        )

        if not user_id or not username:
            return None

        return cls(
            id=user_id,
            username=username,
            global_name=global_name or username,
            avatar=avatar,
            admin_guild_ids=admin_guild_ids,
        )

    def to_session_payload(self) -> dict[str, Any]:
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
            "admin_guild_ids": list(self.admin_guild_ids),
        }


@dataclass(frozen=True)
class PaginatedQuery:
    """
    Shared web query parameters for paginated endpoints.
    """

    page: int
    per_page: int
    search_query: str = ""
    guild_id: int | None = None
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


@dataclass(frozen=True)
class WebGuild:
    """
    Guild option exposed to the web UI.

    Attributes:
        guild_id: Discord guild ID.
        name: Display label for the selector.
        is_default: Whether this is the selected/default option.
    """

    guild_id: int
    name: str
    is_default: bool = False

    def to_payload(self) -> dict[str, Any]:
        """Serialize the guild option for JSON/template usage."""
        return {
            "guild_id": self.guild_id,
            "name": self.name,
            "is_default": self.is_default,
        }
