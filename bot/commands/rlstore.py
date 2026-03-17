"""
Rocket League item shop slash command.
"""

import logging
import os

import discord
from discord.ext import commands

from bot.services.image_generator import ImageGeneratorService
from bot.services.rl_store import RocketLeagueStoreService
from bot.ui import RocketLeagueStoreView


logger = logging.getLogger(__name__)


class RocketLeagueStoreCog(commands.Cog):
    """Cog for browsing today's Rocket League item shop."""

    def __init__(self, bot: discord.Bot, behavior):
        """
        Initialize the Rocket League store cog.

        Args:
            bot: The Discord bot instance.
            behavior: BotBehavior instance providing shared services.
        """
        self.bot = bot
        self.behavior = behavior
        self.store_service = (
            behavior._rocket_league_store_service
            if behavior is not None
            else RocketLeagueStoreService()
        )
        self.image_generator = (
            behavior._audio_service.image_generator
            if behavior is not None
            else ImageGeneratorService()
        )
        self.notify_target = (os.getenv("RLSTORE_NOTIFY_TARGET_USERNAME", "sopustos") or "").strip()

    @commands.slash_command(name="rlstore", description="Show today's Rocket League item shop")
    async def rlstore(self, ctx: discord.ApplicationContext):
        """Fetch and display today's Rocket League store pages."""
        await ctx.defer()

        try:
            snapshot = await self.store_service.fetch_store_snapshot()
        except Exception:
            logger.exception("Failed to fetch Rocket League store for /rlstore")
            await ctx.followup.send(
                "Failed to load the Rocket League store right now. Try again in a bit.",
                ephemeral=True,
            )
            return

        content, allowed_mentions = self._build_notify_content(snapshot, ctx.guild)
        view = RocketLeagueStoreView(
            snapshot=snapshot,
            owner_id=ctx.user.id,
            image_generator=self.image_generator,
        )
        await view.prepare_all_pages()
        image_file = await view.create_file()
        if image_file is not None:
            await ctx.followup.send(
                content=content,
                file=image_file,
                view=view,
                allowed_mentions=allowed_mentions,
            )
            return

        await ctx.followup.send(
            content=content,
            embed=view.create_embed(),
            view=view,
            allowed_mentions=allowed_mentions,
        )

    def _build_notify_content(
        self,
        snapshot,
        guild: discord.Guild | None,
    ) -> tuple[str, discord.AllowedMentions]:
        """Build the content line that notifies the configured target about Merc presence."""
        merc_status = self.store_service.build_merc_status_text(snapshot)
        target_member = self._resolve_notify_member(guild)
        if target_member is not None:
            return f"{target_member.mention} {merc_status}", discord.AllowedMentions(users=True)
        return merc_status, discord.AllowedMentions.none()

    def _resolve_notify_member(self, guild: discord.Guild | None) -> discord.Member | None:
        """Resolve the configured notify target to a guild member."""
        if guild is None or not self.notify_target:
            return None

        target = self.notify_target.strip()
        if target.isdigit():
            member = guild.get_member(int(target))
            if member is not None:
                return member

        target_lower = target.lower()
        for member in guild.members:
            candidates = {
                (member.name or "").lower(),
                (member.display_name or "").lower(),
                (getattr(member, "global_name", None) or "").lower(),
            }
            if target_lower in candidates:
                return member
        return None


def setup(bot: discord.Bot, behavior=None):
    """
    Add the cog to the bot.

    Args:
        bot: Discord bot instance.
        behavior: BotBehavior instance.
    """
    bot.add_cog(RocketLeagueStoreCog(bot, behavior))
