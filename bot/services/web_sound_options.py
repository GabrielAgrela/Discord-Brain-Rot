"""
Service layer for web sound option actions.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from rapidfuzz import fuzz

from bot.database import Database
from bot.models.web import DiscordWebUser
from bot.repositories.action import ActionRepository
from bot.repositories.event import EventRepository
from bot.repositories.list import ListRepository
from bot.repositories.sound import SoundRepository
from bot.repositories.voice_activity import VoiceActivityRepository


class WebSoundOptionsService:
    """
    Service for long-press sound options in the web soundboard.
    """

    def __init__(
        self,
        sound_repository: SoundRepository,
        list_repository: ListRepository,
        action_repository: ActionRepository,
        event_repository: EventRepository,
        voice_activity_repository: VoiceActivityRepository,
    ) -> None:
        """
        Initialize the service.

        Args:
            sound_repository: Repository for sound updates/lookups.
            list_repository: Repository for sound-list operations.
            action_repository: Repository for analytics action logging.
            event_repository: Repository for user join/leave event sounds.
            voice_activity_repository: Repository for tracked voice users.
        """
        self.sound_repository = sound_repository
        self.list_repository = list_repository
        self.action_repository = action_repository
        self.event_repository = event_repository
        self.voice_activity_repository = voice_activity_repository

    def get_options(
        self,
        sound_id: int,
        *,
        guild_id: int | str | None = None,
        current_user: DiscordWebUser | None = None,
    ) -> dict[str, Any]:
        """
        Build modal data for a sound.

        Args:
            sound_id: Sound database ID.
            guild_id: Optional selected guild scope.
            current_user: Optional authenticated user to include in target options.

        Returns:
            Sound metadata, similar sounds, and list options.

        Raises:
            ValueError: If the sound does not exist in the selected guild scope.
        """
        sound = self._get_sound_or_raise(sound_id, guild_id)
        return {
            "sound": self._format_sound(sound),
            "lists": self._get_list_options(sound.filename, guild_id),
            "events": self._get_sound_events(sound.filename, guild_id),
            "users": self._get_user_options(guild_id, current_user),
            "similar_sounds": self._get_similar_sounds(sound.filename, sound.id, guild_id),
        }

    def rename_sound(
        self,
        sound_id: int,
        new_name: str,
        current_user: DiscordWebUser,
        *,
        guild_id: int | str | None = None,
    ) -> dict[str, Any]:
        """
        Rename a sound and log the action.

        Args:
            sound_id: Sound database ID.
            new_name: New filename or bare sound name.
            current_user: Authenticated Discord web user.
            guild_id: Optional selected guild scope.

        Returns:
            Updated sound payload.
        """
        sound = self._get_sound_or_raise(sound_id, guild_id)
        normalized_name = self._normalize_sound_filename(new_name)
        if not normalized_name:
            raise ValueError("Enter a new sound name.")

        self.sound_repository.update_sound_by_id(
            sound.id,
            new_filename=normalized_name,
            guild_id=guild_id,
        )
        self.action_repository.insert(
            current_user.username,
            "change_filename",
            f"{sound.filename} to {normalized_name}",
            guild_id=guild_id,
        )
        Database._sound_cache = None
        Database._sound_cache_normalized = None
        Database._cache_timestamp = None
        updated_sound = self._get_sound_or_raise(sound_id, guild_id)
        return {"sound": self._format_sound(updated_sound)}

    def toggle_favorite(
        self,
        sound_id: int,
        current_user: DiscordWebUser,
        *,
        guild_id: int | str | None = None,
    ) -> dict[str, Any]:
        """
        Toggle a sound's global favorite flag and log the user's action.

        Args:
            sound_id: Sound database ID.
            current_user: Authenticated Discord web user.
            guild_id: Optional selected guild scope.

        Returns:
            Favorite state payload.
        """
        sound = self._get_sound_or_raise(sound_id, guild_id)
        favorite = 0 if sound.favorite else 1
        self.sound_repository.update_sound_by_id(
            sound.id,
            favorite=favorite,
            guild_id=guild_id,
        )
        self.action_repository.insert(
            current_user.username,
            "favorite_sound" if favorite else "unfavorite_sound",
            sound.id,
            guild_id=guild_id,
        )
        return {"favorite": bool(favorite)}

    def toggle_slap(
        self,
        sound_id: int,
        current_user: DiscordWebUser,
        *,
        guild_id: int | str | None = None,
        current_user_is_admin: bool = False,
    ) -> dict[str, Any]:
        """
        Toggle a sound's slap flag and log the user's action.

        Args:
            sound_id: Sound database ID.
            current_user: Authenticated Discord web user.
            guild_id: Optional selected guild scope.
            current_user_is_admin: Whether the web user can manage slap sounds.

        Returns:
            Slap state payload.
        """
        if not current_user_is_admin:
            raise PermissionError("Only admins and moderators can manage slap sounds.")

        sound = self._get_sound_or_raise(sound_id, guild_id)
        slap = 0 if sound.slap else 1
        self.sound_repository.update_sound_by_id(
            sound.id,
            slap=slap,
            guild_id=guild_id,
        )
        self.action_repository.insert(
            current_user.username,
            "slap_sound",
            sound.id,
            guild_id=guild_id,
        )
        return {"slap": bool(slap)}

    def add_to_list(
        self,
        sound_id: int,
        list_id: int,
        current_user: DiscordWebUser,
        *,
        guild_id: int | str | None = None,
    ) -> dict[str, Any]:
        """
        Add a sound to an existing sound list and log the action.

        Args:
            sound_id: Sound database ID.
            list_id: Sound-list database ID.
            current_user: Authenticated Discord web user.
            guild_id: Optional selected guild scope.

        Returns:
            Add result payload.
        """
        sound = self._get_sound_or_raise(sound_id, guild_id)
        sound_list = self.list_repository.get_by_id(list_id, guild_id=guild_id)
        if not sound_list:
            raise ValueError("List not found.")

        added = self.list_repository.add_sound(sound_list[0], sound.filename)
        if added:
            self.action_repository.insert(
                current_user.username,
                "add_sound_to_list",
                f"{sound_list[1]}:{sound.filename}",
                guild_id=guild_id,
            )
        return {
            "added": added,
            "message": "Sound added to list." if added else "Sound is already in that list.",
        }

    def toggle_user_event(
        self,
        sound_id: int,
        target_user: str,
        event_type: str,
        current_user: DiscordWebUser,
        *,
        guild_id: int | str | None = None,
        current_user_is_admin: bool = False,
    ) -> dict[str, Any]:
        """
        Toggle a sound as a join/leave event for a user.

        Args:
            sound_id: Sound database ID.
            target_user: Discord username key used by the bot event system.
            event_type: Event type, either ``join`` or ``leave``.
            current_user: Authenticated Discord web user.
            guild_id: Optional selected guild scope.
            current_user_is_admin: Whether the web user can assign events for others.

        Returns:
            Toggle result payload.
        """
        sound = self._get_sound_or_raise(sound_id, guild_id)
        normalized_event_type = str(event_type or "").strip().lower()
        if normalized_event_type not in {"join", "leave"}:
            raise ValueError("Choose join or leave.")

        normalized_target = str(target_user or "").strip()
        if not normalized_target:
            normalized_target = current_user.username

        if not self._is_self_target(current_user, normalized_target) and not current_user_is_admin:
            raise ValueError("You can only assign events for yourself.")

        sound_name = sound.filename.replace(".mp3", "")
        added = self.event_repository.toggle(
            normalized_target,
            normalized_event_type,
            sound_name,
            guild_id=guild_id,
        )
        self.action_repository.insert(
            current_user.username,
            f"add_{normalized_event_type}_sound" if added else f"delete_{normalized_event_type}_event",
            f"{normalized_target}:{sound_name}",
            guild_id=guild_id,
        )
        return {
            "added": added,
            "event": normalized_event_type,
            "target_user": normalized_target,
            "sound_name": sound_name,
            "message": (
                f"Added {normalized_event_type} event."
                if added
                else f"Removed {normalized_event_type} event."
            ),
        }

    def _get_sound_or_raise(self, sound_id: int, guild_id: int | str | None) -> Any:
        """Return a sound or raise a web-safe validation error."""
        sound = self.sound_repository.get_by_id(sound_id, guild_id=guild_id)
        if sound is None:
            raise ValueError("Sound not found.")
        return sound

    def _get_list_options(
        self,
        filename: str,
        guild_id: int | str | None,
    ) -> list[dict[str, Any]]:
        """Return sound-list options for the selected guild scope."""
        containing_list_ids = {
            row[0]
            for row in self.list_repository.get_lists_containing_sound(
                filename,
                guild_id=guild_id,
            )
        }
        return [
            {
                "id": row[0],
                "name": row[1],
                "creator": row[2],
                "sound_count": row[3] if len(row) > 3 else 0,
                "label": f"{row[1]} ({row[2]})" if row[2] else row[1],
                "contains_sound": row[0] in containing_list_ids,
            }
            for row in self.list_repository.get_all(limit=200, guild_id=guild_id)
        ]

    def _get_sound_events(
        self,
        filename: str,
        guild_id: int | str | None,
    ) -> list[dict[str, str]]:
        """Return join/leave event assignments that already use a sound."""
        return [
            {"target_user": user_id, "event": event_type}
            for user_id, event_type in self.event_repository.get_events_for_sound(
                filename,
                guild_id=guild_id,
            )
        ]

    def _get_user_options(
        self,
        guild_id: int | str | None,
        current_user: DiscordWebUser | None,
    ) -> list[dict[str, str]]:
        """Return known user choices for event assignment."""
        usernames = set(self.event_repository.get_all_users_with_events(guild_id=guild_id))
        usernames.update(self.action_repository.get_distinct_usernames(guild_id=guild_id))
        usernames.update(self.voice_activity_repository.get_distinct_usernames(guild_id=guild_id))
        if current_user and current_user.username:
            usernames.add(current_user.username)

        ordered_usernames = sorted(
            {username.strip() for username in usernames if str(username).strip()},
            key=str.casefold,
        )
        if current_user and current_user.username in ordered_usernames:
            ordered_usernames.remove(current_user.username)
            ordered_usernames.insert(0, current_user.username)

        return [
            {
                "value": username,
                "label": username,
            }
            for username in ordered_usernames
        ]

    @staticmethod
    def _is_self_target(current_user: DiscordWebUser, target_user: str) -> bool:
        """Return whether a requested event target refers to the current user."""
        normalized_target = str(target_user or "").strip().casefold()
        self_candidates = {
            current_user.username.casefold(),
            current_user.global_name.casefold(),
        }
        return normalized_target in {candidate for candidate in self_candidates if candidate}

    def _get_similar_sounds(
        self,
        filename: str,
        sound_id: int,
        guild_id: int | str | None,
    ) -> list[dict[str, Any]]:
        """Return similar sounds using the same weighted fuzzy scoring as Discord."""
        normalized_request = self._normalize_for_similarity(filename)
        scored_matches: list[tuple[float, Any]] = []
        for row in self.sound_repository.get_similarity_candidates(guild_id=guild_id):
            if row["id"] == sound_id:
                continue
            candidate_name = row["Filename"]
            normalized_candidate = self._normalize_for_similarity(candidate_name)
            score = (
                0.5 * fuzz.token_set_ratio(normalized_request, normalized_candidate)
                + 0.3 * fuzz.partial_ratio(normalized_request, normalized_candidate)
                + 0.2 * fuzz.token_sort_ratio(normalized_request, normalized_candidate)
            )
            if guild_id is not None and str(row["guild_id"]) == str(guild_id):
                score += 5.0
            scored_matches.append((score, row))

        scored_matches.sort(key=lambda item: item[0], reverse=True)
        return [
            {
                "sound_id": row["id"],
                "display_filename": row["Filename"],
                "score": int(score),
            }
            for score, row in scored_matches[:10]
        ]

    @staticmethod
    def _format_sound(sound: Any) -> dict[str, Any]:
        """Format sound data for the options modal."""
        return {
            "sound_id": sound.id,
            "display_filename": sound.filename,
            "favorite": sound.favorite,
            "slap": sound.slap,
        }

    @staticmethod
    def _normalize_sound_filename(value: str) -> str:
        """Normalize user input into a safe MP3 filename."""
        filename = Path(str(value or "").strip()).name
        if not filename:
            return ""
        if not filename.lower().endswith(".mp3"):
            filename = f"{filename}.mp3"
        return filename

    @staticmethod
    def _normalize_for_similarity(value: str) -> str:
        """Mirror Database.normalize_text without binding to the singleton DB path."""
        text = str(value or "")
        substitutions = {
            "0": "o",
            "1": "i",
            "3": "e",
            "4": "a",
            "5": "s",
            "7": "t",
            "@": "a",
            "$": "s",
            "!": "i",
        }
        for key, replacement in substitutions.items():
            text = text.replace(key, replacement)
        text = text.replace(".mp3", "")
        text = re.sub(r"[-_]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text.lower()
