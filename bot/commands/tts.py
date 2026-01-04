"""
TTS (Text-to-Speech) related slash commands cog.

This cog handles all TTS commands including:
- /tts - Generate TTS with various voices
- /sts - Speech-to-Speech conversion
- /isolate - Isolate voice from a sound
"""

import discord
from discord.ext import commands
from discord.commands import Option

from config import TTS_PROFILES, CHARACTER_CHOICES, DEFAULT_TTS_THUMBNAIL


class TTSCog(commands.Cog):
    """Cog for TTS and voice-related commands."""
    
    def __init__(self, bot: discord.Bot, behavior):
        """
        Initialize the TTS cog.
        
        Args:
            bot: The Discord bot instance
            behavior: BotBehavior instance for TTS operations
        """
        self.bot = bot
        self.behavior = behavior
    
    @commands.slash_command(name="tts", description="Generate TTS with Google or ElevenLabs voices")
    async def tts(
        self, 
        ctx: discord.ApplicationContext, 
        message: Option(str, "What you want to say", required=True),
        language: Option(str, "Select a voice or language", choices=list(TTS_PROFILES.keys()), required=True)
    ):
        """Generate text-to-speech audio."""
        await ctx.respond("Processing your request...", delete_after=0)
        
        profile = TTS_PROFILES.get(language, TTS_PROFILES["en"])
        flag = profile.get("flag", ":speech_balloon:")
        
        discord_user = ctx.author if isinstance(ctx.author, (discord.Member, discord.User)) else ctx.user
        user = discord_user
        
        self.behavior.color = discord.Color.dark_blue()
        
        # Get thumbnail
        url = profile.get("thumbnail")
        if not url:
            avatar = getattr(discord_user, "display_avatar", None)
            url = avatar.url if avatar else DEFAULT_TTS_THUMBNAIL
        
        await self.behavior._message_service.send_message(
            title=f"TTS • {profile.get('display', language.title())} {flag}",
            description=f"'{message}'",
            thumbnail=url
        )
        
        try:
            if profile.get("provider") == "elevenlabs":
                await self.behavior._voice_transformation_service.tts_EL(user, message, profile.get("voice", "en"))
            else:
                lang = profile.get("lang", "en")
                region = profile.get("region", "")
                await self.behavior._voice_transformation_service.tts(user, message, lang, region)
        except Exception as e:
            await self.behavior._message_service.send_error(str(e))

    @commands.slash_command(name="sts", description="Speech-To-Speech conversion")
    async def sts(
        self, 
        ctx: discord.ApplicationContext, 
        sound: Option(str, "Base sound you want to convert", required=True),
        char: Option(str, "Voice to convert into", choices=CHARACTER_CHOICES, required=True)
    ):
        """Convert a sound to a different voice."""
        await ctx.respond("Processing your request...", delete_after=0)
        
        discord_user = ctx.author if isinstance(ctx.author, (discord.Member, discord.User)) else ctx.user
        user = discord_user
        
        self.behavior.color = discord.Color.dark_blue()
        
        profile = TTS_PROFILES.get(char, TTS_PROFILES["tyson"])
        url = profile.get("thumbnail")
        if not url:
            avatar = getattr(discord_user, "display_avatar", None)
            url = avatar.url if avatar else DEFAULT_TTS_THUMBNAIL
        
        await self.behavior._message_service.send_message(
            title=f"{sound} to {profile.get('display', char.title())}",
            description=f"'{profile.get('display', char.title())}'",
            thumbnail=url
        )
        
        try:
            await self.behavior._voice_transformation_service.sts_EL(user, sound, char)
        except Exception as e:
            await self.behavior._message_service.send_error(str(e))
    
    @commands.slash_command(name="isolate", description="Isolate voice from a sound")
    async def isolate(
        self, 
        ctx: discord.ApplicationContext, 
        sound: Option(str, "Base sound you want to isolate", required=True)
    ):
        """Isolate vocals from a sound file."""
        await ctx.respond("Processing your request...", delete_after=0)
        
        user = discord.utils.get(self.bot.get_all_members(), name=ctx.user.name)
        self.behavior.color = discord.Color.dark_blue()
        
        try:
            await self.behavior._audio_service.isolate_voice(user, sound)
        except Exception as e:
            await self.behavior._message_service.send_error(str(e))


def setup(bot: discord.Bot, behavior=None):
    """
    Set up the cog.
    
    Args:
        bot: Discord bot instance
        behavior: BotBehavior instance (required)
    """
    if behavior is None:
        raise ValueError("behavior parameter is required for TTSCog")
    bot.add_cog(TTSCog(bot, behavior))
