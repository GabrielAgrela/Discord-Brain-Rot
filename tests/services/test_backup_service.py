"""
Tests for bot/services/backup.py - BackupService.
"""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class FakeResponse:
    """Small helper that mimics Discord's interaction response lifecycle."""

    def __init__(self):
        self._done = False
        self.send_message = AsyncMock(side_effect=self._send_message)

    async def _send_message(self, *_args, **_kwargs):
        self._done = True

    def is_done(self):
        return self._done


class FakeStream:
    """Async stream helper for fake subprocess stdout/stderr."""

    def __init__(self, lines=None, payload=b""):
        self._lines = list(lines or [])
        self._payload = payload

    async def readline(self):
        if self._lines:
            return self._lines.pop(0)
        return b""

    async def read(self):
        return self._payload


class FakeProcess:
    """Small fake subprocess object for tar execution tests."""

    def __init__(self, *, stdout_lines=None, stderr=b"", returncode=0):
        self.stdout = FakeStream(lines=stdout_lines)
        self.stderr = FakeStream(payload=stderr)
        self.returncode = returncode

    async def wait(self):
        return self.returncode


class TestBackupService:
    """Tests for the BackupService class."""

    @pytest.fixture
    def backup_service(self):
        """Create a BackupService with mocked dependencies."""
        from bot.services.backup import BackupService

        return BackupService(bot=Mock(), message_service=Mock())

    @pytest.fixture
    def fake_context(self):
        """Create a fake slash-command context with editable original response support."""
        interaction = Mock()
        interaction.response = FakeResponse()
        interaction.edit_original_response = AsyncMock()
        interaction.followup = Mock()
        interaction.followup.send = AsyncMock()

        ctx = Mock()
        ctx.interaction = interaction
        return ctx

    def test_scan_backup_contents_excludes_directories_and_tracks_archive_paths(self, backup_service, tmp_path):
        """Backup scans should ignore excluded directories and keep tar-relative file paths."""
        project_root = tmp_path / "Discord-Brain-Rot"
        project_root.mkdir()
        (project_root / "keep").mkdir()
        (project_root / "skipme").mkdir()
        (project_root / "root.txt").write_text("root-data", encoding="utf-8")
        (project_root / "keep" / "nested.txt").write_text("nested-data", encoding="utf-8")
        (project_root / "skipme" / "ignored.txt").write_text("ignored-data", encoding="utf-8")

        backup_service.project_root = project_root

        stats = backup_service._scan_backup_contents(project_root, ["skipme"])

        expected_size = (
            (project_root / "root.txt").stat().st_size
            + (project_root / "keep" / "nested.txt").stat().st_size
        )
        assert stats.total_bytes == expected_size
        assert stats.total_entries == 4
        assert stats.file_sizes == {
            "Discord-Brain-Rot/root.txt": (project_root / "root.txt").stat().st_size,
            "Discord-Brain-Rot/keep/nested.txt": (project_root / "keep" / "nested.txt").stat().st_size,
        }

    def test_scan_backup_contents_default_includes_all_when_no_exclusions(self, backup_service, tmp_path):
        """With empty exclusions, all directories and files are included in the scan."""
        project_root = tmp_path / "Discord-Brain-Rot"
        project_root.mkdir()
        # Create directories that were previously excluded by default
        (project_root / "venv").mkdir()
        (project_root / ".git").mkdir()
        (project_root / "__pycache__").mkdir()
        (project_root / "Logs").mkdir()
        (project_root / "Downloads").mkdir()
        (project_root / ".gemini").mkdir()
        # Regular file and file inside a previously-excluded dir
        (project_root / "keep_me.py").write_text("code", encoding="utf-8")
        (project_root / "venv" / "lib.py").write_text("lib", encoding="utf-8")

        backup_service.project_root = project_root
        stats = backup_service._scan_backup_contents(project_root, [])

        # Root dir (1) + 6 subdirs + 2 files = 9 entries
        assert stats.total_entries == 9, f"Expected 9 entries, got {stats.total_entries}"
        assert "Discord-Brain-Rot/venv/lib.py" in stats.file_sizes
        assert "Discord-Brain-Rot/keep_me.py" in stats.file_sizes
        expected_bytes = (
            (project_root / "keep_me.py").lstat().st_size
            + (project_root / "venv" / "lib.py").lstat().st_size
        )
        assert stats.total_bytes == expected_bytes

    def test_scan_backup_contents_includes_symlink_files(self, backup_service, tmp_path):
        """Symlink files should be included in the scan using their own lstat size."""
        project_root = tmp_path / "Discord-Brain-Rot"
        project_root.mkdir()
        (project_root / "real_file.txt").write_text("real-data", encoding="utf-8")

        # Create a file symlink (symlink target path as string)
        link_path = project_root / "link.txt"
        link_path.symlink_to("real_file.txt")

        backup_service.project_root = project_root
        stats = backup_service._scan_backup_contents(project_root, [])

        assert "Discord-Brain-Rot/link.txt" in stats.file_sizes
        assert "Discord-Brain-Rot/real_file.txt" in stats.file_sizes
        expected_bytes = (
            (project_root / "real_file.txt").lstat().st_size
            + link_path.lstat().st_size
        )
        assert stats.total_bytes == expected_bytes
        # Root dir (1) + 2 files = 3 entries
        assert stats.total_entries == 3

    def test_scan_backup_contents_respects_explicit_exclusions_when_provided(self, backup_service, tmp_path):
        """Explicitly provided exclusions should still be respected by the scan."""
        project_root = tmp_path / "Discord-Brain-Rot"
        project_root.mkdir()
        (project_root / "keep").mkdir()
        (project_root / "exclude_me").mkdir()
        (project_root / "root.txt").write_text("root", encoding="utf-8")
        (project_root / "exclude_me" / "ignored.txt").write_text("ignored", encoding="utf-8")

        backup_service.project_root = project_root
        stats = backup_service._scan_backup_contents(project_root, ["exclude_me"])

        assert "Discord-Brain-Rot/exclude_me/ignored.txt" not in stats.file_sizes
        assert "Discord-Brain-Rot/root.txt" in stats.file_sizes
        # Root (1) + 1 subdir (keep) + 1 file (root.txt) = 3 entries
        assert stats.total_entries == 3

    def test_build_archive_progress_message_includes_progress_bar_and_status_details(self, backup_service):
        """Archive progress messages should expose useful live status details."""
        from bot.services.backup import BackupProgress, BackupScanStats

        message = backup_service._build_archive_progress_message(
            backup_filename="backup_20260315_135017.tar.gz",
            scan_stats=BackupScanStats(total_bytes=1024, total_entries=8),
            progress=BackupProgress(
                processed_bytes=512,
                processed_entries=4,
                latest_entry="Discord-Brain-Rot/Sounds/test.mp3",
            ),
            archive_size=128,
            elapsed_seconds=65,
        )

        assert "50.0%" in message
        assert "Processed source data: 512 B / 1.00 KB" in message
        assert "Processed entries: 4 / 8" in message
        assert "Compressed archive size: 128 B" in message
        assert "Elapsed: 1m 5s" in message

    @pytest.mark.asyncio
    async def test_perform_backup_success_updates_status_and_final_message(
        self, backup_service, fake_context, tmp_path
    ):
        """Successful backups should update the original ephemeral status message in place."""
        from bot.services.backup import BackupScanStats

        project_root = tmp_path / "Discord-Brain-Rot"
        project_root.mkdir()
        backup_service.project_root = project_root
        backup_service.backup_dir = tmp_path / "backups"
        backup_service.exclusions = []

        scan_stats = BackupScanStats(
            total_bytes=30,
            total_entries=3,
            file_sizes={
                "Discord-Brain-Rot/file1.txt": 10,
                "Discord-Brain-Rot/file2.txt": 20,
            },
        )

        async def fake_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        async def fake_create_subprocess_exec(*command, **_kwargs):
            backup_path = Path(command[2])
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            backup_path.write_bytes(b"x" * 4096)
            return FakeProcess(
                stdout_lines=[
                    b"Discord-Brain-Rot/file1.txt\n",
                    b"Discord-Brain-Rot/file2.txt\n",
                ],
                stderr=b"",
                returncode=0,
            )

        with patch("bot.services.backup.asyncio.to_thread", new=AsyncMock(side_effect=fake_to_thread)):
            with patch.object(backup_service, "_scan_backup_contents", return_value=scan_stats):
                with patch("bot.services.backup.shutil.disk_usage", return_value=(10, 1, 10_000_000)):
                    with patch("bot.services.backup.asyncio.create_subprocess_exec", side_effect=fake_create_subprocess_exec):
                        with patch.object(backup_service, "_monitor_archive_progress", new=AsyncMock()):
                            await backup_service.perform_backup(fake_context)

        interaction = fake_context.interaction
        interaction.response.send_message.assert_awaited_once()

        edited_contents = [
            call.kwargs["content"] for call in interaction.edit_original_response.await_args_list
        ]
        assert any("Scanning files and estimating backup size" in content for content in edited_contents)
        assert any("Creating compressed archive" in content for content in edited_contents)
        assert "✅ **Backup successful!**" in edited_contents[-1]
        assert "created (" in edited_contents[-1]
        assert "Elapsed:" in edited_contents[-1]
        interaction.followup.send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_perform_backup_tar_command_has_no_exclude_args_when_exclusions_empty(
        self, backup_service, fake_context, tmp_path
    ):
        """When exclusions list is empty, the tar command should contain no --exclude flags."""
        from bot.services.backup import BackupScanStats

        project_root = tmp_path / "Discord-Brain-Rot"
        project_root.mkdir()
        backup_service.project_root = project_root
        backup_service.backup_dir = tmp_path / "backups"
        backup_service.exclusions = []

        scan_stats = BackupScanStats(total_bytes=30, total_entries=3, file_sizes={})

        async def fake_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        captured_command = None

        async def fake_create_subprocess_exec(*command, **_kwargs):
            nonlocal captured_command
            captured_command = command
            backup_path = Path(command[2])
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            backup_path.write_bytes(b"x" * 4096)
            return FakeProcess(stdout_lines=[b"a\n", b"b\n"], stderr=b"", returncode=0)

        with patch("bot.services.backup.asyncio.to_thread", new=AsyncMock(side_effect=fake_to_thread)):
            with patch.object(backup_service, "_scan_backup_contents", return_value=scan_stats):
                with patch("bot.services.backup.shutil.disk_usage", return_value=(10, 1, 10_000_000)):
                    with patch("bot.services.backup.asyncio.create_subprocess_exec", side_effect=fake_create_subprocess_exec):
                        with patch.object(backup_service, "_monitor_archive_progress", new=AsyncMock()):
                            await backup_service.perform_backup(fake_context)

        assert captured_command is not None
        assert "--exclude" not in captured_command, f"Unexpected --exclude in tar command: {captured_command}"

    @pytest.mark.asyncio
    async def test_perform_backup_fails_fast_when_disk_space_is_too_low(
        self, backup_service, fake_context, tmp_path
    ):
        """Disk-space failures should edit the original message instead of spawning tar."""
        from bot.services.backup import BackupScanStats

        project_root = tmp_path / "Discord-Brain-Rot"
        project_root.mkdir()
        backup_service.project_root = project_root
        backup_service.backup_dir = tmp_path / "backups"

        with patch(
            "bot.services.backup.asyncio.to_thread",
            new=AsyncMock(return_value=BackupScanStats(total_bytes=10_000_000, total_entries=1)),
        ):
            with patch("bot.services.backup.shutil.disk_usage", return_value=(10, 1, 1_000)):
                with patch("bot.services.backup.asyncio.create_subprocess_exec", new=AsyncMock()) as mock_exec:
                    await backup_service.perform_backup(fake_context)

        interaction = fake_context.interaction
        last_edit = interaction.edit_original_response.await_args_list[-1].kwargs["content"]
        assert "❌ **Backup failed**" in last_edit
        assert "Not enough disk space" in last_edit
        mock_exec.assert_not_called()


