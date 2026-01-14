import discord
from discord.ui import Button
import asyncio
import os
import random
from bot.database import Database

class ReplayButton(Button):
    def __init__(self, bot_behavior, audio_file, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior
        self.audio_file = audio_file
        

    async def callback(self, interaction):
        try:
            await interaction.response.defer()
            channel = interaction.user.voice.channel if interaction.user.voice else None
            if not channel:
                channel = self.bot_behavior._audio_service.get_largest_voice_channel(interaction.guild)
                
            if channel:
                asyncio.create_task(self.bot_behavior._audio_service.play_audio(channel, self.audio_file, interaction.user.name))
                Database().insert_action(interaction.user.name, "replay_sound", Database().get_sounds_by_similarity(self.audio_file)[0][0][0])
            else:
                await interaction.followup.send("No voice channel available! 😭", ephemeral=True)
        except Exception as e:
            print(f"[ReplayButton] Error in callback: {e}")
 
class STSButton(Button):
    def __init__(self, bot_behavior, audio_file, char, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior
        self.audio_file = audio_file
        self.char = char
        

    async def callback(self, interaction):
        await interaction.response.defer()
        # Start the STS process - sts_EL expects (user, sound, char, region)
        asyncio.create_task(self.bot_behavior._voice_transformation_service.sts_EL(interaction.user, self.audio_file, self.char))
        # Record the action
        sound = Database().get_sound(self.audio_file, False)
        if sound:
            Database().insert_action(interaction.user.name, "sts_EL", sound[0])
        # Delete the character selection message
        try:
            await interaction.message.delete()
        except:
            pass  # Message might already be deleted or ephemeral

class IsolateButton(Button):
    def __init__(self, bot_behavior, audio_file, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior
        self.audio_file = audio_file
        

    async def callback(self, interaction):
        await interaction.response.defer()
        asyncio.create_task(self.bot_behavior._audio_service.isolate_voice(interaction.message.channel, self.audio_file))
        similar_sounds = Database().get_sounds_by_similarity(self.audio_file)
        if similar_sounds and similar_sounds[0]:
            Database().insert_action(interaction.user.name, "isolate", similar_sounds[0][0][0])

class FavoriteButton(Button):
    def __init__(self, bot_behavior, audio_file, **kwargs):
        self.bot_behavior = bot_behavior
        self.audio_file = audio_file
        # Always use the star emoji regardless of favorite status
        super().__init__(label="", emoji="⭐", style=discord.ButtonStyle.primary, **kwargs)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        sound = Database().get_sound(self.audio_file, False)
        if not sound:
             await interaction.followup.send("Sound not found in database.", ephemeral=True)
             return
            
        favorite = 1 if not sound[3] else 0
        await Database().update_sound(sound[2], None, favorite)
        
        # Send a message instead of changing the button
        sound_name = sound[2].replace('.mp3', '')
        if favorite == 1:
            await interaction.followup.send(f"Added **{sound_name}** to your favorites! ⭐", ephemeral=True, delete_after=5)
            action_type = "favorite_sound"
        else:
            await interaction.followup.send(f"Removed **{sound_name}** from your favorites!", ephemeral=True, delete_after=5)
            action_type = "unfavorite_sound"
        
        # No need to update the button state or view
        Database().insert_action(interaction.user.name, action_type, sound[0])

# BlacklistButton Removed

class ChangeSoundNameButton(Button):
    def __init__(self, bot_behavior, sound_name, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior
        self.sound_name = sound_name

    async def callback(self, interaction):
        try:
            print(f"ChangeSoundNameButton: Creating modal for sound '{self.sound_name}'")
            # Create and send the modal for changing the sound name
            from bot.ui.modals import ChangeSoundNameModal
            modal = ChangeSoundNameModal(self.bot_behavior, self.sound_name)
            print(f"ChangeSoundNameButton: Modal created successfully")
            await interaction.response.send_modal(modal)
            print(f"ChangeSoundNameButton: Modal sent successfully")
        except Exception as e:
            print(f"ChangeSoundNameButton error: {e}")
            import traceback
            traceback.print_exc()
            try:
                await interaction.response.send_message("Failed to open rename dialog. Please try again.", ephemeral=True)
            except:
                pass

class DownloadSoundButton(Button):
    def __init__(self, bot_behavior, audio_file, **kwargs):
        super().__init__(label="", emoji="⬇️", style=discord.ButtonStyle.primary, **kwargs)
        self.bot_behavior = bot_behavior
        self.audio_file = audio_file

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            # Adjust path since we are now in bot/ui/buttons/
            sound_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "Sounds", self.audio_file))
            if os.path.exists(sound_path):
                await interaction.followup.send(file=discord.File(sound_path), ephemeral=True)
                Database().insert_action(interaction.user.name, "download_sound", self.audio_file)
            else:
                 # Check if the sound exists with its original name (if the filename passed is the original name but renamed in DB)
                sound = Database().get_sound(self.audio_file, False)
                if sound:
                     original_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "Sounds", sound[1]))
                     if os.path.exists(original_path):
                          await interaction.followup.send(file=discord.File(original_path), ephemeral=True)
                          Database().insert_action(interaction.user.name, "download_sound", self.audio_file)
                          return

                await interaction.followup.send("Sound file not found on server.", ephemeral=True)
        except Exception as e:
            print(f"DownloadSoundButton error: {e}")
            await interaction.followup.send("Error sending file.", ephemeral=True)

