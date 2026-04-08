"""
Helpers for web-triggered playback queueing and processing.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
import os
from pathlib import Path
import sqlite3
from typing import Any

from bot.models.web import DiscordWebUser
from bot.repositories.sound import SoundRepository


class WebPlaybackService:
    """
    Service for web-triggered playback requests.
    """

    def __init__(
        self,
        sound_repository: SoundRepository,
        db_path: str,
        env: Mapping[str, str] | None = None,
    ) -> None:
        """
        Initialize the service.

        Args:
            sound_repository: Repository used to resolve sound IDs.
            db_path: Path to the SQLite database.
            env: Optional environment mapping for tests.
        """
        self.sound_repository = sound_repository
        self.db_path = db_path
        self.env = env

    def resolve_sound_filename(self, payload: Mapping[str, Any]) -> str:
        """
        Resolve a playback payload into a concrete filename.

        Args:
            payload: JSON request payload.

        Returns:
            Sound filename to queue.

        Raises:
            ValueError: If the payload is invalid or the sound ID is unknown.
        """
        sound_filename = str(payload.get("sound_filename", "")).strip()
        if sound_filename:
            return sound_filename

        sound_id = payload.get("sound_id")
        if sound_id in (None, ""):
            raise ValueError("Missing sound_filename")

        try:
            sound_id_int = int(sound_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid sound_id") from exc

        sound = self.sound_repository.get_by_id(sound_id_int)
        if sound is None:
            raise ValueError("Unknown sound_id")
        return sound.filename

    def queue_request(
        self,
        payload: Mapping[str, Any],
        current_user: DiscordWebUser,
    ) -> int:
        """
        Queue a web playback request for an authenticated Discord user.

        Args:
            payload: JSON request payload.
            current_user: Authenticated Discord user.

        Returns:
            Inserted playback queue row ID.
        """
        sound_filename = self.resolve_sound_filename(payload)
        return queue_playback_request(
            sound_filename=sound_filename,
            requested_guild_id=payload.get("guild_id"),
            db_path=self.db_path,
            request_username=current_user.global_name,
            request_user_id=current_user.id,
            env=self.env,
        )


def resolve_requested_guild_id(
    requested_guild_id: Any,
    db_path: str,
    env: Mapping[str, str] | None = None,
) -> int:
    """
    Resolve the guild ID for a web playback request.

    Args:
        requested_guild_id: Explicit guild ID from the request payload.
        db_path: Path to the SQLite database used for discovery fallback.
        env: Optional environment mapping for tests.

    Returns:
        Resolved integer guild ID.

    Raises:
        ValueError: If the guild ID is invalid, missing, or ambiguous.
    """
    env_map = env if env is not None else os.environ
    guild_id_raw = requested_guild_id or env_map.get("DEFAULT_GUILD_ID", "")

    if guild_id_raw:
        return _parse_guild_id(guild_id_raw)

    discovered_guild_ids = _discover_known_guild_ids(db_path)
    if len(discovered_guild_ids) == 1:
        return discovered_guild_ids[0]
    if len(discovered_guild_ids) > 1:
        raise ValueError(
            "Missing guild_id and unable to infer one automatically because multiple guilds are configured"
        )
    raise ValueError("Missing guild_id and unable to infer one automatically")


def queue_playback_request(
    sound_filename: str,
    requested_guild_id: Any,
    db_path: str,
    request_username: str,
    request_user_id: str,
    env: Mapping[str, str] | None = None,
) -> int:
    """
    Queue a sound for playback from the web interface.

    Args:
        sound_filename: Filename to queue.
        requested_guild_id: Explicit guild ID from the request payload.
        db_path: Path to the SQLite database.
        request_username: Discord display name to attribute the request to.
        request_user_id: Discord user ID associated with the request.
        env: Optional environment mapping for tests.

    Returns:
        Inserted playback queue row ID.

    Raises:
        ValueError: If the request is missing required data or guild resolution fails.
        sqlite3.Error: If the insert fails.
    """
    if not sound_filename:
        raise ValueError("Missing sound_filename")
    if not str(request_username).strip():
        raise ValueError("Missing request_username")
    if not str(request_user_id).strip():
        raise ValueError("Missing request_user_id")

    guild_id = resolve_requested_guild_id(
        requested_guild_id=requested_guild_id,
        db_path=db_path,
        env=env,
    )

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        _ensure_playback_queue_identity_columns(cursor)
        cursor.execute(
            """
            INSERT INTO playback_queue (guild_id, sound_filename, request_username, request_user_id)
            VALUES (?, ?, ?, ?)
            """,
            (guild_id, sound_filename, str(request_username).strip(), str(request_user_id).strip()),
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


def ensure_playback_queue_identity_columns(db_path: str) -> None:
    """
    Ensure playback queue rows can store Discord web-request identity.

    Args:
        db_path: Path to the SQLite database.
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        _ensure_playback_queue_identity_columns(cursor)
        conn.commit()
    finally:
        conn.close()


