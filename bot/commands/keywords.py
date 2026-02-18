"""
Keyword management slash commands cog.
"""

import discord
from discord.ext import commands
from discord.commands import Option, SlashCommandGroup
import re

from bot.repositories import KeywordRepository, ListRepository

class KeywordCog(commands.Cog):
    """Cog for managing trigger keywords."""
    
    keyword = SlashCommandGroup("keyword", "Manage trigger keywords")
    
    def __init__(self, bot: discord.Bot, behavior):
        self.bot = bot
        self.behavior = behavior
        self.keyword_repo = KeywordRepository()
        self.list_repo = ListRepository()

    async def _get_list_autocomplete(self, ctx: discord.AutocompleteContext):
        """Autocomplete for sound lists."""
        try:
            current = ctx.value.lower() if ctx.value else ""
            guild_id = getattr(getattr(ctx, "interaction", None), "guild_id", None)
            lists = self.list_repo.get_all(limit=25, guild_id=guild_id)
            return [l[1] for l in lists if current in l[1].lower()]
        except Exception:
            return []

    @keyword.command(name="add", description="Add or update a trigger keyword")
    @discord.default_permissions(administrator=True)
    async def add_keyword(
        self,
        ctx: discord.ApplicationContext,
        keyword: Option(str, "Keyword to listen for", required=True),
        action: Option(str, "Action to perform", choices=["slap", "list"], required=True),
        list_name: Option(str, "List name (if action is 'list')", required=False, autocomplete=_get_list_autocomplete)
    ):
        """Add or update a keyword."""
        await ctx.defer(ephemeral=True)
        
        keyword = keyword.lower().strip()
        
        if action == "list" and not list_name:
            await ctx.respond("You must provide a list name if the action is 'list'.", ephemeral=True)
            return
            
        if action == "list":
            # Verify list exists
            lst = self.list_repo.get_by_name(list_name, guild_id=ctx.guild.id if ctx.guild else None)
            if not lst:
                await ctx.respond(f"List '{list_name}' not found.", ephemeral=True)
                return
            action_value = list_name
        else:
            action_value = ""

        success = self.keyword_repo.add(keyword, action, action_value)
        
        if success:
            # Refresh all active sinks
            audio_service = getattr(self.behavior, '_audio_service', None)
            if audio_service:
                for sink in audio_service.keyword_sinks.values():
                    sink.refresh_keywords()
            
            action_desc = "random slap" if action == "slap" else f"random from list '{list_name}'"
            await ctx.respond(f"Keyword '{keyword}' added! Will trigger: {action_desc}.", ephemeral=True)
            
            await self.behavior.send_message(
                title="Keyword Added",
                description=f"User {ctx.author.name} added keyword '{keyword}' -> {action_desc}."
            )
        else:
            await ctx.respond("Failed to add keyword.", ephemeral=True)

    @keyword.command(name="remove", description="Remove a trigger keyword")
    @discord.default_permissions(administrator=True)
    async def remove_keyword(
        self,
        ctx: discord.ApplicationContext,
        keyword: Option(str, "Keyword to remove", required=True)
    ):
        """Remove a keyword."""
        keyword = keyword.lower().strip()
        
        existing = self.keyword_repo.get_by_keyword(keyword)
        if not existing:
            await ctx.respond(f"Keyword '{keyword}' not found.", ephemeral=True)
            return
            
        success = self.keyword_repo.remove(keyword)
        if success:
            # Refresh all active sinks
            audio_service = getattr(self.behavior, '_audio_service', None)
            if audio_service:
                for sink in audio_service.keyword_sinks.values():
                    sink.refresh_keywords()
                    
            await ctx.respond(f"Keyword '{keyword}' removed.", ephemeral=True)
            
            await self.behavior.send_message(
                title="Keyword Removed",
                description=f"User {ctx.author.name} removed keyword '{keyword}'."
            )
        else:
            await ctx.respond("Failed to remove keyword.", ephemeral=True)

    @keyword.command(name="list", description="List all trigger keywords")
    async def list_keywords(self, ctx: discord.ApplicationContext):
        """List all keywords."""
        keywords = self.keyword_repo.get_all()
        
        if not keywords:
            await ctx.respond("No keywords configured.", ephemeral=True)
            return
            
        description = ""
        for k in keywords:
            action = k['action_type']
            value = k['action_value']
            action_desc = "Slap" if action == "slap" else f"List: {value}"
            description += f"• **{k['keyword']}** → {action_desc}\n"
            
        embed = discord.Embed(
            title="Trigger Keywords",
            description=description,
            color=discord.Color.blue()
        )
        await ctx.respond(embed=embed, ephemeral=True)

def setup(bot: discord.Bot, behavior=None):
    if behavior is None:
        raise ValueError("behavior parameter is required for KeywordCog")
    bot.add_cog(KeywordCog(bot, behavior))
