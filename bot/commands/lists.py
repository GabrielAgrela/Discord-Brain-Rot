"""
Sound List slash commands cog.

This cog handles all list-related commands:
- /createlist - Create a new sound list
- /addtolist - Add a sound to a list
- /removefromlist - Remove a sound from a list
- /deletelist - Delete an entire list
- /showlist - Display a list
- /mylists - Show user's lists
"""

import discord
from discord.ext import commands
from discord.commands import Option
import re

from bot.database import Database
from bot.ui import PaginatedSoundListView



async def _get_sound_autocomplete(ctx: discord.AutocompleteContext):
    """Autocomplete for sound names."""
    try:
        db = Database()
        current = ctx.value.lower() if ctx.value else ""
        if not current or len(current) < 2:
            return []
        
        similar_sounds = db.get_sounds_by_similarity_optimized(current, 15)
        # Return just the filenames without .mp3 extension
        return [sound[2].split('/')[-1].replace('.mp3', '') for sound in similar_sounds]
    except Exception as e:
        print(f"Autocomplete error: {e}")
        return []

async def _get_list_autocomplete(ctx: discord.AutocompleteContext):
    """Autocomplete for sound lists."""
    try:
        db = Database()
        current = ctx.value.lower() if ctx.value else ""
        
        # get all lists
        lists = db.get_sound_lists()
        
        matching_lists = []
        for lst in lists:
            list_name = lst[1]
            creator = lst[2]
            
            # Format: "list_name (by creator)"
            formatted = f"{list_name} (by {creator})"
            
            if current in list_name.lower() or current in creator.lower():
                matching_lists.append(formatted)
        
        # Sort by relevance (exact matches first, then starts with, then contains)
        exact_matches = [name for name in matching_lists if name.lower() == current]
        starts_with = [name for name in matching_lists if name.lower().startswith(current) and name.lower() != current]
        contains = [name for name in matching_lists if current in name.lower() and not name.lower().startswith(current) and name.lower() != current]
        
        # Combine and limit to 25 results
        sorted_results = exact_matches + starts_with + contains
        return sorted_results[:25]
    except Exception as e:
        print(f"List autocomplete error: {e}")
        return []

