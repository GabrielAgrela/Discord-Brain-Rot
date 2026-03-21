"""
Tests for bot/commands/rlstore.py - RocketLeagueStoreCog.
"""

from unittest.mock import Mock


class TestRocketLeagueStoreCog:
    """Tests for rlstore command content helpers."""

    def test_build_notify_content_includes_source_url_and_mention(self):
        """Slash-command content should include Merc status and the non-unfurled rlshop.gg URL."""
        from bot.commands.rlstore import RocketLeagueStoreCog

        cog = RocketLeagueStoreCog(bot=Mock(), behavior=None)
        cog.store_service = Mock()
        cog.store_service.build_merc_status_text = Mock(return_value="Merc car on the shop: no.")
        cog.store_service.build_source_url_text = Mock(return_value="<https://rlshop.gg>")
        cog.notify_target = "sopustos"

        member = Mock()
        member.name = "sopustos"
        member.display_name = "Sopustos"
        member.global_name = None
        member.mention = "<@123>"

        guild = Mock()
        guild.members = [member]
        guild.get_member = Mock(return_value=None)

        content, allowed_mentions = cog._build_notify_content(snapshot=Mock(), guild=guild)

        assert content == (
            "<@123> Merc car on the shop: no.\n"
            "<https://rlshop.gg>"
        )
        assert allowed_mentions.users is True
