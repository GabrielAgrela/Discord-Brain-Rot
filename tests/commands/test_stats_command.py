"""
Tests for bot/commands/stats.py - StatsCog.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest


class TestStatsCog:
    """Tests for stats command helpers."""

    def test_resolve_discord_upload_limit_uses_configured_override(self, monkeypatch):
        """Configured GIF limit should override the guild upload limit."""
        from bot.commands.stats import StatsCog

        monkeypatch.setenv("YEAR_REVIEW_GIF_MAX_MB", "5")
        cog = StatsCog(bot=Mock(), behavior=Mock())
        ctx = SimpleNamespace(guild=SimpleNamespace(filesize_limit=25 * 1024 * 1024))

        assert cog._resolve_discord_upload_limit(ctx) == 5 * 1024 * 1024

    def test_resolve_discord_upload_limit_uses_conservative_guild_limit(self, monkeypatch):
        """Guild upload limit should be reduced slightly to leave protocol overhead room."""
        from bot.commands.stats import StatsCog

        monkeypatch.delenv("YEAR_REVIEW_GIF_MAX_MB", raising=False)
        cog = StatsCog(bot=Mock(), behavior=Mock())
        ctx = SimpleNamespace(guild=SimpleNamespace(filesize_limit=10 * 1024 * 1024))

        assert cog._resolve_discord_upload_limit(ctx) == int(10 * 1024 * 1024 * 0.92)

    @pytest.mark.asyncio
    async def test_year_review_gif_replaces_progress_message_with_file(self, tmp_path):
        """Generated year review GIF should edit the original progress response, not send a captioned follow-up."""
        from bot.commands.stats import StatsCog

        gif_path = tmp_path / "review.gif"
        gif_path.write_bytes(b"GIF89a")
        cog = StatsCog(bot=Mock(), behavior=Mock())
        cog.year_review_video_service.render_year_review_gif = Mock(
            return_value=SimpleNamespace(path=str(gif_path), size_bytes=1024)
        )
        ctx = SimpleNamespace(
            guild=SimpleNamespace(filesize_limit=8 * 1024 * 1024),
            interaction=SimpleNamespace(edit_original_response=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )
        target_user = SimpleNamespace(
            name="sopustos",
            display_name="sopustos",
            display_avatar=None,
        )

        await cog._send_year_review_gif(
            ctx,
            target_user,
            {"total_plays": 5, "unique_sounds": 2},
            2026,
        )

        final_call = ctx.interaction.edit_original_response.await_args_list[-1]
        assert final_call.kwargs["content"] == ""
        assert "file" in final_call.kwargs
        ctx.followup.send.assert_not_awaited()