async def process_playback_queue_request(
    request_row: tuple[Any, ...],
    *,
    bot: Any,
    behavior: Any,
    db: Any,
    sound_folder: str | Path,
    action_logger_factory: Callable[[], Any] | None = None,
    sleep_fn: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    now_fn: Callable[[], datetime] = datetime.now,
    logger: Callable[[str], None] = print,
) -> bool:
    """
    Process a single queued playback request.

    Args:
        request_row: Tuple containing queue row fields. Supports both the
            legacy 3-column shape and the current identity-aware shape.
        bot: Discord bot instance used to resolve guilds.
        behavior: Bot behavior object used to locate channels and play audio.
        db: Database singleton with shared cursor/connection and get_sound().
        sound_folder: Folder containing sound files.
        action_logger_factory: Optional callable returning an object with
            ``insert()`` or ``insert_action()``.
        sleep_fn: Awaitable sleep function for tests.
        now_fn: Timestamp provider for tests.
        logger: Logging function.

    Returns:
        True when playback was started, otherwise False.
    """
    request_id, guild_id, sound_filename, request_username, request_user_id = (
        _normalize_playback_queue_row(request_row)
    )

    logger(
        f"[Playback Queue] Processing request ID {request_id}: "
        f"Play '{sound_filename}' in guild {guild_id}"
    )

    def mark_played() -> None:
        db.cursor.execute(
            "UPDATE playback_queue SET played_at = ? WHERE id = ?",
            (now_fn(), request_id),
        )
        db.conn.commit()

    guild = bot.get_guild(guild_id)
    if not guild:
        logger(
            f"[Playback Queue] Error: Bot is not in guild {guild_id}. "
            f"Skipping request {request_id}."
        )
        mark_played()
        return False

    sound_data = db.get_sound(sound_filename, guild_id=guild_id)
    if not sound_data:
        logger(
            f"[Playback Queue] Error: Sound '{sound_filename}' not found in database. "
            f"Skipping request {request_id}."
        )
        mark_played()
        return False

    sound_path = Path(sound_folder) / sound_filename
    if not sound_path.exists():
        logger(
            f"[Playback Queue] Error: Sound file not found at '{sound_path}'. "
            f"Skipping request {request_id}."
        )
        mark_played()
        return False

    try:
        channel = behavior.get_largest_voice_channel(guild)
        if channel is not None:
            if request_username:
                playback_user = request_username
            elif request_user_id:
                playback_user = f"discord-user-{request_user_id}"
            else:
                playback_user = "webpage"
            await behavior.play_audio(channel, sound_filename, playback_user)
            if action_logger_factory is not None:
                action_logger = action_logger_factory()
                if hasattr(action_logger, "insert"):
                    action_logger.insert(
                        request_username or playback_user,
                        "play_request",
                        sound_data[0],
                        guild_id=guild_id,
                    )
                else:
                    action_logger.insert_action(
                        request_username or playback_user,
                        "play_request",
                        sound_data[0],
                        guild_id=guild_id,
                    )

        mark_played()
        await sleep_fn(1)
        return channel is not None
    except Exception as exc:
        logger(
            f"[Playback Queue] Error playing sound for request {request_id}: {exc}"
        )
        mark_played()
        return False


def _parse_guild_id(value: Any) -> int:
    """Parse a guild ID value into an integer."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid guild_id") from exc


def _discover_known_guild_ids(db_path: str) -> list[int]:
    """Discover guild IDs from persisted bot data for single-guild web fallback."""
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        stable_guild_ids: set[int] = set()
        fallback_guild_ids: set[int] = set()

        for query in (
            "SELECT guild_id FROM guild_settings WHERE guild_id IS NOT NULL AND TRIM(guild_id) != ''",
            "SELECT guild_id FROM sounds WHERE guild_id IS NOT NULL AND TRIM(guild_id) != ''",
            "SELECT guild_id FROM actions WHERE guild_id IS NOT NULL AND TRIM(guild_id) != ''",
        ):
            try:
                cursor.execute(query)
            except sqlite3.Error:
                continue
            for (raw_guild_id,) in cursor.fetchall():
                _add_guild_id(stable_guild_ids, raw_guild_id)

        if stable_guild_ids:
            return sorted(stable_guild_ids)

        try:
            cursor.execute(
                "SELECT guild_id FROM playback_queue WHERE guild_id IS NOT NULL"
            )
        except sqlite3.Error:
            return []

        for (raw_guild_id,) in cursor.fetchall():
            _add_guild_id(fallback_guild_ids, raw_guild_id)

        return sorted(fallback_guild_ids)
    finally:
        conn.close()


def _add_guild_id(guild_ids: set[int], raw_guild_id: Any) -> None:
    """Normalize and add a guild ID to a discovery set."""
    if raw_guild_id is None:
        return
    raw_value = str(raw_guild_id).strip()
    if not raw_value:
        return
    try:
        guild_ids.add(int(raw_value))
    except ValueError:
        return


def _ensure_playback_queue_identity_columns(cursor: sqlite3.Cursor) -> None:
    """Add playback queue identity columns when running against an older schema."""
    try:
        cursor.execute("PRAGMA table_info(playback_queue)")
    except sqlite3.Error:
        return

    existing_columns = {str(row[1]) for row in cursor.fetchall()}
    if "request_username" not in existing_columns:
        cursor.execute("ALTER TABLE playback_queue ADD COLUMN request_username TEXT")
    if "request_user_id" not in existing_columns:
        cursor.execute("ALTER TABLE playback_queue ADD COLUMN request_user_id TEXT")


def _normalize_playback_queue_row(
    request_row: tuple[Any, ...],
) -> tuple[int, int, str, str | None, str | None]:
    """Normalize old and new playback queue rows into a common tuple shape."""
    if len(request_row) >= 5:
        request_id, guild_id, sound_filename, request_username, request_user_id = request_row[:5]
        return (
            int(request_id),
            int(guild_id),
            str(sound_filename),
            str(request_username).strip() if request_username is not None else None,
            str(request_user_id).strip() if request_user_id is not None else None,
        )

    request_id, guild_id, sound_filename = request_row[:3]
    return int(request_id), int(guild_id), str(sound_filename), None, None
