"""
Repository for speech training clip metadata.

All public methods have docstrings.
Extends BaseRepository for shared connection and standard CRUD helpers.
"""

from typing import Any, Dict, List, Optional, Tuple

from bot.models.speech_training import SpeechTrainingClip
from bot.repositories.base import BaseRepository

# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

_SPEECH_TRAINING_SCHEMA = """
CREATE TABLE IF NOT EXISTS speech_training_clips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id TEXT,
    user_id TEXT NOT NULL,
    username TEXT NOT NULL,
    display_name TEXT,
    folder_name TEXT NOT NULL,
    filename TEXT NOT NULL,
    relative_path TEXT NOT NULL UNIQUE,
    duration_seconds REAL NOT NULL,
    byte_size INTEGER NOT NULL DEFAULT 0,
    sample_rate INTEGER NOT NULL DEFAULT 48000,
    channels INTEGER NOT NULL DEFAULT 2,
    sample_width INTEGER NOT NULL DEFAULT 2,
    captured_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    label TEXT,
    transcript TEXT,
    notes TEXT,
    reviewed_by_user_id TEXT,
    reviewed_by_username TEXT,
    reviewed_at DATETIME
)
"""

_SPEECH_TRAINING_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_st_clips_guild_user_captured "
    "ON speech_training_clips(guild_id, user_id, captured_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_st_clips_guild_label_captured "
    "ON speech_training_clips(guild_id, label, captured_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_st_clips_captured_at "
    "ON speech_training_clips(captured_at DESC)",
]


