"""
Guild setup/settings slash commands for multi-guild hosted usage.
"""

import discord
from discord.ext import commands
from discord.commands import Option, SlashCommandGroup


class SettingsCog(commands.Cog):
    """Guild setup and settings commands."""

    settings = SlashCommandGroup("settings", "Guild settings commands")

    def __init__(self, bot: discord.Bot, behavior):
        self.bot = bot
        self.behavior = behavior

    def _ensure_admin(self, ctx: discord.ApplicationContext) -> bool:
        """Check if the invoker can manage guild-level bot settings."""
        if not ctx.guild:
            return False
        return self.behavior.is_admin_or_mod(ctx.author)

    @commands.slash_command(name="setup", description="Initial guild setup for channels and defaults")
    async def setup_guild(
        self,
        ctx: discord.ApplicationContext,
        text_channel: Option(discord.TextChannel, "Bot text channel", required=False, default=None),
        voice_channel: Option(discord.VoiceChannel, "Default voice channel", required=False, default=None),
    ):
        """Initialize or update guild settings defaults."""
        if not ctx.guild:
            await ctx.respond("This command can only be used inside a server.", ephemeral=True)
            return
        if not self._ensure_admin(ctx):
            await ctx.respond("You don't have permission to run setup.", ephemeral=True)
            return

        settings_service = self.behavior._guild_settings_service
        settings_service.ensure_guild(ctx.guild.id)
        if text_channel or voice_channel:
            settings_service.set_channels(
                guild_id=ctx.guild.id,
                bot_text_channel_id=text_channel.id if text_channel else None,
                default_voice_channel_id=voice_channel.id if voice_channel else None,
            )

        current = settings_service.get(ctx.guild.id)
        await ctx.respond(
            (
                "Setup saved.\n"
                f"- Text channel: <#{current.bot_text_channel_id}>"
                if current.bot_text_channel_id
                else "Setup saved.\n- Text channel: default `#bot` fallback"
            )
            + (
                f"\n- Default voice: <#{current.default_voice_channel_id}>"
                if current.default_voice_channel_id
                else "\n- Default voice: largest active channel fallback"
            )
            + (
                f"\n- Features: autojoin={current.autojoin_enabled}, periodic={current.periodic_enabled}, stt={current.stt_enabled}"
            )
            + f"\n- Audio policy: `{current.audio_policy}`",
            ephemeral=True,
        )

    @settings.command(name="channel", description="Configure bot text/voice channels for this guild")
    async def settings_channel(
        self,
        ctx: discord.ApplicationContext,
        channel_type: Option(str, "Channel type", choices=["text", "voice"], required=True),
        action: Option(str, "Set or clear", choices=["set", "clear"], required=True),
        text_channel: Option(discord.TextChannel, "Text channel to set", required=False, default=None),
        voice_channel: Option(discord.VoiceChannel, "Voice channel to set", required=False, default=None),
    ):
        """Set or clear configured text/voice channels."""
        if not ctx.guild:
            await ctx.respond("This command can only be used inside a server.", ephemeral=True)
            return
        if not self._ensure_admin(ctx):
            await ctx.respond("You don't have permission to change settings.", ephemeral=True)
            return

        settings_service = self.behavior._guild_settings_service
        settings_service.ensure_guild(ctx.guild.id)

        if action == "clear":
            field_name = "bot_text_channel_id" if channel_type == "text" else "default_voice_channel_id"
            settings_service.clear_channel(ctx.guild.id, field_name)
            await ctx.respond(f"Cleared `{channel_type}` channel setting.", ephemeral=True)
            return

        if channel_type == "text":
            if not text_channel:
                await ctx.respond("Provide `text_channel` when channel_type is text.", ephemeral=True)
                return
            settings_service.set_channels(ctx.guild.id, bot_text_channel_id=text_channel.id)
            await ctx.respond(f"Configured bot text channel as {text_channel.mention}.", ephemeral=True)
            return

        if not voice_channel:
            await ctx.respond("Provide `voice_channel` when channel_type is voice.", ephemeral=True)
            return
        settings_service.set_channels(ctx.guild.id, default_voice_channel_id=voice_channel.id)
        await ctx.respond(f"Configured default voice channel as {voice_channel.mention}.", ephemeral=True)

    @settings.command(name="feature", description="Enable or disable guild features")
    async def settings_feature(
        self,
        ctx: discord.ApplicationContext,
        feature: Option(
            str,
            "Feature",
            choices=["autojoin_enabled", "periodic_enabled", "stt_enabled"],
            required=True,
        ),
        enabled: Option(bool, "Enable or disable", required=True),
    ):
        """Toggle feature flags for this guild."""
        if not ctx.guild:
            await ctx.respond("This command can only be used inside a server.", ephemeral=True)
            return
        if not self._ensure_admin(ctx):
            await ctx.respond("You don't have permission to change settings.", ephemeral=True)
            return

        settings = self.behavior._guild_settings_service.set_feature(ctx.guild.id, feature, enabled)

        if feature == "stt_enabled":
            try:
                if enabled and ctx.guild.voice_client and ctx.guild.voice_client.is_connected():
                    await self.behavior._audio_service.start_keyword_detection(ctx.guild)
                if not enabled:
                    await self.behavior._audio_service.stop_keyword_detection(ctx.guild)
            except Exception as exc:
                print(f"[SettingsCog] Failed to apply STT toggle immediately: {exc}")

        await ctx.respond(
            f"Updated `{feature}` to `{enabled}` for this guild. Current STT={settings.stt_enabled}, periodic={settings.periodic_enabled}, autojoin={settings.autojoin_enabled}.",
            ephemeral=True,
        )

    @settings.command(name="audio_policy", description="Set guild audio policy")
    async def settings_audio_policy(
        self,
        ctx: discord.ApplicationContext,
        policy: Option(str, "Audio policy", choices=["low_latency", "balanced", "high_quality"], required=True),
    ):
        """Configure audio policy for this guild."""
        if not ctx.guild:
            await ctx.respond("This command can only be used inside a server.", ephemeral=True)
            return
        if not self._ensure_admin(ctx):
            await ctx.respond("You don't have permission to change settings.", ephemeral=True)
            return

        settings = self.behavior._guild_settings_service.set_audio_policy(ctx.guild.id, policy)
        await ctx.respond(
            f"Audio policy updated to `{settings.audio_policy}` for this guild.",
            ephemeral=True,
        )


def setup(bot: discord.Bot, behavior=None):
    """Set up settings commands cog."""
    if behavior is None:
        raise ValueError("behavior parameter is required for SettingsCog")
    bot.add_cog(SettingsCog(bot, behavior))
