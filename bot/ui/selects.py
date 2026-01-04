import discord
import asyncio
from bot.database import Database

class EventTypeSelect(discord.ui.Select):
    def __init__(self, bot_behavior):
        self.bot_behavior = bot_behavior
        options = [
            discord.SelectOption(label="Join Event", value="join", description="Sound plays when user joins voice."),
            discord.SelectOption(label="Leave Event", value="leave", description="Sound plays when user leaves voice."),
        ]
        super().__init__(
            placeholder="Select event type...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="event_type_select"
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        view.selected_event_type = self.values[0]
        await view.update_display_message(interaction)

class UserSelect(discord.ui.Select):
    def __init__(self, bot_behavior, guild_members):
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
            custom_id="user_select"
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        view.selected_user_id = self.values[0]
        await view.update_display_message(interaction)

class SoundSelect(discord.ui.Select):
    def __init__(self, bot_behavior, sounds, row: int = 0):
        self.bot_behavior = bot_behavior
        options = []
        for sound in sounds[:25]:
            options.append(discord.SelectOption(
                label=sound[2].replace('.mp3', '') if sound[2] else str(sound[0]),
                value=sound[2]  # Use Filename
            ))
        super().__init__(
            placeholder="Select a sound to play...",
            options=options,
            row=row
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        sound_filename = self.values[0]
        # We don't strictly need to fetch from DB if we trust the value, but let's verify exists?
        # Actually play_audio handles validation.
        channel = self.bot_behavior._audio_service.get_user_voice_channel(interaction.guild, interaction.user.name)
        if not channel:
            channel = self.bot_behavior._audio_service.get_largest_voice_channel(interaction.guild)
        if channel:
            asyncio.create_task(self.bot_behavior._audio_service.play_audio(channel, sound_filename, interaction.user.name))
            Database().insert_action(interaction.user.name, "select_play_sound", sound_filename)

class AddToListSelect(discord.ui.Select):
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
        success, message = Database().add_sound_to_list(list_id, self.sound_filename)
        if success:
            await interaction.followup.send(f"Added to list '{list_info[1]}'.", ephemeral=True)
        else:
            await interaction.followup.send(f"Failed: {message}", ephemeral=True)

class STSCharacterSelect(discord.ui.Select):
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
        # sts_EL expects (user, sound, char, region)
        asyncio.create_task(self.bot_behavior._voice_transformation_service.sts_EL(interaction.user, self.audio_file, char))
        Database().insert_action(interaction.user.name, "sts_EL", Database().get_sound(self.audio_file, True)[0])

class SimilarSoundsSelect(discord.ui.Select):
    def __init__(self, bot_behavior, similar_sounds, row: int = 3):
        self.bot_behavior = bot_behavior
        options = []
        for sound, similarity in similar_sounds:
            sound_name = sound[2] # Filename index is 2
            options.append(discord.SelectOption(
                label=f"{sound_name.replace('.mp3', '')} ({int(similarity)}%)",
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

class LoadingSimilarSoundsSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Loading similar sounds...",
            min_values=1,
            max_values=1,
            options=[discord.SelectOption(label="Loading...", value="loading")],
            disabled=True,
            row=3, 
        )
