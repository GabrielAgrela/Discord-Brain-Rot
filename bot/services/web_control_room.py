"""
Service layer for the web control-room status panel.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from bot.models.web import DiscordWebUser
from bot.repositories.web_control_room import WebControlRoomRepository
from bot.services.text_censor import TextCensorService
from bot.services.web_playback import get_web_control_state, resolve_requested_guild_id


class WebControlRoomService:
    """
    Build status payloads for the web soundboard control room.
    """

    def __init__(
        self,
        repository: WebControlRoomRepository,
        db_path: str,
        text_censor_service: TextCensorService,
        env: Mapping[str, str] | None = None,
    ) -> None:
        """
        Initialize the service.

        Args:
            repository: Repository for runtime status.
            db_path: SQLite database path.
            text_censor_service: Service used to mask usernames for web output.
            env: Optional environment mapping for deterministic tests.
        """
        self.repository = repository
        self.db_path = db_path
        self.text_censor_service = text_censor_service
        self.env = env

    def get_status(
        self,
        payload: Mapping[str, Any],
        current_user: DiscordWebUser | None = None,
    ) -> dict[str, Any]:
        """
        Return the current control-room status payload.

        Args:
            payload: Request query arguments or mapping.
            current_user: Optional authenticated Discord web user.

        Returns:
            JSON-serializable status payload.
        """
        guild_id = resolve_requested_guild_id(
            requested_guild_id=payload.get("guild_id"),
            db_path=self.db_path,
            env=self.env,
        )
        runtime_status = self.repository.get_status(guild_id)
        mute_state = get_web_control_state(
            requested_guild_id=guild_id,
            db_path=self.db_path,
            env=self.env,
        ).get("mute", {})

        if runtime_status:
            muted = bool(runtime_status.get("muted"))
            mute_remaining = int(runtime_status.get("mute_remaining_seconds") or 0)
            if muted or mute_remaining > 0:
                mute_state = {
                    **mute_state,
                    "is_muted": muted,
                    "remaining_seconds": mute_remaining,
                    "toggle_action": "toggle_mute",
                }

        return {
            "guild_id": guild_id,
            "status": self._format_status(runtime_status, current_user=current_user),
            "mute": mute_state,
        }

    def _format_status(
        self,
        status: dict[str, Any] | None,
        current_user: DiscordWebUser | None,
    ) -> dict[str, Any]:
        """Normalize a runtime status row for API output."""
        if not status:
            return {
                "online": False,
                "guild_name": None,
                "voice_connected": False,
                "voice_channel_name": None,
                "voice_member_count": 0,
                "voice_members": [],
                "is_playing": False,
                "is_paused": False,
                "current_sound": None,
                "current_requester": None,
                "current_duration_seconds": None,
                "current_elapsed_seconds": None,
                "updated_at": None,
            }

        return {
            "online": True,
            "guild_name": status.get("guild_name"),
            "voice_connected": bool(status.get("voice_connected")),
            "voice_channel_name": status.get("voice_channel_name"),
            "voice_member_count": int(status.get("voice_member_count") or 0),
            "voice_members": self._decode_voice_members(
                status.get("voice_members"),
                current_user=current_user,
            ),
            "is_playing": bool(status.get("is_playing")),
            "is_paused": bool(status.get("is_paused")),
            "current_sound": status.get("current_sound"),
            "current_requester": self._censor_username(
                status.get("current_requester"),
                current_user=current_user,
            ),
            "current_duration_seconds": self._coerce_optional_float(
                status.get("current_duration_seconds")
            ),
            "current_elapsed_seconds": self._coerce_optional_float(
                status.get("current_elapsed_seconds")
            ),
            "updated_at": status.get("updated_at"),
        }

    def _coerce_optional_float(self, value: Any) -> float | None:
        """Convert nullable numeric status fields to floats."""
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _decode_voice_members(
        self,
        value: Any,
        current_user: DiscordWebUser | None,
    ) -> list[dict[str, Any]]:
        """Decode persisted voice member data for API output."""
        if not value:
            return []
        try:
            members = json.loads(value)
        except (TypeError, ValueError):
            return []
        if not isinstance(members, list):
            return []

        formatted: list[dict[str, Any]] = []
        for member in members:
            if not isinstance(member, dict):
                continue
            formatted.append(
                {
                    "id": str(member.get("id") or ""),
                    "name": self._censor_username(
                        str(member.get("name") or "Unknown"),
                        current_user=current_user,
                    ),
                    "avatar_url": str(member.get("avatar_url") or ""),
                }
            )
        return formatted

    def _censor_username(
        self,
        value: str | None,
        current_user: DiscordWebUser | None,
    ) -> str | None:
        """Mask usernames only for anonymous web responses."""
        if current_user is not None:
            return value
        return self.text_censor_service.censor_username(value)
