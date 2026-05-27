"""
Repository for persistent web upload job state.

Provides a durable table for tracking background web upload job status
so that upload progress survives Flask process restarts.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import sqlite3

from bot.repositories.base import BaseRepository


class WebUploadJobRepository(BaseRepository[dict[str, Any]]):
    """
    Persist web upload job metadata across Flask process restarts.

    Table columns:
        job_id (TEXT PRIMARY KEY): UUID hex string.
        status (TEXT): queued, processing, approved, error.
        guild_id (TEXT): Target guild ID.
        temp_upload_path (TEXT): Path to the temp uploaded file, if any.
        original_filename (TEXT): Original user-facing filename.
        current_user_json (TEXT): JSON-serialized DiscordWebUser session payload.
        custom_name (TEXT): User-requested custom filename.
        source_url (TEXT): Video/MP3 URL source, if any.
        time_limit (INTEGER): Optional trim limit in seconds.
        result_json (TEXT): JSON result payload on success.
        error (TEXT): Error message on failure.
        attempts (INTEGER): Number of processing attempts.
        created_at (TEXT): ISO 8601 UTC.
        started_at (TEXT): ISO 8601 UTC when processing started.
        finished_at (TEXT): ISO 8601 UTC when processing ended.
        updated_at (TEXT): ISO 8601 UTC when status last changed.
    """

    def __init__(self, db_path: str | None = None, use_shared: bool = False):
        super().__init__(db_path=db_path, use_shared=use_shared)
        self.ensure_schema()

    def _row_to_entity(self, row: sqlite3.Row) -> dict[str, Any]:
        return dict(row)

    def ensure_schema(self) -> None:
        """Create the web_upload_jobs table when needed."""
        self._execute_write(
            """
            CREATE TABLE IF NOT EXISTS web_upload_jobs (
                job_id TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'queued',
                guild_id TEXT,
                temp_upload_path TEXT,
                original_filename TEXT,
                current_user_json TEXT,
                custom_name TEXT,
                source_url TEXT,
                time_limit INTEGER,
                result_json TEXT,
                error TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )

    def get_by_id(self, job_id: str) -> dict[str, Any] | None:
        """Return one upload job by job_id."""
        row = self._execute_one(
            "SELECT * FROM web_upload_jobs WHERE job_id = ?", (job_id,)
        )
        return self._row_to_entity(row) if row else None

    def get_all(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return recent upload jobs."""
        rows = self._execute(
            "SELECT * FROM web_upload_jobs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [self._row_to_entity(row) for row in rows]

    def create_job(
        self,
        *,
        job_id: str,
        guild_id: int | None = None,
        temp_upload_path: str | None = None,
        original_filename: str | None = None,
        current_user_json: str | None = None,
        custom_name: str | None = None,
        source_url: str | None = None,
        time_limit: int | None = None,
    ) -> None:
        """
        Insert a new queued upload job.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        self._execute_write(
            """
            INSERT INTO web_upload_jobs (
                job_id, status, guild_id, temp_upload_path,
                original_filename, current_user_json, custom_name,
                source_url, time_limit,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                "queued",
                str(guild_id) if guild_id is not None else None,
                temp_upload_path,
                original_filename,
                current_user_json,
                custom_name,
                source_url,
                time_limit,
                now_iso,
                now_iso,
            ),
        )

    def update_status(
        self,
        job_id: str,
        *,
        status: str,
        result_json: str | None = None,
        error: str | None = None,
        attempts: int | None = None,
    ) -> None:
        """
        Update the status and optional result/error for a job.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        fields = ["status = ?", "updated_at = ?"]
        params: list[Any] = [status, now_iso]

        if result_json is not None:
            fields.append("result_json = ?")
            params.append(result_json)
        if error is not None:
            fields.append("error = ?")
            params.append(error)
        if attempts is not None:
            fields.append("attempts = ?")
            params.append(attempts)

        # Set started_at when first entering processing from queued.
        fields.append(
            "started_at = COALESCE(started_at, ?)"
        )
        params.append(now_iso)

        # Set finished_at when entering a terminal status.
        if status in ("approved", "error"):
            fields.append("finished_at = COALESCE(finished_at, ?)")
            params.append(now_iso)

        params.append(job_id)
        self._execute_write(
            f"UPDATE web_upload_jobs SET {', '.join(fields)} WHERE job_id = ?",
            tuple(params),
        )

    def get_recoverable_jobs(
        self,
        max_attempts: int = 3,
        stale_seconds: int = 300,
    ) -> list[dict[str, Any]]:
        """
        Return jobs in 'queued' status or stale 'processing' jobs.

        Args:
            max_attempts: Maximum attempts before giving up.
            stale_seconds: Age in seconds after which a 'processing' job
                is considered stale and eligible for recovery.

        Returns:
            List of job dicts ready for re-submission.
        """
        rows = self._execute(
            """
            SELECT * FROM web_upload_jobs
            WHERE (
                status = 'queued'
                OR (
                    status = 'processing'
                    AND updated_at < datetime('now', ? || ' seconds')
                )
            )
            AND attempts < ?
            ORDER BY created_at ASC
            """,
            (f"-{stale_seconds}", max_attempts),
        )
        return [self._row_to_entity(row) for row in rows]