class TestBackupServiceScheduled:
    """Tests for scheduled backup target classes and perform_scheduled_backup."""

    @pytest.fixture
    def backup_service(self):
        """Create a BackupService with mocked dependencies."""
        from bot.services.backup import BackupService

        return BackupService(bot=Mock(), message_service=Mock())

    @pytest.mark.asyncio
    async def test_scheduled_target_first_send_then_edit(self):
        """Scheduled target should send first message then edit subsequent ones."""
        from bot.services.backup import _ScheduledBackupTarget

        message_mock = AsyncMock()
        channel = AsyncMock()
        channel.send = AsyncMock(return_value=message_mock)

        target = _ScheduledBackupTarget(channel)

        # First update: not done → send
        assert not target.response.is_done()
        await target.response.send_message("first", ephemeral=True)
        channel.send.assert_awaited_once_with("first")

        # Subsequent updates: done → edit
        assert target.response.is_done()
        await target.edit_original_response(content="second")
        message_mock.edit.assert_awaited_once_with(content="second")

    @pytest.mark.asyncio
    async def test_scheduled_target_edit_before_send_is_noop(self):
        """Editing before the first send should be a no-op (no message to edit)."""
        from bot.services.backup import _ScheduledBackupTarget

        target = _ScheduledBackupTarget(AsyncMock())
        # Should not raise
        await target.edit_original_response(content="anything")

    @pytest.mark.asyncio
    async def test_null_target_no_crash(self):
        """All null target methods should be safe no-ops."""
        from bot.services.backup import _NullBackupTarget

        target = _NullBackupTarget()
        assert target.response.is_done()
        await target.response.send_message("test", ephemeral=True)
        await target.edit_original_response(content="test")
        await target.followup.send("test", ephemeral=True)

    @pytest.mark.asyncio
    async def test_perform_scheduled_backup_with_channel_delegates(self, backup_service):
        """perform_scheduled_backup with a channel should call perform_backup."""
        channel = AsyncMock()
        backup_service.message_service.get_bot_channel = Mock(return_value=channel)

        with patch.object(backup_service, "perform_backup", new_callable=AsyncMock) as mock_perform:
            await backup_service.perform_scheduled_backup(guild=Mock())

        mock_perform.assert_awaited_once()
        target = mock_perform.await_args.args[0]
        from bot.services.backup import _ScheduledBackupTarget
        assert isinstance(target, _ScheduledBackupTarget)
        assert target.channel is channel

    @pytest.mark.asyncio
    async def test_perform_scheduled_backup_no_channel_no_crash(self, backup_service):
        """perform_scheduled_backup without a channel should not crash."""
        backup_service.message_service.get_bot_channel = Mock(return_value=None)

        with patch.object(backup_service, "perform_backup", new_callable=AsyncMock) as mock_perform:
            await backup_service.perform_scheduled_backup()

        mock_perform.assert_awaited_once()
        from bot.services.backup import _NullBackupTarget
        assert isinstance(mock_perform.await_args.args[0], _NullBackupTarget)