class ListCog(commands.Cog):
    """Cog for managing sound lists."""
    
    def __init__(self, bot: discord.Bot, behavior):
        self.bot = bot
        self.behavior = behavior
        self.db = Database()
    
    @commands.slash_command(name="createlist", description="Create a new sound list")
    async def create_list(
        self, 
        ctx: discord.ApplicationContext, 
        list_name: Option(str, "Name for your sound list", required=True)
    ):
        """Create a new sound list."""
        # Check if the user already has a list with this name
        existing_list = self.db.get_list_by_name(list_name, ctx.author.name)
        if existing_list:
            await ctx.respond(f"You already have a list named '{list_name}'.", ephemeral=True)
            return
            
        # Create the list
        list_id = self.db.create_sound_list(list_name, ctx.author.name)
        if list_id:
            await ctx.respond(f"Created list '{list_name}'.", ephemeral=True)
            
            # Send a message confirming the creation
            await self.behavior.send_message(
                title="List Created",
                description=f"Created a new sound list: '{list_name}'\nAdd sounds with `/addtolist`."
            )
        else:
            await ctx.respond("Failed to create list.", ephemeral=True)

    @commands.slash_command(name="addtolist", description="Add a sound to a sound list")
    async def add_to_list(
        self, 
        ctx: discord.ApplicationContext, 
        sound: Option(str, "Sound to add to the list", required=True, autocomplete=_get_sound_autocomplete),
        list_name: Option(str, "Name of the list", required=True, autocomplete=_get_list_autocomplete)
    ):
        """Add a sound to a list."""
        # Get the list
        # Handle "List Name (by Creator)" format from autocomplete if necessary, 
        # but DB lookup usually expects just the name if creator isn't specified.
        # But get_list_by_name can take just name.
        
        # Parse the list name if it came from autocomplete
        match = re.match(r'^(.+?) \(by (.+)\)$', list_name)
        actual_name = match.group(1) if match else list_name
        
        sound_list = self.db.get_list_by_name(actual_name)
        if not sound_list:
            await ctx.respond(f"List '{actual_name}' not found.", ephemeral=True)
            return
        
        # Get the sound ID
        # Reuse similarity search logic to find correct sound ID
        similar = self.db.get_sounds_by_similarity(sound, num_results=1)
        if not similar:
             await ctx.respond(f"Sound '{sound}' not found.", ephemeral=True)
             return
             
        soundid = similar[0][1] # Filename 
        # But wait, add_sound_to_list in DB expects sound_filename (the actual encoded filename)
        # get_sounds_by_similarity returns tuple rows from sounds table. 
        # Index 0 is ID, 1 is originalfilename, 2 is Filename. 
        # Looking at DB.add_sound_to_list, it takes list_id and sound_filename.
        # Looking at original code: soundid = db.get_sounds_by_similarity(sound)[0][1]
        
        # Add the sound to the list
        success, message = self.db.add_sound_to_list(sound_list[0], soundid)
        
        if success:
            # Get the list creator for the success message
            list_creator = sound_list[2]
            
            # If the user adding the sound is not the creator, include that in the message
            if list_creator != ctx.author.name:
                await ctx.respond(f"Added sound '{sound}' to {list_creator}'s list '{actual_name}'.", ephemeral=True)
                
                # Optionally notify in the channel about the addition
                await self.behavior.send_message(
                    title=f"Sound Added to List",
                    description=f"{ctx.author.name} added '{sound}' to {list_creator}'s list '{actual_name}'."
                )
            else:
                await ctx.respond(f"Added sound '{sound}' to your list '{actual_name}'.", ephemeral=True)
        else:
            await ctx.respond(f"Failed to add sound to list: {message}", ephemeral=True)
            
    @commands.slash_command(name="removefromlist", description="Remove a sound from one of your lists")
    async def remove_from_list(
        self, 
        ctx: discord.ApplicationContext, 
        sound: Option(str, "Sound to remove from the list", required=True, autocomplete=_get_sound_autocomplete),
        list_name: Option(str, "Name of your list", required=True, autocomplete=_get_list_autocomplete)
    ):
        """Remove a sound from a list."""
        match = re.match(r'^(.+?) \(by (.+)\)$', list_name)
        actual_name = match.group(1) if match else list_name
        
        # Get the list
        sound_list = self.db.get_list_by_name(actual_name)
        if not sound_list:
            await ctx.respond(f"List '{actual_name}' not found.", ephemeral=True)
            return
        
        # Check if the user is the creator of the list
        if sound_list[2] != ctx.author.name:
            await ctx.respond(f"You don't have permission to modify the list '{actual_name}'. Only the creator ({sound_list[2]}) can remove sounds from it.", ephemeral=True)
            return
            
        # Remove the sound from the list
        # Need to find actual filename first potentially? 
        # DB.remove_sound_from_list takes list_id and sound_filename
        # Original code passed 'sound' directly. Let's assume user passes correct name or we need to find it.
        # But if 'sound' comes from autocomplete or free text, it might need resolution.
        # For consistency with add_to_list logic, we might need to resolve it, 
        # BUT remove_sound_from_list expects the stored filename.
        # The user likely types the original/display name.
        
        # Let's try to resolve it to the exact filename in the list if possible
        # Or blindly trust it. The original code blindly passed 'sound'.
        success = self.db.remove_sound_from_list(sound_list[0], sound)
        
        if success:
            await ctx.respond(f"Removed sound '{sound}' from list '{actual_name}'.", ephemeral=True)
        else:
            await ctx.respond("Failed to remove sound from list. Make sure the name is exact.", ephemeral=True)


    @commands.slash_command(name="deletelist", description="Delete one of your sound lists")
    async def delete_list(
        self, 
        ctx: discord.ApplicationContext, 
        list_name: Option(str, "Name of your list", required=True, autocomplete=_get_list_autocomplete)
    ):
        """Delete a sound list."""
        match = re.match(r'^(.+?) \(by (.+)\)$', list_name)
        actual_name = match.group(1) if match else list_name

        # Get the list
        sound_list = self.db.get_list_by_name(actual_name)
        if not sound_list:
            await ctx.respond(f"List '{actual_name}' not found.", ephemeral=True)
            return
        
        # Check if the user is the creator of the list
        if sound_list[2] != ctx.author.name:
            await ctx.respond(f"You don't have permission to delete the list '{actual_name}'. Only the creator ({sound_list[2]}) can delete it.", ephemeral=True)
            return
            
        # Delete the list
        success = self.db.delete_sound_list(sound_list[0])
        if success:
            await ctx.respond(f"Deleted list '{actual_name}'.", ephemeral=True)
            
            # Send a message confirming the deletion
            await self.behavior.send_message(
                title="List Deleted",
                description=f"The list '{actual_name}' has been deleted."
            )
        else:
            await ctx.respond("Failed to delete list.", ephemeral=True)


    @commands.slash_command(name="showlist", description="Display a sound list with buttons")
    async def show_list(
        self, 
        ctx: discord.ApplicationContext, 
        list_name: Option(str, "Name of the list to display", required=True, autocomplete=_get_list_autocomplete)
    ):
        """Display a sound list."""
        # Defer immediately to acknowledge the interaction
        await ctx.defer()
        
        # Parse the list name
        match = re.match(r'^(.+?) \(by (.+)\)$', list_name)
        actual_list_name = match.group(1) if match else list_name
        
        # Get the list
        sound_list = self.db.get_list_by_name(actual_list_name)
        if not sound_list:
            await ctx.followup.send(f"List '{actual_list_name}' not found.", ephemeral=True)
            return
            
        list_id = sound_list[0]
        display_name = sound_list[1]
        
        # Get the sounds in the list
        sounds = self.db.get_sounds_in_list(list_id)
        if not sounds:
            await ctx.followup.send(f"List '{display_name}' is empty.", ephemeral=True)
            return
            
        # Create a paginated view with buttons for each sound
        view = PaginatedSoundListView(self.behavior, list_id, display_name, sounds, ctx.author.name)
        
        # Send a message with the view
        await self.behavior.send_message(
            title=f"Sound List: {display_name} (Page 1/{len(view.pages)})",
            description=f"Contains {len(sounds)} sounds. Showing sounds 1-{min(4, len(sounds))} of {len(sounds)}",
            view=view
        )
        
        # Delete the deferred "thinking..." message
        await ctx.delete()




def setup(bot: discord.Bot, behavior=None):
    if behavior is None:
        raise ValueError("behavior parameter is required for ListCog")
    bot.add_cog(ListCog(bot, behavior))
