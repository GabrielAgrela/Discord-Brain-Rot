"""
TTS (Text-to-Speech) related slash commands cog.

This cog handles all TTS commands including:
- /tts - Generate TTS with various voices
- /sts - Speech-to-Speech conversion
- /isolate - Isolate voice from a sound
"""

import io
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
    
    async def _send_loading_card(self, guild) -> 'discord.Message':
        """Send a loading card image (GIF) to the bot channel and return the message.
        
        Args:
            guild: The Discord guild to send to
            
        Returns:
            The sent message or None
        """
        bot_channel = self.behavior._message_service.get_bot_channel(guild)
        if not bot_channel:
            return None
        
        # Try to generate/load GIF
        image_bytes = self.behavior._audio_service.image_generator.generate_loading_gif()
        
        if image_bytes:
            file = discord.File(io.BytesIO(image_bytes), filename="loading.gif")
            return await bot_channel.send(file=file)
        else:
            # Fallback: simple embed
            embed = discord.Embed(
                title="⏳ Processing...",
                description="Generating audio, please wait",
                color=discord.Color.dark_blue()
            )
            return await bot_channel.send(embed=embed)
    
    @commands.slash_command(name="tts", description="Generate TTS with Google or ElevenLabs voices")
    async def tts(
        self, 
        ctx: discord.ApplicationContext, 
        message: Option(str, "What you want to say", required=True),
        language: Option(str, "Select a voice or language", choices=list(TTS_PROFILES.keys()), required=True),
        expressive: Option(bool, "Use AI to add emotional tags (ElevenLabs)", required=False, default=True)
    ):
        """Generate text-to-speech audio."""
        await ctx.respond("Processing your request...", delete_after=0)
        
        # Send loading card instead of character embed
        loading_message = await self._send_loading_card(ctx.guild)

        if expressive:
            # Pass loading_message to process_text_for_tts if needed, or just let it process
            # Note: process_text_for_tts might take a few seconds
            processed = await self.behavior._llm_service.process_text_for_tts(message)
            if processed and processed.strip():
                message = processed
            else:
                print(f"[TTSCog] Warning: LLM returned empty text for TTS. Falling back to original.")

        
        profile = TTS_PROFILES.get(language, TTS_PROFILES["en"])
        
        discord_user = ctx.author if isinstance(ctx.author, (discord.Member, discord.User)) else ctx.user
        user = discord_user
        
        self.behavior.color = discord.Color.dark_blue()
        
        # Get avatar URL
        avatar = getattr(discord_user, "display_avatar", None)
        requester_avatar_url = str(avatar.url) if avatar else None
        
        # Get TTS profile thumbnail for the sound card
        sts_thumbnail_url = profile.get("thumbnail")
        
        try:
            if profile.get("provider") == "elevenlabs":
                await self.behavior._voice_transformation_service.tts_EL(
                    user, message, profile.get("voice", "en"),
                    loading_message=loading_message,
                    requester_avatar_url=requester_avatar_url,
                    sts_thumbnail_url=sts_thumbnail_url
                )
            else:
                lang = profile.get("lang", "en")
                region = profile.get("region", "")
                await self.behavior._voice_transformation_service.tts(
                    user, message, lang, region,
                    loading_message=loading_message,
                    requester_avatar_url=requester_avatar_url
                )
        except Exception as e:
            if loading_message:
                try:
                    await loading_message.delete()
                except:
                    pass
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
        
        # Get avatar URL and character thumbnail
        avatar = getattr(discord_user, "display_avatar", None)
        requester_avatar_url = str(avatar.url) if avatar else None
        sts_thumbnail_url = profile.get("thumbnail")
        
        # Send loading card instead of character embed
        loading_message = await self._send_loading_card(ctx.guild)
        
        try:
            await self.behavior._voice_transformation_service.sts_EL(
                user, sound, char,
                loading_message=loading_message,
                requester_avatar_url=requester_avatar_url,
                sts_thumbnail_url=sts_thumbnail_url
            )
        except Exception as e:
            if loading_message:
                try:
                    await loading_message.delete()
                except:
                    pass
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
            await self.behavior._voice_transformation_service.isolate_voice(
                sound_name=sound,
                guild_id=ctx.guild.id if ctx.guild else None,
            )
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
