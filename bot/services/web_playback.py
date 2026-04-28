"""
Helpers for web-triggered playback queueing and processing.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
import io
import json
import os
from pathlib import Path
import random
import sqlite3
from types import SimpleNamespace
from typing import Any

from config import TTS_PROFILES
from bot.models.web import DiscordWebUser
from bot.repositories.sound import SoundRepository


WEB_QUEUE_PLAY_SOUND = "play_sound"
WEB_QUEUE_SLAP = "slap"
WEB_QUEUE_MUTE_30_MINUTES = "mute_30_minutes"
WEB_QUEUE_TOGGLE_MUTE = "toggle_mute"
WEB_QUEUE_TTS = "tts"
WEB_QUEUE_CONTROL_PLACEHOLDER = "__web_control__"
WEB_PLAY_ACTION_REQUEST = "play_request"
WEB_PLAY_ACTION_SIMILAR = "play_similar_sound"
WEB_MUTE_DURATION_SECONDS = 1800
WEB_TTS_MAX_LENGTH = 20000
WEB_ALLOWED_PLAY_ACTIONS = {WEB_PLAY_ACTION_REQUEST, WEB_PLAY_ACTION_SIMILAR}
WEB_QUEUE_CONTROL_ACTIONS = {
    WEB_QUEUE_SLAP,
    WEB_QUEUE_MUTE_30_MINUTES,
    WEB_QUEUE_TOGGLE_MUTE,
    WEB_QUEUE_TTS,
}


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
            sound = self.sound_repository.get_by_filename(
                sound_filename,
                guild_id=payload.get("guild_id"),
            )
            if sound is not None and getattr(sound, "blacklist", False) is True:
                raise ValueError("Sound is rejected")
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
        if getattr(sound, "blacklist", False) is True:
            raise ValueError("Sound is rejected")
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
            play_action=payload.get("play_action"),
            env=self.env,
        )

    def queue_control_request(
        self,
        payload: Mapping[str, Any],
        current_user: DiscordWebUser,
    ) -> int:
        """
        Queue a web control request for the bot to execute.

        Args:
            payload: JSON request payload.
            current_user: Authenticated Discord user.

        Returns:
            Inserted playback queue row ID.
        """
        return queue_control_request(
            control_action=payload.get("action"),
            control_payload={
                "message": payload.get("message"),
                "profile": payload.get("profile"),
            },
            requested_guild_id=payload.get("guild_id"),
            db_path=self.db_path,
            request_username=current_user.global_name,
            request_user_id=current_user.id,
            env=self.env,
        )

    def get_control_state(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """
        Return current web control state inferred from persisted bot actions.

        Args:
            payload: Request payload or query mapping.

        Returns:
            Control state used by the web UI.
        """
        return get_web_control_state(
            requested_guild_id=payload.get("guild_id"),
            db_path=self.db_path,
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
    play_action: Any = None,
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
        play_action: Analytics action to record when the bot consumes the row.
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
    normalized_play_action = str(play_action or WEB_PLAY_ACTION_REQUEST).strip()
    if normalized_play_action not in WEB_ALLOWED_PLAY_ACTIONS:
        raise ValueError("Invalid play_action")

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
            INSERT INTO playback_queue (
                guild_id,
                sound_filename,
                request_username,
                request_user_id,
                request_type,
                play_action
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                sound_filename,
                str(request_username).strip(),
                str(request_user_id).strip(),
                WEB_QUEUE_PLAY_SOUND,
                normalized_play_action,
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


def queue_control_request(
    control_action: Any,
    requested_guild_id: Any,
    db_path: str,
    request_username: str,
    request_user_id: str,
    env: Mapping[str, str] | None = None,
    control_payload: Any = None,
) -> int:
    """
    Queue a web control action for bot-side execution.

    Args:
        control_action: Control action name to execute.
        control_payload: Optional control payload, such as TTS text.
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
    action = str(control_action or "").strip()
    if action not in WEB_QUEUE_CONTROL_ACTIONS:
        raise ValueError("Invalid web control action")
    if not str(request_username).strip():
        raise ValueError("Missing request_username")
    if not str(request_user_id).strip():
        raise ValueError("Missing request_user_id")
    queued_payload = WEB_QUEUE_CONTROL_PLACEHOLDER
    if action == WEB_QUEUE_TTS:
        speech, profile_key = _normalize_web_tts_payload(control_payload)
        if not speech:
            raise ValueError("Missing TTS message")
        if len(speech) > WEB_TTS_MAX_LENGTH:
            raise ValueError(f"TTS message must be {WEB_TTS_MAX_LENGTH} characters or fewer")
        queued_payload = json.dumps(
            {"message": speech, "profile": profile_key},
            ensure_ascii=True,
            separators=(",", ":"),
        )

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
            INSERT INTO playback_queue (
                guild_id,
                sound_filename,
                request_username,
                request_user_id,
                request_type,
                control_action
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                queued_payload,
                str(request_username).strip(),
                str(request_user_id).strip(),
                action,
                action,
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


def get_web_control_state(
    requested_guild_id: Any,
    db_path: str,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """
    Return web control state inferred from the latest mute/unmute action.

    Args:
        requested_guild_id: Explicit guild ID from the request.
        db_path: Path to the SQLite database.
        env: Optional environment mapping for tests.

    Returns:
        Dict containing mute state details.
    """
    guild_id = resolve_requested_guild_id(
        requested_guild_id=requested_guild_id,
        db_path=db_path,
        env=env,
    )
    latest_mute_action = _get_latest_mute_action(db_path, guild_id)
    is_muted = False
    remaining_seconds = 0

    if latest_mute_action:
        action, timestamp = latest_mute_action
        if action == WEB_QUEUE_MUTE_30_MINUTES:
            parsed_timestamp = _parse_action_timestamp(timestamp)
            if parsed_timestamp is None:
                is_muted = True
            else:
                mute_until = parsed_timestamp + timedelta(seconds=WEB_MUTE_DURATION_SECONDS)
                remaining_seconds = max(0, int((mute_until - datetime.now()).total_seconds()))
                is_muted = remaining_seconds > 0

    return {
        "guild_id": guild_id,
        "mute": {
            "is_muted": is_muted,
            "remaining_seconds": remaining_seconds,
            "toggle_action": WEB_QUEUE_TOGGLE_MUTE,
        },
    }


def _normalize_web_tts_payload(payload: Any) -> tuple[str, str]:
    """Normalize queued or incoming web TTS payload into message/profile."""
    if isinstance(payload, Mapping):
        speech = str(payload.get("message") or "").strip()
        profile_key = str(payload.get("profile") or "en").strip() or "en"
        return speech, profile_key if profile_key in TTS_PROFILES else "en"

    payload_text = str(payload or "").strip()
    if not payload_text:
        return "", "en"

    try:
        decoded_payload = json.loads(payload_text)
    except (TypeError, ValueError):
        return payload_text, "en"

    if not isinstance(decoded_payload, Mapping):
        return payload_text, "en"

    speech = str(decoded_payload.get("message") or "").strip()
    profile_key = str(decoded_payload.get("profile") or "en").strip() or "en"
    return speech, profile_key if profile_key in TTS_PROFILES else "en"


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
        now_fn: Timestamp provider for tests.
        logger: Logging function.

    Returns:
        True when playback was started, otherwise False.
    """
    (
        request_id,
        guild_id,
        sound_filename,
        request_username,
        request_user_id,
        request_type,
        control_action,
        play_action,
    ) = (
        _normalize_playback_queue_row(request_row)
    )

    logger(
        f"[Playback Queue] Processing request ID {request_id}: "
        f"{request_type} '{sound_filename}' in guild {guild_id}"
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

    if request_type != WEB_QUEUE_PLAY_SOUND:
        result = await _process_web_control_request(
            request_id=request_id,
            guild_id=guild_id,
            guild=guild,
            control_action=control_action or request_type,
            control_payload=sound_filename,
            request_username=request_username,
            request_user_id=request_user_id,
            behavior=behavior,
            db=db,
            action_logger_factory=action_logger_factory,
            logger=logger,
        )
        mark_played()
        return result

    sound_data = db.get_sound(sound_filename, guild_id=guild_id)
    if not sound_data:
        logger(
            f"[Playback Queue] Error: Sound '{sound_filename}' not found in database. "
            f"Skipping request {request_id}."
        )
        mark_played()
        return False

    playback_filename = sound_filename
    sound_path = Path(sound_folder) / playback_filename
    if not sound_path.exists():
        original_filename = _get_original_sound_filename(sound_data)
        original_sound_path = (
            Path(sound_folder) / original_filename if original_filename else None
        )
        if (
            original_filename
            and original_filename != sound_filename
            and original_sound_path is not None
            and original_sound_path.exists()
        ):
            logger(
                f"[Playback Queue] Sound file not found at '{sound_path}'. "
                f"Falling back to original file '{original_sound_path}'."
            )
            playback_filename = original_filename
        else:
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
            await behavior.play_audio(channel, playback_filename, playback_user)
            if action_logger_factory is not None:
                action_logger = action_logger_factory()
                if hasattr(action_logger, "insert"):
                    action_logger.insert(
                        request_username or playback_user,
                        play_action,
                        sound_data[0],
                        guild_id=guild_id,
                    )
                else:
                    action_logger.insert_action(
                        request_username or playback_user,
                        play_action,
                        sound_data[0],
                        guild_id=guild_id,
                    )

        mark_played()
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
            "SELECT guild_id FROM web_bot_status WHERE guild_id IS NOT NULL AND TRIM(guild_id) != ''",
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


def _get_latest_mute_action(db_path: str, guild_id: int) -> tuple[str, str | None] | None:
    """Return the latest persisted mute/unmute action for a guild."""
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        row = cursor.execute(
            """
            SELECT action, timestamp
            FROM actions
            WHERE action IN (?, ?)
              AND guild_id = ?
            ORDER BY timestamp DESC, id DESC
            LIMIT 1
            """,
            (WEB_QUEUE_MUTE_30_MINUTES, "unmute", str(guild_id)),
        ).fetchone()
        if row is None:
            return None
        return str(row[0]), str(row[1]) if row[1] is not None else None
    finally:
        conn.close()


def _parse_action_timestamp(timestamp: str | None) -> datetime | None:
    """Parse the action timestamp format used by ActionRepository."""
    if not timestamp:
        return None
    normalized_timestamp = str(timestamp).strip().replace("Z", "+00:00")
    try:
        parsed_timestamp = datetime.fromisoformat(normalized_timestamp)
    except ValueError:
        try:
            parsed_timestamp = datetime.strptime(
                normalized_timestamp,
                "%Y-%m-%d %H:%M:%S",
            )
        except ValueError:
            return None

    if parsed_timestamp.tzinfo is not None:
        parsed_timestamp = parsed_timestamp.astimezone().replace(tzinfo=None)
    return parsed_timestamp


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


def _get_original_sound_filename(sound_data: Any) -> str | None:
    """Extract ``originalfilename`` from a DB sound row tuple when available."""
    try:
        original_filename = sound_data[1]
    except (IndexError, KeyError, TypeError):
        return None

    if original_filename is None:
        return None
    original_filename_text = str(original_filename).strip()
    return original_filename_text or None


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
    if "request_type" not in existing_columns:
        cursor.execute(
            "ALTER TABLE playback_queue ADD COLUMN request_type TEXT DEFAULT 'play_sound'"
        )
    if "control_action" not in existing_columns:
        cursor.execute("ALTER TABLE playback_queue ADD COLUMN control_action TEXT")
    if "play_action" not in existing_columns:
        cursor.execute("ALTER TABLE playback_queue ADD COLUMN play_action TEXT DEFAULT 'play_request'")


def _normalize_playback_queue_row(
    request_row: tuple[Any, ...],
) -> tuple[int, int, str, str | None, str | None, str, str | None, str]:
    """Normalize old and new playback queue rows into a common tuple shape."""
    if len(request_row) >= 8:
        (
            request_id,
            guild_id,
            sound_filename,
            request_username,
            request_user_id,
            request_type,
            control_action,
            play_action,
        ) = request_row[:8]
        normalized_request_type = str(request_type or WEB_QUEUE_PLAY_SOUND).strip()
        normalized_play_action = str(play_action or WEB_PLAY_ACTION_REQUEST).strip()
        if normalized_play_action not in WEB_ALLOWED_PLAY_ACTIONS:
            normalized_play_action = WEB_PLAY_ACTION_REQUEST
        return (
            int(request_id),
            int(guild_id),
            str(sound_filename),
            str(request_username).strip() if request_username is not None else None,
            str(request_user_id).strip() if request_user_id is not None else None,
            normalized_request_type or WEB_QUEUE_PLAY_SOUND,
            str(control_action).strip() if control_action is not None else None,
            normalized_play_action,
        )

    if len(request_row) >= 7:
        (
            request_id,
            guild_id,
            sound_filename,
            request_username,
            request_user_id,
            request_type,
            control_action,
        ) = request_row[:7]
        normalized_request_type = str(request_type or WEB_QUEUE_PLAY_SOUND).strip()
        return (
            int(request_id),
            int(guild_id),
            str(sound_filename),
            str(request_username).strip() if request_username is not None else None,
            str(request_user_id).strip() if request_user_id is not None else None,
            normalized_request_type or WEB_QUEUE_PLAY_SOUND,
            str(control_action).strip() if control_action is not None else None,
            WEB_PLAY_ACTION_REQUEST,
        )

    if len(request_row) >= 5:
        request_id, guild_id, sound_filename, request_username, request_user_id = request_row[:5]
        return (
            int(request_id),
            int(guild_id),
            str(sound_filename),
            str(request_username).strip() if request_username is not None else None,
            str(request_user_id).strip() if request_user_id is not None else None,
            WEB_QUEUE_PLAY_SOUND,
            None,
            WEB_PLAY_ACTION_REQUEST,
        )

    request_id, guild_id, sound_filename = request_row[:3]
    return (
        int(request_id),
        int(guild_id),
        str(sound_filename),
        None,
        None,
        WEB_QUEUE_PLAY_SOUND,
        None,
        WEB_PLAY_ACTION_REQUEST,
    )


async def _process_web_control_request(
    *,
    request_id: int,
    guild_id: int,
    guild: Any,
    control_action: str,
    control_payload: str,
    request_username: str | None,
    request_user_id: str | None,
    behavior: Any,
    db: Any,
    action_logger_factory: Callable[[], Any] | None,
    logger: Callable[[str], None],
) -> bool:
    """Execute a queued web control request."""
    playback_user = _get_web_playback_user(request_username, request_user_id)

    try:
        if control_action == WEB_QUEUE_SLAP:
            return await _play_random_web_slap(
                request_id=request_id,
                guild_id=guild_id,
                guild=guild,
                playback_user=playback_user,
                behavior=behavior,
                db=db,
                action_logger_factory=action_logger_factory,
                logger=logger,
                require_slap=True,
            )

        if control_action == WEB_QUEUE_MUTE_30_MINUTES:
            await _play_random_web_slap(
                request_id=request_id,
                guild_id=guild_id,
                guild=guild,
                playback_user=playback_user,
                behavior=behavior,
                db=db,
                action_logger_factory=action_logger_factory,
                logger=logger,
                require_slap=False,
            )
            await behavior.activate_mute(duration_seconds=1800, requested_by=playback_user)
            _log_web_control_action(
                action_logger_factory,
                playback_user,
                "mute_30_minutes",
                "",
                guild_id,
            )
            return True

        if control_action == WEB_QUEUE_TOGGLE_MUTE:
            if behavior.get_mute_remaining() > 0:
                await behavior.deactivate_mute(requested_by=playback_user)
                _log_web_control_action(
                    action_logger_factory,
                    playback_user,
                    "unmute",
                    "",
                    guild_id,
                )
            else:
                await _play_random_web_slap(
                    request_id=request_id,
                    guild_id=guild_id,
                    guild=guild,
                    playback_user=playback_user,
                    behavior=behavior,
                    db=db,
                    action_logger_factory=action_logger_factory,
                    logger=logger,
                    require_slap=False,
                )
                await behavior.activate_mute(duration_seconds=1800, requested_by=playback_user)
                _log_web_control_action(
                    action_logger_factory,
                    playback_user,
                    "mute_30_minutes",
                    "",
                    guild_id,
                )
            return True

        if control_action == WEB_QUEUE_TTS:
            speech, profile_key = _normalize_web_tts_payload(control_payload)
            if not speech or speech == WEB_QUEUE_CONTROL_PLACEHOLDER:
                logger(
                    f"[Playback Queue] Error: Missing TTS message for request {request_id}."
                )
                return False
            profile = TTS_PROFILES.get(profile_key, TTS_PROFILES["en"])
            web_user = SimpleNamespace(
                name=playback_user,
                display_name=playback_user,
                guild=guild,
            )
            loading_message = await _send_web_tts_loading_card(behavior, guild)
            if profile.get("provider") == "elevenlabs":
                await behavior._voice_transformation_service.tts_EL(
                    web_user,
                    speech,
                    profile.get("voice", "en"),
                    loading_message=loading_message,
                    sts_thumbnail_url=profile.get("thumbnail"),
                )
            else:
                await behavior._voice_transformation_service.tts(
                    web_user,
                    speech,
                    profile.get("lang", "en"),
                    profile.get("region", ""),
                    loading_message=loading_message,
                )
            return True

        logger(
            f"[Playback Queue] Error: Unknown web control action '{control_action}' "
            f"for request {request_id}."
        )
        return False
    except Exception as exc:
        logger(
            f"[Playback Queue] Error executing web control request {request_id}: {exc}"
        )
        return False


async def _send_web_tts_loading_card(behavior: Any, guild: Any) -> Any:
    """Send the same loading card used by Discord TTS commands."""
    message_service = getattr(behavior, "_message_service", None)
    bot_channel = None
    if message_service is not None:
        get_bot_channel = getattr(message_service, "get_bot_channel", None)
        if callable(get_bot_channel):
            bot_channel = get_bot_channel(guild)
    if bot_channel is None:
        return None

    image_bytes = None
    audio_service = getattr(behavior, "_audio_service", None)
    image_generator = getattr(audio_service, "image_generator", None)
    generate_loading_gif = getattr(image_generator, "generate_loading_gif", None)
    if callable(generate_loading_gif):
        image_bytes = generate_loading_gif()

    try:
        import discord

        if image_bytes:
            file = discord.File(io.BytesIO(image_bytes), filename="loading.gif")
            return await bot_channel.send(file=file)

        embed = discord.Embed(
            title="⏳ Processing...",
            description="Generating audio, please wait",
            color=discord.Color.dark_blue(),
        )
        return await bot_channel.send(embed=embed)
    except Exception:
        return await bot_channel.send("⏳ Processing...")


async def _play_random_web_slap(
    *,
    request_id: int,
    guild_id: int,
    guild: Any,
    playback_user: str,
    behavior: Any,
    db: Any,
    action_logger_factory: Callable[[], Any] | None,
    logger: Callable[[str], None],
    require_slap: bool,
) -> bool:
    """Play a random slap for a web control request."""
    slap_sounds = db.get_sounds(slap=True, num_sounds=100, guild_id=guild_id)
    if not slap_sounds:
        logger(
            f"[Playback Queue] Error: No slap sounds found for request {request_id}."
        )
        return False

    channel = behavior._audio_service.get_user_voice_channel(guild, playback_user)
    if not channel:
        channel = behavior._audio_service.get_largest_voice_channel(guild)
    if channel is None:
        logger(
            f"[Playback Queue] Error: No voice channel available for slap request {request_id}."
        )
        return False

    random_slap = random.choice(slap_sounds)
    try:
        await behavior._audio_service.play_slap(channel, random_slap[2], playback_user)
    except Exception as exc:
        logger(
            f"[Playback Queue] Error playing web slap for request {request_id}: {exc}"
        )
        if require_slap:
            raise
        return False

    _log_web_control_action(
        action_logger_factory,
        playback_user,
        "play_slap",
        random_slap[0],
        guild_id,
    )
    return True


def _get_web_playback_user(
    request_username: str | None,
    request_user_id: str | None,
) -> str:
    """Return a stable display name for a web-originated queue request."""
    if request_username:
        return request_username
    if request_user_id:
        return f"discord-user-{request_user_id}"
    return "webpage"


def _log_web_control_action(
    action_logger_factory: Callable[[], Any] | None,
    username: str,
    action: str,
    target: Any,
    guild_id: int,
) -> None:
    """Log a processed web control action when an action repository is available."""
    if action_logger_factory is None:
        return

    action_logger = action_logger_factory()
    if hasattr(action_logger, "insert"):
        action_logger.insert(username, action, target, guild_id=guild_id)
    else:
        action_logger.insert_action(username, action, target, guild_id=guild_id)