class SpeechTrainingRepository(BaseRepository):
    """Repository for speech training clip CRUD."""

    # ------------------------------------------------------------------
    # Schema helpers
    # ------------------------------------------------------------------

    def ensure_schema(self) -> None:
        """Create the speech_training_clips table and indexes if they do not exist.

        Uses a single connection for the DDL batch so that indexes are
        created on the same database connection as the table (important
        for in-memory databases in tests).
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(_SPEECH_TRAINING_SCHEMA)
            for idx_sql in _SPEECH_TRAINING_INDEXES:
                cursor.execute(idx_sql)
            conn.commit()
        finally:
            if not self._use_shared or BaseRepository._shared_connection is None:
                conn.close()

    # ------------------------------------------------------------------
    # Insert
    # ------------------------------------------------------------------

    def insert_clip(
        self,
        guild_id: Optional[str],
        user_id: str,
        username: str,
        display_name: Optional[str],
        folder_name: str,
        filename: str,
        relative_path: str,
        duration_seconds: float,
        byte_size: int,
        sample_rate: int = 48000,
        channels: int = 2,
        sample_width: int = 2,
    ) -> int:
        """Insert a new speech training clip record.

        Args:
            guild_id: Discord guild ID, or None.
            user_id: Discord user ID.
            username: Discord username.
            display_name: Display name (nickname), or None.
            folder_name: Directory name under the training data root.
            filename: Base filename (e.g. ``2026-05-24T18-20-30Z_1234ms.mp3``).
            relative_path: Path relative to the training data root.
            duration_seconds: Clip duration.
            byte_size: File size in bytes.
            sample_rate: Audio sample rate (default 48000).
            channels: Number of channels (default 2).
            sample_width: Sample width in bytes (default 2).

        Returns:
            The new row ID.
        """
        return self._execute_write(
            """
            INSERT INTO speech_training_clips
                (guild_id, user_id, username, display_name, folder_name,
                 filename, relative_path, duration_seconds, byte_size,
                 sample_rate, channels, sample_width)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                user_id,
                username,
                display_name,
                folder_name,
                filename,
                relative_path,
                duration_seconds,
                byte_size,
                sample_rate,
                channels,
                sample_width,
            ),
        )

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def list_users(self, guild_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return per-user aggregation for the labeling UI.

        Each entry contains user_id, username, display_name, folder_name,
        total_count, unlabeled_count, and latest_captured_at.

        Args:
            guild_id: Optional guild filter.

        Returns:
            List of dicts with user aggregation.
        """
        if guild_id:
            rows = self._execute(
                """
                SELECT
                    user_id,
                    username,
                    display_name,
                    folder_name,
                    COUNT(*) AS total_count,
                    SUM(CASE WHEN label IS NULL OR label = '' THEN 1 ELSE 0 END) AS unlabeled_count,
                    MAX(captured_at) AS latest_captured_at
                FROM speech_training_clips
                WHERE guild_id = ?
                GROUP BY user_id, username, display_name, folder_name
                ORDER BY MAX(captured_at) DESC
                """,
                (guild_id,),
            )
        else:
            rows = self._execute(
                """
                SELECT
                    user_id,
                    username,
                    display_name,
                    folder_name,
                    COUNT(*) AS total_count,
                    SUM(CASE WHEN label IS NULL OR label = '' THEN 1 ELSE 0 END) AS unlabeled_count,
                    MAX(captured_at) AS latest_captured_at
                FROM speech_training_clips
                GROUP BY user_id, username, display_name, folder_name
                ORDER BY MAX(captured_at) DESC
                """
            )
        return [dict(r) for r in rows]

    _SORT_ALLOWLIST: set[str] = {
        "captured_at",
        "duration_seconds",
        "username",
        "label",
        "reviewed_at",
    }
    _SORT_DIR_ALLOWLIST: set[str] = {"asc", "desc"}

    # ------------------------------------------------------------------
    # Filter / order helpers (shared by list_clips and list_clip_ids)
    # ------------------------------------------------------------------

    def _build_clip_conditions(
        self,
        guild_id: Optional[str] = None,
        user_id: Optional[str] = None,
        label: Optional[str] = None,
        search: str = "",
    ) -> Tuple[List[str], List[Any]]:
        """Build WHERE conditions and params for clip queries.

        Args:
            guild_id: Optional guild filter.
            user_id: Optional user filter.
            label: Optional label filter (``"unlabeled"`` for NULL/empty).
            search: Optional search in username/display_name/filename.

        Returns:
            Tuple of (list of condition strings, list of parameter values).
        """
        conditions: List[str] = []
        params: List[Any] = []

        if guild_id:
            conditions.append("guild_id = ?")
            params.append(guild_id)
        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        if label == "unlabeled":
            conditions.append("(label IS NULL OR label = '')")
        elif label:
            conditions.append("label = ?")
            params.append(label)
        if search:
            conditions.append(
                "(username LIKE ? OR display_name LIKE ? OR filename LIKE ?)"
            )
            like_val = f"%{search}%"
            params.extend([like_val, like_val, like_val])

        return conditions, params

    def _build_clip_order(
        self, sort_by: str = "captured_at", sort_dir: str = "desc"
    ) -> str:
        """Build ORDER BY clause for clip queries.

        Args:
            sort_by: Column to sort by (allowlisted). Default ``captured_at``.
            sort_dir: Sort direction (``asc`` or ``desc``). Default ``desc``.

        Returns:
            Full ORDER BY clause string including the deterministic tiebreaker.
        """
        safe_sort = sort_by if sort_by in self._SORT_ALLOWLIST else "captured_at"
        safe_dir = sort_dir.lower() if sort_dir.lower() in self._SORT_DIR_ALLOWLIST else "desc"
        # For label sorts, treat NULL/empty as a group
        # With asc: labeled (CASE 0) first; with desc: unlabeled (CASE 0) first
        if safe_sort == "label":
            if safe_dir == "asc":
                order_expr = "CASE WHEN label IS NULL OR label = '' THEN 1 ELSE 0 END, label asc"
            else:
                order_expr = "CASE WHEN label IS NULL OR label = '' THEN 0 ELSE 1 END, label desc"
        else:
            order_expr = f"{safe_sort} {safe_dir}"
        # Deterministic tiebreaker
        return f"ORDER BY {order_expr}, id {safe_dir}"

    def list_clips(
        self,
        guild_id: Optional[str] = None,
        user_id: Optional[str] = None,
        label: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
        search: str = "",
        sort_by: str = "captured_at",
        sort_dir: str = "desc",
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Return a paginated list of clips and total count.

        Args:
            guild_id: Optional guild filter.
            user_id: Optional user filter.
            label: Optional label filter (``"unlabeled"`` for NULL/empty).
            page: 1-indexed page number.
            per_page: Items per page.
            search: Optional search in username/display_name/filename.
            sort_by: Column to sort by (allowlisted). Default ``captured_at``.
            sort_dir: Sort direction (``asc`` or ``desc``). Default ``desc``.

        Returns:
            Tuple of (list of clip dicts, total count).
        """
        conditions, params = self._build_clip_conditions(
            guild_id=guild_id, user_id=user_id, label=label, search=search
        )

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        count_row = self._execute_one(
            f"SELECT COUNT(*) AS cnt FROM speech_training_clips {where_clause}",
            tuple(params),
        )
        total = count_row["cnt"] if count_row else 0

        order_clause = self._build_clip_order(sort_by=sort_by, sort_dir=sort_dir)

        offset = (page - 1) * per_page
        rows = self._execute(
            f"""
            SELECT * FROM speech_training_clips
            {where_clause}
            {order_clause}
            LIMIT ? OFFSET ?
            """,
            tuple(params) + (per_page, offset),
        )
        return [dict(r) for r in rows], total

    def list_clip_ids(
        self,
        guild_id: Optional[str] = None,
        user_id: Optional[str] = None,
        label: Optional[str] = None,
        search: str = "",
        sort_by: str = "captured_at",
        sort_dir: str = "desc",
    ) -> List[int]:
        """Return IDs of all clips matching the given filters, without pagination.

        Args:
            guild_id: Optional guild filter.
            user_id: Optional user filter.
            label: Optional label filter (``"unlabeled"`` for NULL/empty).
            search: Optional search in username/display_name/filename.
            sort_by: Column to sort by (allowlisted). Default ``captured_at``.
            sort_dir: Sort direction (``asc`` or ``desc``). Default ``desc``.

        Returns:
            List of clip IDs (integers).
        """
        conditions, params = self._build_clip_conditions(
            guild_id=guild_id, user_id=user_id, label=label, search=search
        )
        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)
        order_clause = self._build_clip_order(sort_by=sort_by, sort_dir=sort_dir)

        rows = self._execute(
            f"SELECT id FROM speech_training_clips {where_clause} {order_clause}",
            tuple(params),
        )
        return [r["id"] for r in rows]

    def list_unlabeled_clips(
        self,
        guild_id: Optional[str] = None,
        user_id: Optional[str] = None,
        max_duration_seconds: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Return all clips with label IS NULL or empty, optionally scoped.

        Args:
            guild_id: Optional guild filter.
            user_id: Optional user filter.
            max_duration_seconds: Optional maximum duration filter (inclusive).

        Returns:
            List of clip dicts ordered by ``captured_at DESC, id DESC``.
        """
        conditions: List[str] = ["(label IS NULL OR label = '')"]
        params: List[Any] = []

        if guild_id:
            conditions.append("guild_id = ?")
            params.append(guild_id)
        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        if max_duration_seconds is not None:
            conditions.append("duration_seconds <= ?")
            params.append(max_duration_seconds)

        sql = "SELECT * FROM speech_training_clips"
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY captured_at DESC, id DESC"
        rows = self._execute(sql, tuple(params))
        return [dict(r) for r in rows]

    def get_clip(self, clip_id: int) -> Optional[Dict[str, Any]]:
        """Return a single clip by ID.

        Args:
            clip_id: Clip primary key.

        Returns:
            Dict of the clip row, or None.
        """
        row = self._execute_one(
            "SELECT * FROM speech_training_clips WHERE id = ?", (clip_id,)
        )
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # Updates
    # ------------------------------------------------------------------

    def update_review(
        self,
        clip_id: int,
        label: Optional[str],
        transcript: Optional[str],
        notes: Optional[str],
        reviewer_user_id: str,
        reviewer_username: str,
    ) -> bool:
        """Update a clip's label, transcript, notes, and reviewer metadata.

        Uses a direct connection to reliably check ``cursor.rowcount``
        because ``_execute_write`` returns ``lastrowid`` which is
        unreliable for UPDATE statements.

        Args:
            clip_id: Clip primary key.
            label: New label (e.g. ``"chapada"``, ``"ventura"``, ``"none"``, or None/empty).
            transcript: Optional human transcript.
            notes: Optional reviewer notes.
            reviewer_user_id: Discord user ID of the reviewer.
            reviewer_username: Discord username of the reviewer.

        Returns:
            True if the clip was updated.
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE speech_training_clips
                SET label = ?,
                    transcript = ?,
                    notes = ?,
                    reviewed_by_user_id = ?,
                    reviewed_by_username = ?,
                    reviewed_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    label if label else None,
                    transcript if transcript else None,
                    notes if notes else None,
                    reviewer_user_id,
                    reviewer_username,
                    clip_id,
                ),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            if not self._use_shared or BaseRepository._shared_connection is None:
                conn.close()

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete_clip(self, clip_id: int) -> Optional[Dict[str, Any]]:
        """Delete a clip and return its row metadata, or None if not found.

        The returned dict includes ``relative_path`` so the caller can
        remove the audio file.

        Args:
            clip_id: Clip primary key.

        Returns:
            Dict of the deleted row, or None.
        """
        clip = self.get_clip(clip_id)
        if clip is None:
            return None
        self._execute_write(
            "DELETE FROM speech_training_clips WHERE id = ?",
            (clip_id,),
        )
        return clip

    # ------------------------------------------------------------------
    # Bulk operations
    # ------------------------------------------------------------------

    def bulk_update_review(
        self,
        clip_ids: list[int],
        label: Optional[str],
        reviewer_user_id: str,
        reviewer_username: str,
    ) -> int:
        """Update label and reviewer metadata for multiple clips.

        Args:
            clip_ids: List of clip primary keys.
            label: New label value (or None to clear).
            reviewer_user_id: Discord user ID of the reviewer.
            reviewer_username: Discord username.

        Returns:
            Number of rows updated.
        """
        if not clip_ids:
            return 0
        placeholders = ",".join("?" for _ in clip_ids)
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                f"""
                UPDATE speech_training_clips
                SET label = ?,
                    reviewed_by_user_id = ?,
                    reviewed_by_username = ?,
                    reviewed_at = CURRENT_TIMESTAMP
                WHERE id IN ({placeholders})
                """,
                (
                    label if label else None,
                    reviewer_user_id,
                    reviewer_username,
                    *clip_ids,
                ),
            )
            conn.commit()
            return cursor.rowcount
        finally:
            if not self._use_shared or BaseRepository._shared_connection is None:
                conn.close()

    def bulk_delete_clips(
        self, clip_ids: list[int]
    ) -> List[Dict[str, Any]]:
        """Delete multiple clips and return their pre-deletion row metadata.

        Args:
            clip_ids: List of clip primary keys.

        Returns:
            List of deleted clip dicts (each includes ``relative_path``).
        """
        if not clip_ids:
            return []

        placeholders = ",".join("?" for _ in clip_ids)
        # Fetch rows before deleting
        rows = self._execute(
            f"SELECT * FROM speech_training_clips WHERE id IN ({placeholders})",
            tuple(clip_ids),
        )
        clips = [dict(r) for r in rows]
        if not clips:
            return []

        self._execute_write(
            f"DELETE FROM speech_training_clips WHERE id IN ({placeholders})",
            tuple(clip_ids),
        )
        return clips

    # ------------------------------------------------------------------
    # Storage summary
    # ------------------------------------------------------------------

    def get_storage_summary(
        self, guild_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Return total MP3 storage used and clip count, optionally scoped to a guild.

        Args:
            guild_id: Optional guild filter.

        Returns:
            Dict with ``total_bytes`` (int) and ``clip_count`` (int).
        """
        if guild_id:
            row = self._execute_one(
                """
                SELECT COALESCE(SUM(byte_size), 0) AS total_bytes,
                       COUNT(*) AS clip_count
                FROM speech_training_clips
                WHERE guild_id = ?
                """,
                (guild_id,),
            )
        else:
            row = self._execute_one(
                """
                SELECT COALESCE(SUM(byte_size), 0) AS total_bytes,
                       COUNT(*) AS clip_count
                FROM speech_training_clips
                """
            )
        if row is None:
            return {"total_bytes": 0, "clip_count": 0}
        return {"total_bytes": row["total_bytes"], "clip_count": row["clip_count"]}

    # ------------------------------------------------------------------
    # BaseRepository abstract methods
    # ------------------------------------------------------------------

    def get_by_id(self, id: int):
        """Return a SpeechTrainingClip model by ID."""
        row = self._execute_one(
            "SELECT * FROM speech_training_clips WHERE id = ?", (id,)
        )
        return self._row_to_entity(row) if row else None

    def get_all(self, limit: int = 100):
        """Return all clips up to limit."""
        rows = self._execute(
            "SELECT * FROM speech_training_clips ORDER BY captured_at DESC LIMIT ?",
            (limit,),
        )
        return [self._row_to_entity(r) for r in rows]

    def _row_to_entity(self, row) -> SpeechTrainingClip:
        """Convert a database row to a SpeechTrainingClip dataclass."""
        return SpeechTrainingClip(
            id=row["id"],
            guild_id=row["guild_id"],
            user_id=row["user_id"],
            username=row["username"],
            display_name=row["display_name"],
            folder_name=row["folder_name"],
            filename=row["filename"],
            relative_path=row["relative_path"],
            duration_seconds=row["duration_seconds"],
            byte_size=row["byte_size"],
            sample_rate=row["sample_rate"],
            channels=row["channels"],
            sample_width=row["sample_width"],
            captured_at=row["captured_at"],
            label=row["label"],
            transcript=row["transcript"],
            notes=row["notes"],
            reviewed_by_user_id=row["reviewed_by_user_id"],
            reviewed_by_username=row["reviewed_by_username"],
            reviewed_at=row["reviewed_at"],
        )