class PlaySoundButton(Button):
    def __init__(self, bot_behavior, sound_name, **kwargs):
        row = kwargs.pop('row', None)  # Extract row from kwargs
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior
        self.sound_name = sound_name
        if row is not None:
            self.row = row  # Set the row if provided

    async def callback(self, interaction):
        try:
            await interaction.response.defer()
            channel = self.bot_behavior._audio_service.get_user_voice_channel(interaction.guild, interaction.user.name)
            if not channel:
                channel = self.bot_behavior._audio_service.get_largest_voice_channel(interaction.guild)
            if channel:
                asyncio.create_task(self.bot_behavior._audio_service.play_audio(channel, self.sound_name, interaction.user.name))
            else:
                await interaction.followup.send("No voice channel available to play sounds! 😭", ephemeral=True)
        except Exception as e:
            print(f"[PlaySoundButton] Error in callback for '{self.sound_name}': {e}")

class SlapButton(Button):
    def __init__(self, bot_behavior, audio_file, **kwargs):
        self.bot_behavior = bot_behavior
        self.audio_file = audio_file
        self.kwargs = kwargs
        self.update_button_state()

    def update_button_state(self):
        sound = Database().get_sound(self.audio_file, False) # Lookup by Filename
        if sound and sound[6]:  # Check if slap (index 6) matches 1 (True)
            super().__init__(label="👋❌", style=discord.ButtonStyle.primary, **self.kwargs)
        else:
            super().__init__(label="", emoji="👋", style=discord.ButtonStyle.primary, **self.kwargs)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        # Check if user has admin/mod permissions
        if not self.bot_behavior.is_admin_or_mod(interaction.user):
            await interaction.followup.send("Only admins and moderators can add slap sounds! 😤", ephemeral=True)
            return
            
        sound = Database().get_sound(self.audio_file, False)
        if not sound:
             await interaction.followup.send("Sound not found in database.", ephemeral=True)
             return

        slap = 1 if not sound[6] else 0
        await Database().update_sound(sound[2], slap=slap)
        
        # Update the button state
        self.update_button_state()
        
        # Update the entire view
        from bot.ui.views.sounds import SoundBeingPlayedView
        await interaction.message.edit(view=SoundBeingPlayedView(self.bot_behavior, self.audio_file))
        Database().insert_action(interaction.user.name, "slap_sound", sound[0])

class PlaySlapButton(Button):
    def __init__(self, bot_behavior, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction):
        try:
            await interaction.response.defer()
            # Get a random slap sound from the database
            slap_sounds = Database().get_sounds(slap=True, num_sounds=100)
            if slap_sounds:
                random_slap = random.choice(slap_sounds)
                # Use fast silent slap path - stops current audio, plays immediately, no embed
                channel = self.bot_behavior._audio_service.get_user_voice_channel(interaction.guild, interaction.user.name)
                if not channel:
                    channel = self.bot_behavior._audio_service.get_largest_voice_channel(interaction.guild)
                if channel:
                    asyncio.create_task(self.bot_behavior._audio_service.play_slap(
                        channel, random_slap[2], interaction.user.name
                    ))
                    Database().insert_action(interaction.user.name, "play_slap", random_slap[0])
                else:
                    await interaction.followup.send("Join a voice channel first! 👋", ephemeral=True)
            else:
                await interaction.followup.send("No slap sounds found in the database!", ephemeral=True, delete_after=5)
        except Exception as e:
            print(f"[PlaySlapButton] Error in callback: {e}")

class AssignUserEventButton(Button):
    def __init__(self, bot_behavior, audio_file, emoji="👤", style=discord.ButtonStyle.primary, **kwargs):
        super().__init__(label="", emoji=emoji, style=style, custom_id="assign_user_event_button", **kwargs)
        self.bot_behavior = bot_behavior
        self.audio_file = audio_file

    async def callback(self, interaction: discord.Interaction):
        # Fetch non-bot members from the current guild
        guild_members = [
            m for m in interaction.guild.members
            if not m.bot and any(r.name.upper() == "ACTIVE" for r in m.roles)
        ]
        
        if not guild_members:
            await interaction.response.send_message("No users available in this server to assign an event to.", ephemeral=True)
            return

        from bot.ui.views.events import UserEventSelectView
        # Pass interaction_user for SelectDefaultValue pre-selection (Pycord 2.7.0)
        view = UserEventSelectView(
            self.bot_behavior, 
            self.audio_file, 
            guild_members, 
            interaction.user.id,
            interaction_user=interaction.user  # New: enables pre-selection
        )
        initial_message_content = await view.get_initial_message_content()
        
        await interaction.response.send_message(
            content=initial_message_content, 
            view=view, 
            ephemeral=True
        )
        message = await interaction.original_response() 
        view.message_to_edit = message 

class STSCharacterSelectButton(Button):
    def __init__(self, bot_behavior, audio_file, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior
        self.audio_file = audio_file

    async def callback(self, interaction):
        await interaction.response.defer()
        
        # Create a view with buttons for each character
        from discord.ui import View
        view = View(timeout=None)
        view.add_item(STSButton(self.bot_behavior, self.audio_file, "ventura", label="Ventura 🐷", style=discord.ButtonStyle.secondary))
        view.add_item(STSButton(self.bot_behavior, self.audio_file, "tyson", label="Tyson 🐵", style=discord.ButtonStyle.secondary))
        view.add_item(STSButton(self.bot_behavior, self.audio_file, "costa", label="Costa 🐗", style=discord.ButtonStyle.secondary))
        
        # Send a message with the character selection buttons
        await interaction.followup.send(
            content=f"Select a character for Speech-To-Speech with sound '{os.path.basename(self.audio_file).replace('.mp3', '')}':",
            view=view,
            ephemeral=True,
            delete_after=10
        )
        sound = Database().get_sound(self.audio_file, False)
        if sound:
            Database().insert_action(interaction.user.name, "sts_character_select", sound[0])
