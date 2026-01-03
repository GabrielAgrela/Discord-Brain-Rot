import discord
from discord.ui import Button
import asyncio
from bot.database import Database

class ListSoundsButton(Button):
    def __init__(self, bot_behavior, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction):
        await interaction.response.defer()
        asyncio.create_task(self.bot_behavior.list_sounds(user=interaction.user))

class ListLastScrapedSoundsButton(Button):
    def __init__(self, bot_behavior, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction):
        await interaction.response.defer()
        asyncio.create_task(self.bot_behavior.list_sounds(interaction.user, 25))
        Database().insert_action(interaction.user.name, "list_last_scraped_sounds", "")

class SoundListButton(Button):
    def __init__(self, bot_behavior, list_id, list_name, label, **kwargs):
        super().__init__(label=label, style=discord.ButtonStyle.secondary, **kwargs)
        self.bot_behavior = bot_behavior
        self.list_id = list_id
        self.list_name = list_name

    async def callback(self, interaction):
        await interaction.response.defer()
        
        # Get sounds for this list
        sounds = Database().get_sounds_in_list(self.list_id)
        
        if not sounds:
            await interaction.followup.send(f"List '{self.list_name}' is empty.", ephemeral=True)
            return
            
        # Create a paginated view
        from bot.ui.views.lists import PaginatedSoundListView
        view = PaginatedSoundListView(self.bot_behavior, self.list_id, self.list_name, sounds, interaction.user.name)
        
        await interaction.followup.send(
            embed=discord.Embed(
                title=f"Sound List: {self.list_name} (Page 1/{len(view.pages)})",
                description=f"Contains {len(sounds)} sounds. Showing sounds 1-{min(4, len(sounds))} of {len(sounds)}",
                color=discord.Color.blue()
            ),
            view=view,
            ephemeral=True
        )
        Database().insert_action(interaction.user.name, "view_sound_list", str(self.list_id))

class CreateListButton(Button):
    def __init__(self, bot_behavior, **kwargs):
        super().__init__(label="➕ Create New List", style=discord.ButtonStyle.success, **kwargs)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction):
        from bot.ui.modals import CreateListModalWithSoundAdd
        modal = CreateListModalWithSoundAdd(self.bot_behavior)
        await interaction.response.send_modal(modal)

class DeleteListButton(Button):
    def __init__(self, bot_behavior, list_id, list_name, label, style, **kwargs):
        super().__init__(label=label, style=style, **kwargs)
        self.bot_behavior = bot_behavior
        self.list_id = list_id
        self.list_name = list_name

    async def callback(self, interaction):
        success = Database().delete_sound_list(self.list_id, interaction.user.name)
        if success:
            await interaction.response.send_message(f"List '{self.list_name}' deleted.", ephemeral=True)
            try:
                await interaction.message.delete()
            except:
                pass
        else:
            await interaction.response.send_message(f"Failed to delete list. Are you the creator?", ephemeral=True)

class AddToListButton(Button):
    def __init__(self, bot_behavior, sound_filename, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior
        self.sound_filename = sound_filename

    async def callback(self, interaction):
        lists = Database().get_sound_lists()
        if not lists:
            await interaction.response.send_message(
                "There are no sound lists available. Create one with `/createlist`.",
                ephemeral=True
            )
            return
            
        from bot.ui.selects import AddToListSelect
        select = AddToListSelect(self.bot_behavior, self.sound_filename, lists)
        from discord.ui import View
        view = View()
        view.add_item(select)
        
        await interaction.response.send_message(
            "Select a list to add this sound to:",
            view=view,
            ephemeral=True
        )

class SoundListItemButton(Button):
    def __init__(self, bot_behavior, sound_filename, display_name, **kwargs):
        super().__init__(label=display_name, style=discord.ButtonStyle.secondary, **kwargs)
        self.bot_behavior = bot_behavior
        self.sound_filename = sound_filename

    async def callback(self, interaction):
        await interaction.response.defer()
        channel = self.bot_behavior.get_user_voice_channel(interaction.guild, interaction.user.name)
        if not channel:
            channel = self.bot_behavior.get_largest_voice_channel(interaction.guild)
        if channel:
            asyncio.create_task(self.bot_behavior.play_audio(channel, self.sound_filename, interaction.user.name))
        else:
            await interaction.followup.send("No voice channel available! 😭", ephemeral=True)

class RemoveFromListButton(Button):
    def __init__(self, bot_behavior, list_id, list_name, sound_filename, label, style, **kwargs):
        super().__init__(label=label, style=style, **kwargs)
        self.bot_behavior = bot_behavior
        self.list_id = list_id
        self.list_name = list_name
        self.sound_filename = sound_filename

    async def callback(self, interaction):
        success = Database().remove_sound_from_list(self.list_id, self.sound_filename)
        if success:
            await interaction.response.send_message(f"Removed from '{self.list_name}'.", ephemeral=True)
            
            sounds = Database().get_sounds_in_list(self.list_id)
            if not sounds:
                await interaction.message.edit(content=f"List '{self.list_name}' is now empty.", embed=None, view=None)
                return
                
            from bot.ui.views.lists import PaginatedSoundListView
            view = PaginatedSoundListView(self.bot_behavior, self.list_id, self.list_name, sounds, interaction.user.name)
            view.current_page = min(self.view.current_page, len(view.pages) - 1)
            view.update_buttons()
            
            await interaction.message.edit(view=view)
        else:
            await interaction.response.send_message(f"Failed to remove sound.", ephemeral=True)
