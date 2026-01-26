import discord
from discord import ui
import asyncio
import sqlite3
from bot.database import Database


class EventTypeSelect(ui.Select):
    """
    Select for choosing event type (join/leave).
    
    Pycord 2.7.0 Note: StringSelect is a partial helper, not a base class.
    We use ui.Select with select_type parameter for typed behavior.
    Default: "join" is pre-selected since it's the most common use case.
    """
    
    def __init__(self, bot_behavior, row: int = 0):
        self.bot_behavior = bot_behavior
        options = [
            discord.SelectOption(label="Join Event", value="join", description="Sound plays when user joins voice.", default=True),
            discord.SelectOption(label="Leave Event", value="leave", description="Sound plays when user leaves voice."),
        ]
        super().__init__(
            placeholder="Select event type...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="event_type_select",
            row=row
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        view.selected_event_type = self.values[0]
        await view.update_display_message(interaction)


class UserSelectComponent(ui.Select):
    """
    Native Discord user picker using Pycord 2.7.0's UserSelect.
    
    Uses select_type=ComponentType.user_select for the native user picker UI.
    This removes the 25 user limit and provides Discord's built-in user search.
    
    Pycord 2.7.0: Supports default_values to pre-select a user.
    """
    
    def __init__(self, bot_behavior, row: int = 0, default_values: list = None):
        self.bot_behavior = bot_behavior
        super().__init__(
            select_type=discord.ComponentType.user_select,
            placeholder="Select a user...",
            min_values=1,
            max_values=1,
            row=row,
            default_values=default_values or []
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        # values is a list of User/Member objects with the native UserSelect
        selected_user = self.values[0]
        view.selected_user_id = f"{selected_user.name}#{selected_user.discriminator}"
        view.selected_user = selected_user
        await view.update_display_message(interaction)


# Keep the old UserSelect as an alias for backwards compatibility during transition
class UserSelect(ui.Select):
    """Legacy user select - kept for compatibility, prefer UserSelectComponent."""
    
    def __init__(self, bot_behavior, guild_members, row: int = 0):
        self.bot_behavior = bot_behavior
        options = []
        for member in guild_members[:25]:
            if not member.bot:
                options.append(discord.SelectOption(
                    label=f"{member.name}#{member.discriminator}",
                    value=f"{member.name}#{member.discriminator}"
                ))
        super().__init__(
            placeholder="Select a user...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="user_select",
            row=row
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        view.selected_user_id = self.values[0]
        await view.update_display_message(interaction)


class SoundSelect(ui.Select):
    """Select for choosing a sound to play."""
    
    def __init__(self, bot_behavior, sounds, row: int = 0):
        self.bot_behavior = bot_behavior
        options = []
        for sound in sounds[:25]:
            # sound can be a tuple or Row, handle both
            filename = sound['Filename'] if isinstance(sound, sqlite3.Row) else sound[2]
            label = filename.replace('.mp3', '')
            if len(label) > 80:
                label = label[:77] + "..."
            options.append(discord.SelectOption(
                label=label,
                value=filename
            ))
        super().__init__(
            placeholder="Select a sound to play...",
            options=options,
            row=row
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        sound_filename = self.values[0]
        channel = self.bot_behavior._audio_service.get_user_voice_channel(interaction.guild, interaction.user.name)
        if not channel:
            channel = self.bot_behavior._audio_service.get_largest_voice_channel(interaction.guild)
        if channel:
            asyncio.create_task(self.bot_behavior._audio_service.play_audio(channel, sound_filename, interaction.user.name))
            Database().insert_action(interaction.user.name, "select_play_sound", sound_filename)


class AddToListSelect(ui.Select):
    """Select for adding a sound to a list."""
    
    def __init__(self, bot_behavior, sound_filename, lists, default_list_id: int = None, row: int = 0):
        self.bot_behavior = bot_behavior
        self.sound_filename = sound_filename
        options = []
        options.append(discord.SelectOption(
            label="➕ Create New List",
            value="create_new_list",
            description="Create a new sound list"
        ))
        for list_info in lists[:24]:
            list_id = list_info[0]
            option = discord.SelectOption(
                label=f"{list_info[1]} (by {list_info[2]})",
                value=str(list_id)
            )
            if default_list_id is not None and list_id == default_list_id:
                option.default = True
            options.append(option)
        super().__init__(
            placeholder="Add this sound to a list",
            min_values=1,
            max_values=1,
            options=options,
            row=row
        )

    async def callback(self, interaction):
        if self.values[0] == "create_new_list":
            from bot.ui.modals import CreateListModalWithSoundAdd
            modal = CreateListModalWithSoundAdd(self.bot_behavior, self.sound_filename)
            await interaction.response.send_modal(modal)
            return
            
        await interaction.response.defer()
        list_id = int(self.values[0])
        list_info = Database().get_sound_list(list_id)
        if not list_info:
            await interaction.followup.send("List not found.", ephemeral=True)
            return
        success = Database().add_sound_to_list(list_id, self.sound_filename)
        if success:
            await interaction.followup.send(f"Added to list '{list_info[1]}'.", ephemeral=True)
        else:
            await interaction.followup.send(f"Sound is already in list '{list_info[1]}'.", ephemeral=True)


class STSCharacterSelect(ui.Select):
    """Select for voice character transformation."""
    
    def __init__(self, bot_behavior, audio_file, row: int = 0):
        self.bot_behavior = bot_behavior
        self.audio_file = audio_file
        options = [
            discord.SelectOption(label="Ventura 🐷", value="ventura"),
            discord.SelectOption(label="Tyson 🐵", value="tyson"),
            discord.SelectOption(label="Costa 🐗", value="costa"),
        ]
        super().__init__(
            placeholder="Change sound voice",
            min_values=1,
            max_values=1,
            options=options,
            row=row
        )

    async def callback(self, interaction):
        await interaction.response.defer()
        char = self.values[0]
        asyncio.create_task(self.bot_behavior._voice_transformation_service.sts_EL(interaction.user, self.audio_file, char))
        Database().insert_action(interaction.user.name, "sts_EL", Database().get_sound(self.audio_file, True)[0])


class SimilarSoundsSelect(ui.Select):
    """Select for playing similar sounds."""
    
    def __init__(self, bot_behavior, similar_sounds, row: int = 3):
        self.bot_behavior = bot_behavior
        options = []
        for sound, similarity in similar_sounds:
            # sound is the sound_data (already unpacked from tuple)
            # Check if it's a Row/dict or a tuple
            if isinstance(sound, (sqlite3.Row, dict)):
                sound_name = sound['Filename']
            else:
                # It's a tuple, filename is at index 2
                sound_name = sound[2]
            label = f"{sound_name.replace('.mp3', '')} ({int(similarity)}%)"
            if len(label) > 80:
                # Truncate while keeping the similarity percentage
                suffix = f" ({int(similarity)}%)"
                label = sound_name.replace('.mp3', '')[:80-len(suffix)-3] + "..." + suffix
            options.append(discord.SelectOption(
                label=label,
                value=sound_name
            ))
        super().__init__(
            placeholder="Try similar sounds...",
            options=options,
            row=row
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        sound_name = self.values[0]
        channel = self.bot_behavior._audio_service.get_user_voice_channel(interaction.guild, interaction.user.name)
        if not channel:
            channel = self.bot_behavior._audio_service.get_largest_voice_channel(interaction.guild)
        if channel:
            asyncio.create_task(self.bot_behavior._audio_service.play_audio(channel, sound_name, interaction.user.name))
            Database().insert_action(interaction.user.name, "select_similar_sound", sound_name)


class LoadingSimilarSoundsSelect(ui.Select):
    """Placeholder select shown while similar sounds are loading."""
    
    def __init__(self):
        super().__init__(
            placeholder="Loading similar sounds...",
            min_values=1,
            max_values=1,
            options=[discord.SelectOption(label="Loading...", value="loading")],
            disabled=True,
            row=3,
        )

