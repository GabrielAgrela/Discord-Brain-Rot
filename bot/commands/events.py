"""
User Event slash commands cog.

This cog handles event-related commands:
- /addevent - Add a sound when user joins/leaves
- /listevents - List user's events
"""

import discord
from discord.ext import commands
from discord.commands import Option

from bot.database import Database


class EventCog(commands.Cog):
    """Cog for managing user events (join/leave sounds)."""
    
    def __init__(self, bot: discord.Bot, behavior):
        self.bot = bot
        self.behavior = behavior
        self.db = Database()
    
    @staticmethod
    async def _get_user_choices(ctx: discord.AutocompleteContext):
        """Get all known users for autocomplete."""
        db = Database()
        return db.get_all_users()

    @commands.slash_command(name="addevent", description="Add a join/leave event sound for a user")
    async def add_event(
        self, 
        ctx: discord.ApplicationContext, 
        username: Option(str, "Select a user", autocomplete=_get_user_choices, required=True),
        event: Option(str, "Event type", choices=["join", "leave"], required=True),
        sound: Option(str, "Sound name to play", required=True)
    ):
        """Set a sound to play on user join/leave."""
        await ctx.respond("Processing your request...", delete_after=0)
        success = await self.behavior.add_user_event(username, event, sound)
        if success:
            await ctx.followup.send(f"Successfully added {sound} as {event} sound for {username}!", ephemeral=True, delete_after=5)
        else:
            await ctx.followup.send("Failed to add event sound. Make sure the username and sound are correct!", ephemeral=True, delete_after=5)


    @commands.slash_command(name="listevents", description="List your join/leave event sounds")
    async def list_events(
        self, 
        ctx: discord.ApplicationContext, 
        username: Option(str, "User to list events for", autocomplete=_get_user_choices, required=False)
    ):
        """List event sounds for a user."""
        await ctx.respond("Processing your request...", delete_after=0)
        
        if username:
            target_user = username
            target_user_full = username
        else:
            target_user = ctx.user.name
            target_user_full = f"{ctx.user.name}#{ctx.user.discriminator}"
        
        if not await self.behavior.list_user_events(target_user, target_user_full, requesting_user=ctx.user.name):
            await ctx.followup.send(f"No event sounds found for {target_user}!", ephemeral=True)



def setup(bot: discord.Bot, behavior=None):
    if behavior is None:
        raise ValueError("behavior is required for EventCog")
    bot.add_cog(EventCog(bot, behavior))
