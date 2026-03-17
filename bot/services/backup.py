import asyncio
import contextlib
import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from config import BACKUP_DIR, BACKUP_EXCLUSIONS, PROJECT_ROOT

logger = logging.getLogger(__name__)


@dataclass
class BackupScanStats:
    """Precomputed stats for the files that will be included in a backup."""

    total_bytes: int = 0
    total_entries: int = 1
    file_sizes: dict[str, int] = field(default_factory=dict)


@dataclass
class BackupProgress:
    """Mutable progress state for a running archive creation job."""

    processed_bytes: int = 0
    processed_entries: int = 0
    latest_entry: str = ""
    finished: bool = False


class BackupService:
    """
    Service for backing up the bot's data and codebase.
    """

    def __init__(self, bot, message_service):
        self.bot = bot
        self.message_service = message_service
        self.backup_dir = BACKUP_DIR
        self.project_root = PROJECT_ROOT
        self.exclusions = BACKUP_EXCLUSIONS
        self.progress_update_interval_seconds = 2.0

    async def perform_backup(self, interaction):
        """
        Perform a full project backup and keep the user updated as it progresses.

        Args:
            interaction: Discord application context/interaction for the `/backup` command.
        """
        started_at = time.monotonic()
        await self._set_status_message(
            interaction,
            self._build_stage_message(
                step=1,
                total_steps=5,
                status="Preparing backup directory",
            ),
        )

        try:
            self.backup_dir.mkdir(parents=True, exist_ok=True)

            await self._set_status_message(
                interaction,
                self._build_stage_message(
                    step=2,
                    total_steps=5,
                    status="Scanning files and estimating backup size",
                ),
            )
            scan_stats = await asyncio.to_thread(
                self._scan_backup_contents, self.project_root, self.exclusions
            )

            _total, _used, free = shutil.disk_usage(self.backup_dir.parent)
            await self._set_status_message(
                interaction,
                self._build_stage_message(
                    step=3,
                    total_steps=5,
                    status="Checking free disk space",
                    details=[
                        f"Estimated source size: {self._format_bytes(scan_stats.total_bytes)}",
                        f"Free space at backup destination: {self._format_bytes(free)}",
                    ],
                ),
            )

            required_free_bytes = int(scan_stats.total_bytes * 1.2)
            if free < required_free_bytes:
                await self._set_status_message(
                    interaction,
                    "\n".join(
                        [
                            "❌ **Backup failed**",
                            "Not enough disk space to create a safe backup.",
                            f"Free: {self._format_bytes(free)}",
                            f"Needed (approx): {self._format_bytes(required_free_bytes)}",
                        ]
                    ),
                )
                return

            existing_backups = list(self.backup_dir.glob("*.tar.gz"))
            await self._set_status_message(
                interaction,
                self._build_stage_message(
                    step=4,
                    total_steps=5,
                    status="Removing previous backup archives",
                    details=[f"Found {len(existing_backups)} previous backup(s)."],
                ),
            )
            for old_backup in existing_backups:
                try:
                    old_backup.unlink()
                    logger.info("Deleted old backup: %s", old_backup)
                except Exception as exc:
                    logger.error("Failed to delete old backup %s: %s", old_backup, exc)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_filename = f"backup_{timestamp}.tar.gz"
            backup_path = self.backup_dir / backup_filename

            await self._set_status_message(
                interaction,
                self._build_stage_message(
                    step=5,
                    total_steps=5,
                    status="Creating compressed archive",
                    details=[
                        f"Target file: `{backup_filename}`",
                        f"Entries to archive: {scan_stats.total_entries:,}",
                        f"Estimated source size: {self._format_bytes(scan_stats.total_bytes)}",
                    ],
                ),
            )

            return_code, stderr_output = await self._create_archive_with_progress(
                interaction=interaction,
                backup_path=backup_path,
                backup_filename=backup_filename,
                scan_stats=scan_stats,
                started_at=started_at,
            )

            if return_code == 0:
                size_mb = backup_path.stat().st_size / (1024 * 1024)
                await self._set_status_message(
                    interaction,
                    "\n".join(
                        [
                            "✅ **Backup successful!**",
                            f"`{backup_filename}` created ({size_mb:.2f} MB).",
                            f"Elapsed: {self._format_duration(time.monotonic() - started_at)}",
                        ]
                    ),
                )
                logger.info("Backup created successfully: %s", backup_path)
                return

            truncated_error = self._truncate_text(stderr_output.strip() or "tar exited without stderr output.")
            await self._set_status_message(
                interaction,
                "\n".join(
                    [
                        "❌ **Backup failed**",
                        f"tar exited with code {return_code}.",
                        f"```{truncated_error}```",
                    ]
                ),
            )
            logger.error("Backup failed with return code %s: %s", return_code, stderr_output)

        except Exception as exc:
            logger.error("Unexpected error during backup: %s", exc)
            await self._set_status_message(
                interaction,
                f"❌ **An unexpected error occurred:** {self._truncate_text(str(exc))}",
            )

    async def _create_archive_with_progress(
        self,
        interaction,
        backup_path: Path,
        backup_filename: str,
        scan_stats: BackupScanStats,
        started_at: float,
    ) -> tuple[int, str]:
        """Run tar and keep the original Discord response updated with progress."""
        exclude_args = []
        for exclusion in self.exclusions:
            exclude_args.extend(["--exclude", exclusion])

        command = [
            "tar",
            "-czvf",
            str(backup_path),
            *exclude_args,
            "-C",
            str(self.project_root.parent),
            self.project_root.name,
        ]

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        progress = BackupProgress()
        monitor_task = asyncio.create_task(
            self._monitor_archive_progress(
                interaction=interaction,
                backup_path=backup_path,
                backup_filename=backup_filename,
                scan_stats=scan_stats,
                progress=progress,
                started_at=started_at,
            )
        )

        try:
            while True:
                line = await process.stdout.readline()
                if not line:
                    break

                archive_entry = line.decode("utf-8", errors="replace").strip()
                normalized_entry = archive_entry.rstrip("/")
                progress.latest_entry = normalized_entry
                progress.processed_entries += 1
                progress.processed_bytes += scan_stats.file_sizes.get(normalized_entry, 0)

            stderr_output = (await process.stderr.read()).decode("utf-8", errors="replace")
            return_code = await process.wait()
            return return_code, stderr_output
        finally:
            progress.finished = True
            monitor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await monitor_task

    async def _monitor_archive_progress(
        self,
        interaction,
        backup_path: Path,
        backup_filename: str,
        scan_stats: BackupScanStats,
        progress: BackupProgress,
        started_at: float,
    ) -> None:
        """Periodically edit the backup status message while tar is running."""
        last_message = None
        while not progress.finished:
            archive_size = backup_path.stat().st_size if backup_path.exists() else 0
            message = self._build_archive_progress_message(
                backup_filename=backup_filename,
                scan_stats=scan_stats,
                progress=progress,
                archive_size=archive_size,
                elapsed_seconds=time.monotonic() - started_at,
            )
            if message != last_message:
                await self._set_status_message(interaction, message)
                last_message = message
            await asyncio.sleep(self.progress_update_interval_seconds)

    async def _set_status_message(self, interaction, content: str) -> None:
        """Send or edit the backup status message for the current interaction."""
        discord_interaction = getattr(interaction, "interaction", interaction)

        try:
            if not discord_interaction.response.is_done():
                await discord_interaction.response.send_message(content, ephemeral=True)
            else:
                await discord_interaction.edit_original_response(content=content)
        except Exception as exc:
            logger.warning("Failed to update backup status message: %s", exc)
            if discord_interaction.response.is_done():
                try:
                    await discord_interaction.followup.send(content, ephemeral=True)
                except Exception as followup_exc:
                    logger.warning("Failed to send backup followup status message: %s", followup_exc)

    def _scan_backup_contents(self, path: Path, exclusions) -> BackupScanStats:
        """Collect file sizes and entry counts for the paths included in the backup."""
        stats = BackupScanStats()
        excluded_names = set(exclusions)

        for dirpath, dirnames, filenames in os.walk(path):
            dirnames[:] = [dirname for dirname in dirnames if dirname not in excluded_names]
            stats.total_entries += len(dirnames)

            for filename in filenames:
                file_path = Path(dirpath) / filename
                if file_path.is_symlink():
                    continue

                try:
                    size = file_path.stat().st_size
                except OSError as exc:
                    logger.warning("Skipping unreadable file during backup scan %s: %s", file_path, exc)
                    continue

                archive_path = f"{self.project_root.name}/{file_path.relative_to(path).as_posix()}"
                stats.file_sizes[archive_path] = size
                stats.total_bytes += size
                stats.total_entries += 1

        return stats

    def _build_stage_message(
        self,
        step: int,
        total_steps: int,
        status: str,
        details: list[str] | None = None,
    ) -> str:
        """Create a stage/status message for non-archiving steps."""
        detail_lines = details or []
        lines = [
            "🚀 **Backup in progress**",
            f"`[{self._render_progress_bar(step / total_steps)}] Step {step}/{total_steps}`",
            f"**Status:** {status}",
        ]
        lines.extend(detail_lines)
        return "\n".join(lines)

    def _build_archive_progress_message(
        self,
        backup_filename: str,
        scan_stats: BackupScanStats,
        progress: BackupProgress,
        archive_size: int,
        elapsed_seconds: float,
    ) -> str:
        """Create the live archive progress message shown while tar is running."""
        if scan_stats.total_bytes > 0:
            ratio = min(progress.processed_bytes / scan_stats.total_bytes, 0.995)
        elif scan_stats.total_entries > 0:
            ratio = min(progress.processed_entries / scan_stats.total_entries, 0.995)
        else:
            ratio = 0.0

        latest_entry = self._truncate_text(progress.latest_entry or "Starting archive stream...", 80)
        lines = [
            "🚀 **Backup in progress**",
            f"`[{self._render_progress_bar(ratio)}] {ratio * 100:5.1f}%`",
            "**Status:** Creating compressed archive",
            f"Target file: `{backup_filename}`",
            f"Processed source data: {self._format_bytes(progress.processed_bytes)} / {self._format_bytes(scan_stats.total_bytes)}",
            f"Processed entries: {progress.processed_entries:,} / {scan_stats.total_entries:,}",
            f"Compressed archive size: {self._format_bytes(archive_size)}",
            f"Latest entry: `{latest_entry}`",
            f"Elapsed: {self._format_duration(elapsed_seconds)}",
        ]
        return "\n".join(lines)

    def _render_progress_bar(self, ratio: float, width: int = 16) -> str:
        """Render a small ASCII progress bar."""
        bounded_ratio = max(0.0, min(ratio, 1.0))
        filled = int(width * bounded_ratio)
        return f"{'#' * filled}{'-' * (width - filled)}"

    def _format_bytes(self, value: int) -> str:
        """Format a byte count into a compact human-readable string."""
        if value <= 0:
            return "0 B"

        units = ["B", "KB", "MB", "GB", "TB"]
        size = float(value)
        for unit in units:
            if size < 1024 or unit == units[-1]:
                if unit == "B":
                    return f"{int(size)} {unit}"
                return f"{size:.2f} {unit}"
            size /= 1024

        return f"{size:.2f} TB"

    def _format_duration(self, elapsed_seconds: float) -> str:
        """Format an elapsed duration into minutes/seconds."""
        total_seconds = max(0, int(elapsed_seconds))
        minutes, seconds = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)

        if hours:
            return f"{hours}h {minutes}m {seconds}s"
        if minutes:
            return f"{minutes}m {seconds}s"
        return f"{seconds}s"

    def _truncate_text(self, text: str, max_length: int = 1200) -> str:
        """Trim long text so status/error messages stay within Discord limits."""
        if len(text) <= max_length:
            return text
        return f"{text[: max_length - 3]}..."
