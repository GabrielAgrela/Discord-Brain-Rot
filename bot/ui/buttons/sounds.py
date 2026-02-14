import discord
from discord.ui import Button
import asyncio
import os
import random
from bot.database import Database

class ReplayButton(Button):
    def __init__(self, bot_behavior, audio_file, is_tts=False, original_message="", sts_char=None, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior
        self.audio_file = audio_file
        self.is_tts = is_tts
        self.original_message = original_message
        self.sts_char = sts_char
        

    async def callback(self, interaction):
        print(f"DEBUG: ReplayButton.callback called by {interaction.user.name} for {self.audio_file}")
        await replay_sound(
            bot_behavior=self.bot_behavior,
            interaction=interaction,
            audio_file=self.audio_file,
            is_tts=self.is_tts,
            original_message=self.original_message,
            sts_char=self.sts_char
        )
 
class STSButton(Button):
    def __init__(self, bot_behavior, audio_file, char, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior
        self.audio_file = audio_file
        self.char = char
        

    async def callback(self, interaction):
        await interaction.response.defer()
        
        # Get avatar URL and character thumbnail
        avatar = getattr(interaction.user, "display_avatar", None)
        requester_avatar_url = str(avatar.url) if avatar else None
        
        from config import TTS_PROFILES
        profile = TTS_PROFILES.get(self.char, {})
        sts_thumbnail_url = profile.get("thumbnail")
        
        # Send loading card
        import io
        bot_channel = self.bot_behavior._message_service.get_bot_channel(interaction.guild)
        loading_message = None
        if bot_channel:
            image_bytes = self.bot_behavior._audio_service.image_generator.generate_loading_card(
                title="Processing...",
                subtitle="Generating audio, please wait"
            )
            if image_bytes:
                file = discord.File(io.BytesIO(image_bytes), filename="loading_card.png")
                loading_message = await bot_channel.send(file=file)
        
        # Start the STS process
        asyncio.create_task(self.bot_behavior._voice_transformation_service.sts_EL(
            interaction.user, self.audio_file, self.char,
            loading_message=loading_message,
            requester_avatar_url=requester_avatar_url,
            sts_thumbnail_url=sts_thumbnail_url
        ))
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
        print(f"DEBUG: FavoriteButton.callback called by {interaction.user.name} for {self.audio_file}")
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
                # Log the action
                sound = Database().get_sound(self.sound_name, False)
                if sound:
                    Database().insert_action(interaction.user.name, "play_similar_sound", sound[0])
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
        print(f"DEBUG: SlapButton.callback called by {interaction.user.name} for {self.audio_file}")
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
        await play_random_slap(self.bot_behavior, interaction)


async def play_random_slap(bot_behavior, interaction: discord.Interaction):
    """Play a random slap sound using the standard slap button flow."""
    try:
        await interaction.response.defer()
        # Get a random slap sound from the database
        slap_sounds = Database().get_sounds(slap=True, num_sounds=100)
        if slap_sounds:
            random_slap = random.choice(slap_sounds)
            # Use fast silent slap path - stops current audio, plays immediately, no embed
            channel = bot_behavior._audio_service.get_user_voice_channel(interaction.guild, interaction.user.name)
            if not channel:
                channel = bot_behavior._audio_service.get_largest_voice_channel(interaction.guild)
            if channel:
                asyncio.create_task(bot_behavior._audio_service.play_slap(
                    channel, random_slap[2], interaction.user.name
                ))
                Database().insert_action(interaction.user.name, "play_slap", random_slap[0])
            else:
                await interaction.followup.send("Join a voice channel first! 👋", ephemeral=True)
        else:
            await interaction.followup.send("No slap sounds found in the database!", ephemeral=True, delete_after=5)
    except Exception as e:
        print(f"[PlaySlapButton] Error in callback: {e}")


async def replay_sound(
    bot_behavior,
    interaction: discord.Interaction,
    audio_file: str,
    is_tts: bool = False,
    original_message: str = "",
    sts_char: str = None
):
    """Replay a specific sound using the same behavior as ReplayButton."""
    try:
        await interaction.response.defer()
        channel = interaction.user.voice.channel if interaction.user.voice else None
        if not channel:
            channel = bot_behavior._audio_service.get_largest_voice_channel(interaction.guild)

        if channel:
            # Get avatar URL for the card
            avatar = getattr(interaction.user, "display_avatar", None)
            requester_avatar_url = str(avatar.url) if avatar else None

            # If STS, include the STS thumbnail
            sts_thumbnail_url = None
            if sts_char:
                from config import TTS_PROFILES
                profile = TTS_PROFILES.get(sts_char, {})
                sts_thumbnail_url = profile.get("thumbnail")

            asyncio.create_task(bot_behavior._audio_service.play_audio(
                channel, audio_file, interaction.user.name,
                is_tts=is_tts,
                original_message=original_message,
                sts_char=sts_char,
                requester_avatar_url=requester_avatar_url,
                sts_thumbnail_url=sts_thumbnail_url
            ))
            sound_data = Database().get_sounds_by_similarity(audio_file)
            if sound_data and sound_data[0]:
                Database().insert_action(interaction.user.name, "replay_sound", sound_data[0][0]['id'])
        else:
            await interaction.followup.send("No voice channel available! 😭", ephemeral=True)
    except Exception as e:
        print(f"[ReplayButton] Error in callback: {e}")


class ProgressSlapButton(Button):
    """Progress bar button that keeps color and triggers a slap when clicked."""
    def __init__(
        self,
        bot_behavior,
        audio_file: str,
        is_tts: bool = False,
        original_message: str = "",
        sts_char: str = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior
        self.audio_file = audio_file
        self.is_tts = is_tts
        self.original_message = original_message
        self.sts_char = sts_char

    async def callback(self, interaction: discord.Interaction):
        label = self.label or ""
        is_stopped_state = label.startswith(("✅", "⏭️", "👋", "⏹️", "⏸️"))

        if is_stopped_state:
            await replay_sound(
                bot_behavior=self.bot_behavior,
                interaction=interaction,
                audio_file=self.audio_file,
                is_tts=self.is_tts,
                original_message=self.original_message,
                sts_char=self.sts_char
            )
            return

        await play_random_slap(self.bot_behavior, interaction)

class AssignUserEventButton(Button):
    def __init__(self, bot_behavior, audio_file, emoji="👤", style=discord.ButtonStyle.primary, **kwargs):
        super().__init__(label="", emoji=emoji, style=style, custom_id="assign_user_event_button", **kwargs)
        self.bot_behavior = bot_behavior
        self.audio_file = audio_file

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        # Fetch non-bot members from the current guild
        guild_members = [
            m for m in interaction.guild.members
            if not m.bot and any(r.name.upper() == "ACTIVE" for r in m.roles)
        ]
        
        if not guild_members:
            await interaction.followup.send("No users available in this server to assign an event to.", ephemeral=True)
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
        
        await interaction.followup.send(
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
class ToggleControlsButton(Button):
    def __init__(self, **kwargs):
        # Extract initial state from view if possible
        label = kwargs.pop('label', "")
        emoji = kwargs.pop('emoji', "👁️")
        super().__init__(label="", emoji=emoji, style=discord.ButtonStyle.primary, **kwargs)

    async def callback(self, interaction: discord.Interaction):
        # Toggle the state in the view
        view = self.view
        if view is None:
            return
            
        if not hasattr(view, 'show_controls'):
            view.show_controls = False
        
        view.show_controls = not view.show_controls
        
        # Lazy load similar sounds if expanding
        if view.show_controls:
            # Initialize similar_sounds if not present
            if not hasattr(view, 'similar_sounds'):
                view.similar_sounds = None
                
            # Fetch if not cached
            if not view.similar_sounds:
                try:
                    # Use asyncio.to_thread for database operation
                    # Note: We need to import the Database class here or ensure it's available
                    from bot.database import Database
                    # Request slightly more than we display to have variety if needed, but select component uses its own limit
                    similar_data = await asyncio.to_thread(Database().get_sounds_by_similarity, view.audio_file)
                    
                    # Filter out the current sound itself
                    import sqlite3
                    filtered_data = []
                    for s in similar_data:
                         sound_data = s[0]
                         if isinstance(sound_data, (sqlite3.Row, dict)):
                             filename = sound_data['Filename']
                         else:
                             filename = sound_data[2]
                             
                         if filename != view.audio_file:
                             filtered_data.append(s)
                             
                    view.similar_sounds = filtered_data
                except Exception as e:
                     print(f"[ToggleControlsButton] Error lazy loading similar sounds: {e}")
                     view.similar_sounds = []

        # Update button appearance (Icon only ✅)
        # Update emoji
        self.emoji = "🔼" if view.show_controls else "🔽"
            
        # Re-setup the view items based on the new state
        if hasattr(view, '_setup_items'):
            view._setup_items()
            await interaction.response.edit_message(view=view)
            
            # Ensure view has message reference for auto-close
            if not getattr(view, 'message', None):
                view.message = interaction.message
                
            # Manage auto-close timer
            if view.show_controls:
                if hasattr(view, 'start_auto_close_task'):
                    view.start_auto_close_task()
            else:
                 # Cancel task if manually closed
                 if hasattr(view, 'auto_close_task') and view.auto_close_task:
                     view.auto_close_task.cancel()
        else:
            await interaction.response.defer()

class SendControlsButton(Button):
    """Button to send main controls as a separate message."""
    def __init__(self, **kwargs):
        super().__init__(label="", emoji="⚙️", style=discord.ButtonStyle.primary, **kwargs)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        view = self.view
        if hasattr(view, 'bot_behavior') and view.bot_behavior:
            from bot.ui.views.controls import ControlsView
            # Send controls as standalone ephemeral message - only visible to the user who clicked
            await interaction.followup.send(
                view=ControlsView(view.bot_behavior),
                ephemeral=True,
                delete_after=10
            )
        else:
            await interaction.followup.send("Error: Bot behavior not found.", ephemeral=True)
