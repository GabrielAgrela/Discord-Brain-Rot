"""
Tests for bot/commands/admin.py - AdminCog.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest


def _make_context(author):
    """Create a minimal Discord application context mock."""
    guild = SimpleNamespace(id=456)
    return SimpleNamespace(
        author=author,
        guild=guild,
        respond=AsyncMock(),
        followup=SimpleNamespace(send=AsyncMock()),
    )


def _make_cog(owner_ids=None):
    """Create an AdminCog with mocked dependencies."""
    from bot.commands.admin import AdminCog

    behavior = Mock()
    behavior._owner_user_ids = set(owner_ids or [])
    behavior._message_service.send_message = AsyncMock()

    with patch("bot.commands.admin.ActionRepository") as action_repo_cls:
        cog = AdminCog(bot=Mock(), behavior=behavior)

    return cog, behavior, action_repo_cls.return_value


class TestAdminCog:
    """Tests for administrative slash command behavior."""

    @pytest.mark.asyncio
    async def test_reboot_allows_discord_administrator(self):
        """Administrators should be able to trigger the host reboot command."""
        cog, behavior, action_repo = _make_cog()
        author = SimpleNamespace(
            id=123,
            name="admin-user",
            mention="<@123>",
            guild_permissions=SimpleNamespace(administrator=True),
        )
        ctx = _make_context(author)

        with patch("bot.commands.admin.asyncio.sleep", new=AsyncMock()) as sleep:
            with patch("bot.commands.admin.asyncio.to_thread", new=AsyncMock()) as to_thread:
                await cog.reboot.callback(cog, ctx)

        action_repo.insert.assert_called_once_with(
            "admin-user",
            "reboot_host",
            "requested",
            guild_id=456,
        )
        behavior._message_service.send_message.assert_awaited_once()
        ctx.respond.assert_awaited_once_with(
            "Rebooting host machine...",
            ephemeral=True,
            delete_after=5,
        )
        sleep.assert_awaited_once_with(2)
        to_thread.assert_awaited_once()
        command = to_thread.await_args.args[1]
        assert command == ["nsenter", "-t", "1", "-m", "-u", "-n", "-i", "reboot"]
        assert to_thread.await_args.kwargs == {"check": True}

    @pytest.mark.asyncio
    async def test_reboot_allows_owner_allowlist(self):
        """Owner allowlist members should be able to trigger reboot without guild admin permission."""
        cog, behavior, _action_repo = _make_cog(owner_ids={123})
        author = SimpleNamespace(
            id=123,
            name="owner-user",
            mention="<@123>",
            guild_permissions=SimpleNamespace(administrator=False),
        )
        ctx = _make_context(author)

        with patch("bot.commands.admin.asyncio.sleep", new=AsyncMock()):
            with patch("bot.commands.admin.asyncio.to_thread", new=AsyncMock()) as to_thread:
                await cog.reboot.callback(cog, ctx)

        behavior._message_service.send_message.assert_awaited_once()
        to_thread.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reboot_rejects_non_administrator(self):
        """Members without administrator permission should not trigger host reboot."""
        cog, behavior, action_repo = _make_cog()
        author = SimpleNamespace(
            id=123,
            name="mod-user",
            mention="<@123>",
            guild_permissions=SimpleNamespace(administrator=False, manage_channels=True),
        )
        ctx = _make_context(author)

        with patch("bot.commands.admin.asyncio.to_thread", new=AsyncMock()) as to_thread:
            await cog.reboot.callback(cog, ctx)

        ctx.respond.assert_awaited_once_with(
            "You don't have permission to use this command.",
            ephemeral=True,
        )
        action_repo.insert.assert_not_called()
        behavior._message_service.send_message.assert_not_awaited()
        to_thread.assert_not_awaited()
