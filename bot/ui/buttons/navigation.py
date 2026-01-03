import discord
from discord.ui import Button

class PaginationButton(Button):
    def __init__(self, label, emoji, style, custom_id, row):
        super().__init__(label=label, emoji=emoji, style=style, custom_id=custom_id, row=row)

    async def callback(self, interaction):
        await interaction.response.defer()
        view = self.view
        
        # Check if these are user favorites or all favorites based on the title
        is_user_favorites = "My Favorites" in interaction.message.embeds[0].title or "'s Favorites" in interaction.message.embeds[0].title
        
        # Only check ownership for user-specific favorites
        if is_user_favorites and interaction.user.name != view.owner:
            await interaction.followup.send("Only the user who requested the favorites can navigate through pages! 😤", ephemeral=True)
            return
            
        if self.custom_id == "previous":
            # If on first page and going previous, wrap to last page
            if view.current_page == 0:
                view.current_page = len(view.pages) - 1
            else:
                view.current_page = view.current_page - 1
        elif self.custom_id == "next":
            # If on last page and going next, wrap to first page
            if view.current_page == len(view.pages) - 1:
                view.current_page = 0
            else:
                view.current_page = view.current_page + 1
        
        # Update buttons state
        view.update_buttons()
        await interaction.message.edit(view=view)

class SoundListPaginationButton(Button):
    def __init__(self, label, emoji, style, custom_id, row):
        super().__init__(label=label, emoji=emoji, style=style, custom_id=custom_id, row=row)

    async def callback(self, interaction):
        await interaction.response.defer()
        view = self.view
        
        # Check if the user who clicked is the owner of the view
        if interaction.user.name != view.owner:
            await interaction.followup.send("Only the user who opened this list can navigate through pages! 😤", ephemeral=True)
            return
            
        if self.custom_id == "previous":
            # If on first page and going previous, wrap to last page
            if view.current_page == 0:
                view.current_page = len(view.pages) - 1
            else:
                view.current_page = view.current_page - 1
        elif self.custom_id == "next":
            # If on last page and going next, wrap to first page
            if view.current_page == len(view.pages) - 1:
                view.current_page = 0
            else:
                view.current_page = view.current_page + 1
        
        # Update buttons state
        view.update_buttons()
        
        # Update both the content and description
        total_sounds = sum(len(page) for page in view.pages)
        current_page_start = (view.current_page * 4) + 1
        current_page_end = min((view.current_page + 1) * 4, total_sounds)
        
        await interaction.message.edit(
            content=None,
            embed=discord.Embed(
                title=f"Sound List: {view.list_name} (Page {view.current_page + 1}/{len(view.pages)})",
                description=f"Contains {total_sounds} sounds. Showing sounds {current_page_start}-{current_page_end} of {total_sounds}",
                color=discord.Color.blue()
            ),
            view=view
        )
class EventPaginationButton(Button):
    def __init__(self, label, emoji, style, custom_id, row):
        super().__init__(label=label, emoji=emoji, style=style, custom_id=custom_id, row=row)

    async def callback(self, interaction):
        await interaction.response.defer()
        view = self.view
        
        if self.custom_id == "previous":
            if view.current_page == 0:
                view.current_page = len(view.pages) - 1
            else:
                view.current_page = view.current_page - 1
        elif self.custom_id == "next":
            if view.current_page == len(view.pages) - 1:
                view.current_page = 0
            else:
                view.current_page = view.current_page + 1
        
        view.update_buttons()
        
        total_events = sum(len(page) for page in view.pages)
        current_page_start = (view.current_page * 20) + 1
        current_page_end = min((view.current_page + 1) * 20, total_events)
        
        description = "**Current sounds:**\n"
        description += "\n".join([f"• {event[2]}" for event in view.pages[view.current_page]])
        description += f"\nShowing sounds {current_page_start}-{current_page_end} of {total_events}"
        
        await interaction.message.edit(
            embed=discord.Embed(
                title=f"🎵 {view.event.capitalize()} Event Sounds for {view.user_id.split('#')[0]} (Page {view.current_page + 1}/{len(view.pages)})",
                description=description,
                color=discord.Color.blue()
            ),
            view=view
        )
