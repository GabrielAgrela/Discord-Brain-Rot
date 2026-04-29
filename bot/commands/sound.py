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
from discord.commands import Option, SlashCommandGroup
import sqlite3

from bot.database import Database
from bot.models.sound import SoundEffect


async def _get_sound_autocomplete(ctx: discord.AutocompleteContext):
    """Autocomplete for sound names."""
    try:
        db = Database()
        current = ctx.value.lower() if ctx.value else ""
        if not current or len(current) < 2:
            return []
        
        guild_id = getattr(getattr(ctx, "interaction", None), "guild_id", None)
        similar_sounds = db.get_sounds_by_similarity(current, 15, guild_id=guild_id)
        # similar_sounds is a list of (sound_data, score)
        completions = []
        for s in similar_sounds:
            sound_data = s[0]
            # Robustly get filename from Row, dict, or tuple
            if isinstance(sound_data, (sqlite3.Row, dict)):
                filename = sound_data['Filename']
            else:
                filename = sound_data[2]
            completions.append(filename.split('/')[-1].replace('.mp3', ''))
        return completions
    except Exception as e:
        print(f"Autocomplete error: {e}")
        return []

class SoundCog(commands.Cog):
    """Cog for sound playback commands."""

    favoritewatcher = SlashCommandGroup(
        "favoritewatcher",
        "TikTok favorites collection watcher commands",
    )
    
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

    def _ensure_admin(self, ctx: discord.ApplicationContext) -> bool:
        """Check if the invoker can manage guild-level sound imports."""
        if not ctx.guild:
            return False
        return self.behavior.is_admin_or_mod(ctx.author)
    
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
                    self.behavior._sound_service.play_random_sound(username, effects=effects.to_dict(), guild=ctx.guild), 
                    self.bot.loop
                )
            else:
                await self.behavior._sound_service.play_request(message, author.name, effects=effects.to_dict(), guild=ctx.guild)
                
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
        await self.behavior._sound_service.change_filename(current, new, ctx.user)
    
    
    @commands.slash_command(name="lastsounds", description="Returns last sounds downloaded")
    async def lastsounds(
        self, 
        ctx: discord.ApplicationContext, 
        number: Option(int, "Number of sounds", default=10, required=False)
    ):
        """Show recently downloaded sounds."""
        await self.behavior.list_sounds(ctx.user, number, guild=ctx.guild)
    @commands.slash_command(name="subwaysurfers", description="Play Subway Surfers gameplay")
    async def subway_surfers(self, ctx: discord.ApplicationContext):
        """Play Subway Surfers."""
        await ctx.respond("Processing your request...", delete_after=0)
        await self.behavior.subway_surfers(ctx.user, guild=ctx.guild)

    @commands.slash_command(name="familyguy", description="Play Family Guy clip")
    async def family_guy(self, ctx: discord.ApplicationContext):
        """Play Family Guy."""
        await ctx.respond("Processing your request...", delete_after=0)
        await self.behavior.family_guy(ctx.user, guild=ctx.guild)

    @commands.slash_command(name="slice", description="Play Slice All gameplay")
    async def slice(self, ctx: discord.ApplicationContext):
        """Play Slice All."""
        await ctx.respond("Processing your request...", delete_after=0)
        await self.behavior.slice_all(ctx.user, guild=ctx.guild)

    @favoritewatcher.command(name="add", description="Watch a TikTok collection for new sound imports")
    async def favoritewatcher_add(
        self,
        ctx: discord.ApplicationContext,
        url: Option(str, "TikTok collection URL", required=True),
    ):
        """Add a TikTok collection watcher for this guild."""
        if not self._ensure_admin(ctx):
            await ctx.respond("You don't have permission to change sound watchers.", ephemeral=True)
            return

        await ctx.defer(ephemeral=True)
        try:
            watcher_id, seeded_count = await self.behavior._favorite_watcher_service.add_watcher(
                url=url,
                guild_id=ctx.guild.id,
                added_by_user_id=ctx.author.id,
                added_by_username=ctx.author.name,
            )
        except sqlite3.IntegrityError:
            await ctx.followup.send("That collection is already being watched for this server.", ephemeral=True)
            return
        except ValueError as exc:
            await ctx.followup.send(str(exc), ephemeral=True)
            return
        except Exception as exc:
            print(f"[SoundCog] Failed to add favorite watcher: {exc}")
            await ctx.followup.send("Failed to add that watcher. Check the URL and try again.", ephemeral=True)
            return

        await ctx.followup.send(
            (
                f"Favorite watcher `{watcher_id}` added. "
                f"Seeded {seeded_count} existing video(s), so only future additions will import."
            ),
            ephemeral=True,
        )

    @favoritewatcher.command(name="list", description="List watched TikTok collections")
    async def favoritewatcher_list(self, ctx: discord.ApplicationContext):
        """List active TikTok collection watchers for this guild."""
        if not self._ensure_admin(ctx):
            await ctx.respond("You don't have permission to view sound watchers.", ephemeral=True)
            return

        watchers = self.behavior._favorite_watcher_service.list_watchers(ctx.guild.id)
        if not watchers:
            await ctx.respond("No favorite watchers are configured for this server.", ephemeral=True)
            return

        lines = [
            f"`{watcher['id']}` {watcher['url']} (last checked: {watcher['last_checked_at'] or 'never'})"
            for watcher in watchers[:20]
        ]
        await ctx.respond("\n".join(lines), ephemeral=True)

    @favoritewatcher.command(name="remove", description="Stop watching a TikTok collection")
    async def favoritewatcher_remove(
        self,
        ctx: discord.ApplicationContext,
        watcher_id: Option(int, "Watcher ID from /favoritewatcher list", required=True),
    ):
        """Disable a TikTok collection watcher for this guild."""
        if not self._ensure_admin(ctx):
            await ctx.respond("You don't have permission to change sound watchers.", ephemeral=True)
            return

        removed = self.behavior._favorite_watcher_service.remove_watcher(
            watcher_id,
            ctx.guild.id,
        )
        if not removed:
            await ctx.respond("Watcher not found for this server.", ephemeral=True)
            return
        await ctx.respond(f"Favorite watcher `{watcher_id}` removed.", ephemeral=True)

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
