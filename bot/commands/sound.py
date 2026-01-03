"""
Sound-related slash commands cog.

This cog handles all sound playback commands including:
- /toca - Play a specific sound
- /change - Rename a sound
- /list - Show database of sounds
- /lastsounds - Show recent sounds
"""

import asyncio
import discord
from discord.ext import commands
from discord.commands import Option

from bot.database import Database
from bot.models.sound import SoundEffect


class SoundCog(commands.Cog):
    """Cog for sound playback commands."""
    
    def __init__(self, bot: discord.Bot, behavior):
        """
        Initialize the sound cog.
        
        Args:
            bot: The Discord bot instance
            behavior: BotBehavior instance for sound operations
        """
        self.bot = bot
        self.behavior = behavior
        self.db = Database()
    
    @staticmethod
    async def _get_sound_autocomplete(ctx: discord.AutocompleteContext):
        """Autocomplete for sound names."""
        try:
            db = Database()
            current = ctx.value.lower() if ctx.value else ""
            if not current or len(current) < 2:
                return []
            
            similar_sounds = db.get_sounds_by_similarity_optimized(current, 15)
            return [sound[2].split('/')[-1].replace('.mp3', '') for sound in similar_sounds]
        except Exception as e:
            print(f"Autocomplete error: {e}")
            return []
    
    @commands.slash_command(name="toca", description="Write a name of something you want to hear")
    async def toca(
        self, 
        ctx: discord.ApplicationContext, 
        message: discord.Option(str, "Sound name ('random' for random)", required=True, autocomplete=_get_sound_autocomplete),
        speed: discord.Option(float, "Playback speed (0.5-3.0)", required=False, default=1.0),
        volume: discord.Option(float, "Volume multiplier (0.1-5.0)", required=False, default=1.0),
        reverse: discord.Option(bool, "Play in reverse?", required=False, default=False)
    ):
        """Play a sound by name."""
        await ctx.respond("Processing your request...", delete_after=0)
        
        try:
            # Use SoundEffect model for validation and clamping
            effects = SoundEffect(speed=speed, volume=volume, reverse=reverse)
            
            author = ctx.user
            username = f"{author.name}#{author.discriminator}"
            
            print(f"Playing '{message}' for {username} with effects: {effects.to_dict()}")
            
            if message == "random":
                asyncio.run_coroutine_threadsafe(
                    self.behavior.play_random_sound(username, effects=effects.to_dict()), 
                    self.bot.loop
                )
            else:
                await self.behavior.play_request(message, author.name, effects=effects.to_dict())
                
        except Exception as e:
            print(f"Error in toca command: {e}")
            await ctx.followup.send(
                f"An error occurred while trying to play '{message}'.", 
                ephemeral=True, 
                delete_after=10
            )
    
    @commands.slash_command(name="change", description="Change the name of a sound")
    async def change(
        self, 
        ctx: discord.ApplicationContext, 
        current: Option(str, "Current name of the sound", required=True), 
        new: Option(str, "New name of the sound", required=True)
    ):
        """Rename a sound file."""
        await ctx.respond("Processing your request...", delete_after=0)
        await self.behavior.change_filename(current, new, ctx.user)
    
    @commands.slash_command(name="list", description="Returns database of sounds")
    async def list_sounds(self, ctx: discord.ApplicationContext):
        """Show the sound database."""
        await ctx.respond("Processing your request...", delete_after=0)
        await self.behavior.list_sounds(ctx.user)
    
    @commands.slash_command(name="lastsounds", description="Returns last sounds downloaded")
    async def lastsounds(
        self, 
        ctx: discord.ApplicationContext, 
        number: Option(int, "Number of sounds", default=10, required=False)
    ):
        """Show recently downloaded sounds."""
        await self.behavior.list_sounds(ctx, number)
    @commands.slash_command(name="subwaysurfers", description="Play Subway Surfers gameplay")
    async def subway_surfers(self, ctx: discord.ApplicationContext):
        """Play Subway Surfers."""
        await ctx.respond("Processing your request...", delete_after=0)
        await self.behavior.subway_surfers()

    @commands.slash_command(name="familyguy", description="Play Family Guy clip")
    async def family_guy(self, ctx: discord.ApplicationContext):
        """Play Family Guy."""
        await ctx.respond("Processing your request...", delete_after=0)
        await self.behavior.family_guy()

    @commands.slash_command(name="slice", description="Play Slice All gameplay")
    async def slice(self, ctx: discord.ApplicationContext):
        """Play Slice All."""
        await self.behavior.slice_all(ctx)

def setup(bot: discord.Bot, behavior=None):
    """
    Set up the cog.
    
    Args:
        bot: Discord bot instance
        behavior: BotBehavior instance (required)
    """
    if behavior is None:
        raise ValueError("behavior parameter is required for SoundCog")
    bot.add_cog(SoundCog(bot, behavior))
