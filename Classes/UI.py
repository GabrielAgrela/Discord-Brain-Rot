from datetime import datetime
import random
from discord.ui import Button, View
import discord
import asyncio
import os
from Classes.Database import Database
import re



class ReplayButton(Button):
    def __init__(self, bot_behavior, audio_file, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior
        self.audio_file = audio_file
        

    async def callback(self, interaction):
        await interaction.response.defer()
        asyncio.create_task(self.bot_behavior.play_audio(interaction.user.voice.channel, self.audio_file, interaction.user.name))
        Database().insert_action(interaction.user.name, "replay_sound", Database().get_sounds_by_similarity(self.audio_file)[0][0])

class STSButton(Button):
    def __init__(self, bot_behavior, audio_file, char, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior
        self.audio_file = audio_file
        self.char = char
        

    async def callback(self, interaction):
        await interaction.response.defer()
        # Start the STS process
        asyncio.create_task(self.bot_behavior.sts_EL(interaction.message.channel, self.audio_file, self.char))
        # Record the action
        Database().insert_action(interaction.user.name, "sts_EL", Database().get_sound(self.audio_file, True)[0])
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
        asyncio.create_task(self.bot_behavior.isolate_voice(interaction.message.channel, self.audio_file))
        Database().insert_action(interaction.user.name, "isolate", Database().get_sounds_by_similarity(self.audio_file)[0][0])

class FavoriteButton(Button):
    def __init__(self, bot_behavior, audio_file):
        self.bot_behavior = bot_behavior
        self.audio_file = audio_file
        # Always use the star emoji regardless of favorite status
        super().__init__(label="", emoji="⭐", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        sound = Database().get_sound(self.audio_file, True)
        favorite = 1 if not sound[3] else 0
        await Database().update_sound(sound[2], None, favorite)
        
        # Send a message instead of changing the button
        sound_name = sound[2].replace('.mp3', '')
        if favorite == 1:
            await interaction.followup.send(f"Added **{sound_name}** to your favorites! ⭐", ephemeral=True, delete_after=5)
            action_type = "favorite_sound"
        else:
            await interaction.followup.send(f"Removed **{sound_name}** from your favorites!", ephemeral=True, delete_after=5)
        
        # No need to update the button state or view
        Database().insert_action(interaction.user.name, action_type, sound[0])

class BlacklistButton(Button):

    def __init__(self, bot_behavior, audio_file):
        self.bot_behavior = bot_behavior
        self.audio_file = audio_file
        self.update_button_state()

    def update_button_state(self):
        if Database().get_sound(self.audio_file, True)[4]:  # Check if blacklisted (index 4)
            super().__init__(label="🗑️❌", style=discord.ButtonStyle.primary)
        else:
            super().__init__(label="", emoji="🗑️", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        sound = Database().get_sound(self.audio_file, True)
        blacklist = 1 if not sound[4] else 0
        await Database().update_sound(sound[2], None, None, blacklist)

        
        # Update the button state
        self.update_button_state()
        
        # Update the entire view
        await interaction.message.edit(view=SoundBeingPlayedView(self.bot_behavior, self.audio_file))
        Database().insert_action(interaction.user.name, "blacklist_sound", sound[0])

class ChangeSoundNameButton(Button):
    def __init__(self, bot_behavior, sound_name, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior
        self.sound_name = sound_name

    async def callback(self, interaction):
        try:
            print(f"ChangeSoundNameButton: Creating modal for sound '{self.sound_name}'")
            # Create and send the modal for changing the sound name
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

# New User Event Assignment Components Start

class EventTypeSelect(discord.ui.Select):
    def __init__(self, bot_behavior):
        self.bot_behavior = bot_behavior
        options = [
            discord.SelectOption(label="Join Event", value="join", description="Sound plays when user joins voice."),
            discord.SelectOption(label="Leave Event", value="leave", description="Sound plays when user leaves voice.")
        ]
        super().__init__(
            placeholder="Select event type...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="event_type_select"
        )

    async def callback(self, interaction: discord.Interaction):
        # Store selection on the view for the confirm button to access
        self.view.selected_event_type = self.values[0]
        await interaction.response.defer() # Acknowledge this select interaction
        # Update the main message
        await self.view.update_display_message(interaction)


class UserSelect(discord.ui.Select):
    def __init__(self, bot_behavior, guild_members):
        self.bot_behavior = bot_behavior
        options = []
        for member in guild_members[:25]: # Discord limits to 25 options
            if not member.bot: # Exclude bots
                options.append(discord.SelectOption(
                    label=member.display_name,
                    value=f"{member.name}#{member.discriminator}",
                    description=f"ID: {member.id}"
                ))
        
        if not options: # Handle case where no non-bot members are found (e.g. only bots in a small server)
             options.append(discord.SelectOption(label="No users available", value="no_users", disabled=True))


        super().__init__(
            placeholder="Select user...",
            min_values=1,
            max_values=1,
            options=options if options else [discord.SelectOption(label="No users found", value="dummy_no_user", disabled=True)], # Ensure options is never empty
            custom_id="user_select"
        )

    async def callback(self, interaction: discord.Interaction):
        # Store selection on the view for the confirm button to access
        if self.values and self.values[0] != "no_users" and self.values[0] != "dummy_no_user":
            self.view.selected_user_id = self.values[0]
        else:
            self.view.selected_user_id = None # Clear if invalid selection
        await interaction.response.defer() # Acknowledge this select interaction
        # Update the main message
        await self.view.update_display_message(interaction)


class ConfirmUserEventButton(Button):
    def __init__(self, bot_behavior, audio_file, **kwargs):
        super().__init__(label="Confirm", style=discord.ButtonStyle.success, custom_id="confirm_user_event", **kwargs)
        self.bot_behavior = bot_behavior
        self.audio_file = audio_file

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True) # Defer with ephemeral for followup

        event_type_select = self.view.event_type_select
        user_select = self.view.user_select
        
        selected_event_type = getattr(self.view, 'selected_event_type', None)
        selected_user_id_for_db = getattr(self.view, 'selected_user_id', None) # This is "name#discriminator"

        if not selected_event_type:
            await interaction.followup.send("Please select an event type.", ephemeral=True)
            return
        if not selected_user_id_for_db:
            await interaction.followup.send("Please select a user.", ephemeral=True)
            return

        # Permission Check
        acting_user_full_name = f"{interaction.user.name}#{interaction.user.discriminator}"
        is_admin = self.bot_behavior.is_admin_or_mod(interaction.user)
        is_self_assign = (acting_user_full_name == selected_user_id_for_db)

        if not (is_self_assign or is_admin):
            user_display_name_target = selected_user_id_for_db.split('#')[0]
            await interaction.followup.send(
                f"You do not have permission to assign an event for {user_display_name_target}. Admins can assign to any user, and users can assign to themselves.",
                ephemeral=True
            )
            # Edit original message to remove components after action
            if self.view.message_to_edit: # Check if message_to_edit exists
                try:
                    await self.view.message_to_edit.edit(content=f"Permission denied for event assignment to {user_display_name_target}.", view=None)
                except discord.NotFound:
                    print(f"ConfirmUserEventButton: message_to_edit (ID: {self.view.message_to_edit.id}) not found for permission denial edit.")
                except Exception as e:
                    print(f"ConfirmUserEventButton: Error editing message_to_edit on permission denial: {e}")
            return

        sound_name = self.audio_file.split('/')[-1].replace('.mp3', '')
        
        # Check current status for the message
        is_set = Database().get_user_event_sound(selected_user_id_for_db, selected_event_type, sound_name)
        
        success = Database().toggle_user_event_sound(selected_user_id_for_db, selected_event_type, sound_name)

        if success:
            action_message = "Removed" if is_set else "Added"
            user_display_name = selected_user_id_for_db.split('#')[0]
            # Edit original message to remove components after action and reflect the outcome - this is now the single final message
            final_content_message = f"{action_message} '{sound_name}' as {selected_event_type} sound for {user_display_name}."
            if self.view.message_to_edit: # Check if message_to_edit exists
                try:
                    await self.view.message_to_edit.edit(content=final_content_message, view=None)
                except discord.NotFound:
                    print(f"ConfirmUserEventButton: message_to_edit (ID: {self.view.message_to_edit.id}) not found for edit.")
                except Exception as e:
                    print(f"ConfirmUserEventButton: Error editing message_to_edit on failure: {e}")
        else:
            await interaction.followup.send("Failed to update event sound. Please try again.", ephemeral=True)
            user_display_name = selected_user_id_for_db.split('#')[0]
            final_content_message = f"Failed to process event assignment for '{sound_name}' to {user_display_name}."
            if self.view.message_to_edit: # Check if message_to_edit exists
                try:
                    await self.view.message_to_edit.edit(content=final_content_message, view=None)
                except discord.NotFound:
                    print(f"ConfirmUserEventButton: message_to_edit (ID: {self.view.message_to_edit.id}) not found for failure edit.")
                except Exception as e:
                    print(f"ConfirmUserEventButton: Error editing message_to_edit on failure: {e}")


class CancelButton(Button):
    def __init__(self, **kwargs):
        super().__init__(label="Cancel", style=discord.ButtonStyle.grey, custom_id="cancel_user_event", **kwargs)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if self.view.message_to_edit: # Check if message_to_edit exists
            try:
                await self.view.message_to_edit.delete()
            except discord.NotFound:
                print(f"CancelButton: message_to_edit (ID: {self.view.message_to_edit.id}) not found for delete.")
            except Exception as e:
                print(f"CancelButton: Error deleting message_to_edit: {e}")
        # Fallback or alternative if message_to_edit is None (though it shouldn't be with the new flow)
        # await interaction.message.delete() # This would be the problematic one


class UserEventSelectView(View):
    def __init__(self, bot_behavior, audio_file, guild_members, interaction_user_id, message_to_edit=None):
        super().__init__(timeout=180)
        self.bot_behavior = bot_behavior
        self.audio_file = audio_file
        self.sound_name_no_ext = audio_file.split('/')[-1].replace('.mp3', '')
        self.interaction_user_id = interaction_user_id
        self.message_to_edit = message_to_edit # Store the message reference

        self.selected_event_type = None
        self.selected_user_id = None

        self.event_type_select = EventTypeSelect(bot_behavior)
        self.user_select = UserSelect(bot_behavior, guild_members)
        self.confirm_button = ConfirmUserEventButton(bot_behavior, audio_file)
        self.cancel_button = CancelButton()

        self.add_item(self.event_type_select)
        self.add_item(self.user_select)
        self.add_item(self.confirm_button)
        self.add_item(self.cancel_button)

    async def get_initial_message_content(self):
        return f"Assigning event for sound: **{self.sound_name_no_ext}**\n"

    async def update_display_message(self, interaction_from_select: discord.Interaction):
        new_content = f"Assigning event for sound: **{self.sound_name_no_ext}**\n"
        
        if self.selected_event_type and self.selected_user_id:
            is_set = Database().get_user_event_sound(self.selected_user_id, self.selected_event_type, self.sound_name_no_ext)
            action_preview_text = "REMOVE" if is_set else "ADD"
            user_display_name_target = self.selected_user_id.split('#')[0]
            
            new_content += (f"\n **{action_preview_text}** this sound "
                            f"as a **{self.selected_event_type}** event for **{user_display_name_target}**.")
        else:
            if not self.selected_event_type and not self.selected_user_id:
                 new_content += "Please select an event type and a user."
            elif not self.selected_event_type:
                new_content += "Please select an event type."
            elif not self.selected_user_id:
                new_content += "Please select a user."
        
        try:
            if self.message_to_edit: # Check if message_to_edit exists
                # Set defaults for EventTypeSelect before editing
                for option in self.event_type_select.options:
                    option.default = (self.selected_event_type is not None and option.value == self.selected_event_type)

                # Set defaults for UserSelect before editing
                for option in self.user_select.options:
                    option.default = (self.selected_user_id is not None and option.value == self.selected_user_id)
                
                await self.message_to_edit.edit(content=new_content, view=self)
            else:
                print("UserEventSelectView.update_display_message: self.message_to_edit is None. Cannot edit.")
        except discord.NotFound:
            print(f"UserEventSelectView.update_display_message: Stored message (ID: {self.message_to_edit.id if self.message_to_edit else 'Unknown'}) not found. It might have been deleted.")
        except Exception as e:
            print(f"UserEventSelectView.update_display_message: Error editing message: {e}")


    # Optional: Interaction check to ensure only the user who clicked the initial button can interact
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.interaction_user_id:
            await interaction.response.send_message("You cannot interact with this menu.", ephemeral=True)
            return False
        return True
    
    async def on_timeout(self):
        # Optionally disable components or send a message when the view times out
        for item in self.children:
            item.disabled = True
        # Check if the message still exists before trying to edit
        if self.message_to_edit:
            try:
                await self.message_to_edit.edit(content=f"Event assignment for '{self.sound_name_no_ext}' timed out.", view=self)
            except discord.NotFound:
                print(f"UserEventSelectView.on_timeout: Stored message (ID: {self.message_to_edit.id}) not found for timeout edit.")
                pass # Message already deleted or gone
            except Exception as e:
                print(f"UserEventSelectView.on_timeout: Error editing message on timeout: {e}")


class AssignUserEventButton(Button):
    def __init__(self, bot_behavior, audio_file, emoji="👤", style=discord.ButtonStyle.primary, **kwargs):
        super().__init__(label="", emoji=emoji, style=style, custom_id="assign_user_event_button", **kwargs)
        self.bot_behavior = bot_behavior
        self.audio_file = audio_file

    async def callback(self, interaction: discord.Interaction):
        # Fetch non-bot members from the current guild
        guild_members = [m for m in interaction.guild.members if not m.bot]
        
        if not guild_members:
            await interaction.response.send_message("No users available in this server to assign an event to.", ephemeral=True)
            return

        view = UserEventSelectView(self.bot_behavior, self.audio_file, guild_members, interaction.user.id)
        initial_message_content = await view.get_initial_message_content()
        
        # Send the message and get the InteractionMessage object
        # This requires interaction.response.send_message to be awaited if it returns the message.
        # If it returns None, or we need original_response, this approach might need adjustment.
        # For now, assuming followup is needed to get the message object if send_message doesn't return it directly.
        await interaction.response.send_message(
            content=initial_message_content, 
            view=view, 
            ephemeral=True
        )
        message = await interaction.original_response() # Fetch the message we just sent
        view.message_to_edit = message # Assign it to the view instance

# New User Event Assignment Components End

class UploadSoundModal(discord.ui.Modal):
    def __init__(self, bot_behavior):
        super().__init__(title="Upload Sound")
        self.bot_behavior = bot_behavior
        
        self.url_input = discord.ui.InputText(
            label="URL",
            placeholder="Paste MP3/TikTok/YouTube/Instagram URL here",
            style=discord.InputTextStyle.long,
            min_length=1,
            max_length=500,
            required=True
        )
        self.add_item(self.url_input)
        
        self.custom_name_input = discord.ui.InputText(
            label="Custom Name (Optional)",
            placeholder="Enter a custom name for the sound",
            min_length=0,
            max_length=50,
            required=False
        )
        self.add_item(self.custom_name_input)
        
        self.time_limit_input = discord.ui.InputText(
            label="Time Limit (Optional, for videos)",
            placeholder="Enter time limit in seconds (e.g., 30)",
            min_length=0,
            max_length=3,
            required=False
        )
        self.add_item(self.time_limit_input)
        
    async def callback(self, interaction):
        """Called when the modal is submitted"""
        try:
            # Check if upload is already in progress
            if self.bot_behavior.upload_lock.locked():
                await interaction.response.send_message("Another upload is in progress. Wait caralho 😤", ephemeral=True, delete_after=10)
                return
                
            await interaction.response.defer()
            
            async with self.bot_behavior.upload_lock:
                url_content = self.url_input.value.strip()
                custom_filename = self.custom_name_input.value.strip() if self.custom_name_input.value else None
                time_limit = None
                
                # Parse time limit if provided
                if self.time_limit_input.value and self.time_limit_input.value.strip().isdigit():
                    time_limit = int(self.time_limit_input.value.strip())
                
                # Validate URL format
                is_mp3_url = re.match(r'^https?://.*\.mp3$', url_content)
                is_tiktok_url = re.match(r'^https?://.*tiktok\.com/.*$', url_content)
                is_youtube_url = re.match(r'^https?://(www\.)?(youtube\.com|youtu\.be)/.*$', url_content)
                is_instagram_url = re.match(r'^https?://(www\.)?instagram\.com/(p|reels|reel|stories)/.*$', url_content)
                
                if not (is_mp3_url or is_tiktok_url or is_youtube_url or is_instagram_url):
                    await interaction.followup.send("Please provide a valid MP3, TikTok, YouTube, or Instagram URL.", ephemeral=True)
                    return
                
                try:
                    # Handle different URL types
                    if is_mp3_url:
                        file_path = await self.bot_behavior.save_sound_from_url(url_content, custom_filename)
                    elif is_tiktok_url or is_youtube_url or is_instagram_url:
                        await interaction.followup.send("Downloading video... 🤓", ephemeral=True, delete_after=5)
                        try:
                            file_path = await self.bot_behavior.save_sound_from_video(url_content, custom_filename, time_limit=time_limit)
                        except ValueError as e:
                            await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)
                            return
                    
                    # Ensure the file path exists before logging
                    if not os.path.exists(file_path):
                        await interaction.followup.send("Upload completed but file verification failed. Please try again.", ephemeral=True)
                        return
                    
                    # Log the action and send confirmation
                    Database().insert_action(interaction.user.name, "upload_sound", file_path)
                    await interaction.followup.send("Sound uploaded successfully! (may take up to 10s to be available)", ephemeral=True, delete_after=10)
                    
                except Exception as e:
                    print(f"Upload error details: {e}")
                    await interaction.followup.send(f"An error occurred during upload: {str(e)}", ephemeral=True)
                    
        except Exception as e:
            print(f"Error in UploadSoundModal.callback: {e}")
            try:
                await interaction.followup.send("An error occurred while uploading the sound. Please try again.", ephemeral=True)
            except:
                try:
                    await interaction.response.send_message("An error occurred while uploading the sound. Please try again.", ephemeral=True)
                except:
                    pass

class UploadSoundButton(Button):
    def __init__(self, bot_behavior, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction):
        # Create and send the modal for uploading sound
        modal = UploadSoundModal(self.bot_behavior)
        await interaction.response.send_modal(modal)


class PlayRandomButton(Button):
    def __init__(self, bot_behavior, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction):
        await interaction.response.defer()
        asyncio.create_task(self.bot_behavior.play_random_sound(interaction.user.name))

class PlayRandomFavoriteButton(Button):
    def __init__(self, bot_behavior, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction):
        await interaction.response.defer()
        asyncio.create_task(self.bot_behavior.play_random_favorite_sound(interaction.user.name))

class ListFavoritesButton(Button):
    # Class variable to track the current all favorites message
    current_favorites_message = None

    def __init__(self, bot_behavior, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction):
        await interaction.response.defer()
        
        # Delete previous all favorites message if it exists
        if ListFavoritesButton.current_favorites_message:
            try:
                await ListFavoritesButton.current_favorites_message.delete()
            except:
                pass  # Message might already be deleted
        
        favorites = Database().get_sounds(num_sounds=1000, favorite=True)
        Database().insert_action(interaction.user.name, "list_favorites", len(favorites))
        
        if len(favorites) > 0:
            view = PaginatedFavoritesView(self.bot_behavior, favorites, interaction.user.name)  # Pass the owner
            message = await self.bot_behavior.send_message(
                title=f"⭐ All Favorite Sounds (Page 1/{len(view.pages)}) ⭐",
                description=f"All favorite sounds in the database\nShowing sounds 1-{min(20, len(favorites))} of {len(favorites)}",
                view=view,
                delete_time=300
            )
            # Store the new message
            ListFavoritesButton.current_favorites_message = message
        else:
            await interaction.message.channel.send("No favorite sounds found.", delete_after=10)

class ListBlacklistButton(Button):
    def __init__(self, bot_behavior, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction):
        await interaction.response.defer()
        blacklisted = Database().get_sounds(num_sounds=1000, blacklist=True)
        Database().insert_action(interaction.user.name, "list_blacklisted_sounds", len(blacklisted))
        if len(blacklisted) > 0:
            blacklisted_entries = [f"{sound[0]}: {sound[2]}" for sound in blacklisted]
            blacklisted_content = "\n".join(blacklisted_entries)
            
            with open("blacklisted.txt", "w") as f:
                f.write(blacklisted_content)
            
            await self.bot_behavior.send_message("🗑️ Blacklisted Sounds 🗑️", file=discord.File("blacklisted.txt", "blacklisted.txt"), delete_time=30)
            os.remove("blacklisted.txt")  # Clean up the temporary file
        else:
            await interaction.message.channel.send("No blacklisted sounds found.")

class SlapButton(Button):
    def __init__(self, bot_behavior, audio_file):
        self.bot_behavior = bot_behavior
        self.audio_file = audio_file
        self.update_button_state()

    def update_button_state(self):
        if Database().get_sound(self.audio_file, True)[6]:  # Check if slap (index 6)
            super().__init__(label="👋❌", style=discord.ButtonStyle.primary)
        else:
            super().__init__(label="", emoji="👋", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        # Check if user has admin/mod permissions
        if not self.bot_behavior.is_admin_or_mod(interaction.user):
            await interaction.followup.send("Only admins and moderators can add slap sounds! 😤", ephemeral=True)
            return
            
        sound = Database().get_sound(self.audio_file, True)
        slap = 1 if not sound[6] else 0
        await Database().update_sound(sound[2], slap=slap)
        
        # Update the button state
        self.update_button_state()
        
        # Update the entire view
        await interaction.message.edit(view=SoundBeingPlayedView(self.bot_behavior, self.audio_file))
        Database().insert_action(interaction.user.name, "slap_sound", sound[0])

class PlaySlapButton(Button):
    def __init__(self, bot_behavior, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction):
        await interaction.response.defer()
        # Get a random slap sound from the database
        slap_sounds = Database().get_sounds(slap=True, num_sounds=100)
        if slap_sounds:
            random_slap = random.choice(slap_sounds)

            asyncio.create_task(self.bot_behavior.play_request(random_slap[1], interaction.user.name, exact=True)) #dont do this at home kids
        else:
            await interaction.followup.send("No slap sounds found in the database!", ephemeral=True, delete_after=5)

class ListSoundsButton(Button):
    def __init__(self, bot_behavior, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction):
        await interaction.response.defer()
        asyncio.create_task(self.bot_behavior.list_sounds(user=interaction.user))
        #self.bot_behavior.other_actions_db.add_entry(interaction.user.name, "list_sounds")

class SubwaySurfersButton(Button):
    def __init__(self, bot_behavior, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction):
        await interaction.response.defer()
        asyncio.create_task(self.bot_behavior.subway_surfers())

class SliceAllButton(Button):
    def __init__(self, bot_behavior, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction):
        await interaction.response.defer()
        asyncio.create_task(self.bot_behavior.slice_all())

class FamilyGuyButton(Button):
    def __init__(self, bot_behavior, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction):
        await interaction.response.defer()
        asyncio.create_task(self.bot_behavior.family_guy())

class BrainRotButton(Button):
    def __init__(self, bot_behavior, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction):
        await interaction.response.defer()

        # Check if the brain rot lock is already held
        if self.bot_behavior.brain_rot_lock.locked():
            # Delete previous cooldown message if it exists
            if self.bot_behavior.brain_rot_cooldown_message:
                try:
                    await self.bot_behavior.brain_rot_cooldown_message.delete()
                except discord.NotFound:
                    pass # Message already deleted
                except discord.Forbidden:
                    pass # Missing permissions
            # Send public message using send_message and store it
            self.bot_behavior.brain_rot_cooldown_message = await self.bot_behavior.send_message(
                title="🧠 Brain Rot Active 🧠",
                description="A brain rot function is already in progress. Please wait!",
                delete_time=5, # Make message public, but delete after 30s
                send_controls=False # Don't resend controls for just a status message
            )
            return

        # Function to run the chosen brain rot action with lock
        async def run_brain_rot():
            try:
                async with self.bot_behavior.brain_rot_lock:
                    # List of possible brain rot functions
                    brain_rot_functions = [
                        self.bot_behavior.subway_surfers,
                        self.bot_behavior.slice_all,
                        self.bot_behavior.family_guy
                    ]
                    # Choose one randomly
                    chosen_function = random.choice(brain_rot_functions)
                    
                    # Execute the chosen function
                    try:
                        await chosen_function(interaction.user)
                        # Log the action only on successful execution
                        function_name = chosen_function.__name__
                        Database().insert_action(interaction.user.name, f"brain_rot_{function_name}", "")
                    except Exception as e:
                        print(f"Error during brain rot function '{chosen_function.__name__}': {e}")
                        # Optionally send an error message to the user/channel
                        # await interaction.followup.send(f"An error occurred during {chosen_function.__name__}.", ephemeral=True)
            finally:
                 # Clean up the cooldown message after lock is released
                if self.bot_behavior.brain_rot_cooldown_message:
                    try:
                        await self.bot_behavior.brain_rot_cooldown_message.delete()
                    except discord.NotFound:
                        pass # Message already deleted
                    except discord.Forbidden:
                        pass # Missing permissions
                    self.bot_behavior.brain_rot_cooldown_message = None

        # Create a task to run the brain rot function in the background
        asyncio.create_task(run_brain_rot())

class StatsButton(Button):
    def __init__(self, bot_behavior, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction):
        await interaction.response.defer()
        asyncio.create_task(self.bot_behavior.display_top_users(interaction.user, number_users=20, number_sounds=5, days=700, by="plays"))


class ListLastScrapedSoundsButton(Button):
    def __init__(self, bot_behavior, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction):
        await interaction.response.defer()
        asyncio.create_task(self.bot_behavior.list_sounds(interaction.user, 25))
        self.bot_behavior.other_actions_db.add_entry(interaction.user.name, "list_last_scraped_sounds")

class PlaySoundButton(Button):
    def __init__(self, bot_behavior, sound_name, **kwargs):
        row = kwargs.pop('row', None)  # Extract row from kwargs
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior
        self.sound_name = sound_name
        if row is not None:
            self.row = row  # Set the row if provided

    async def callback(self, interaction):
        await interaction.response.defer()
        asyncio.create_task(self.bot_behavior.play_audio(self.bot_behavior.get_user_voice_channel(interaction.guild, interaction.user.name), self.sound_name, interaction.user.name))

class SoundBeingPlayedView(View):
    def __init__(self, bot_behavior, audio_file, user_id=None, include_add_to_list_select: bool = False):
        super().__init__(timeout=None)
        self.bot_behavior = bot_behavior
        self.audio_file = audio_file
        self.user_id = user_id

        # Conditionally add AddToList button or select menu FIRST - only if explicitly requested
        if include_add_to_list_select:
            lists = Database().get_sound_lists()
            if lists: # Only add select if there are lists
                # Check which list(s) the sound is already in
                lists_containing_sound = Database().get_lists_containing_sound(self.audio_file)
                default_list_id = lists_containing_sound[0][0] if lists_containing_sound else None

                # Ensure AddToListSelect can fit, check component count if necessary
                if len(self.children) < 25: # Basic check for component limit
                    # Pass the default_list_id to AddToListSelect
                    self.add_item(AddToListSelect(self.bot_behavior, self.audio_file, lists, default_list_id=default_list_id, row=4))
                else:
                    print("Warning: Could not add AddToListSelect to SoundBeingPlayedView due to component limit.")
                    # Fallback to button maybe? Or just omit. For now, omit if limit reached.
                    pass
            # If no lists, don't add the select or the button
        else:
            # Add the Add to List button only if explicitly requested
            if False:  # Removed - don't add button by default either
                if len(self.children) < 25:
                    self.add_item(AddToListButton(bot_behavior=bot_behavior, sound_filename=audio_file, emoji="📃", style=discord.ButtonStyle.success))
                else:
                    print("Warning: Could not add AddToListButton to SoundBeingPlayedView due to component limit.")

        # Add the replay button
        self.add_item(ReplayButton(bot_behavior=bot_behavior, audio_file=audio_file, emoji="🔁", style=discord.ButtonStyle.primary))

        # Add the favorite button
        self.add_item(FavoriteButton(bot_behavior=bot_behavior, audio_file=audio_file))

        # Add the blacklist button
        self.add_item(BlacklistButton(bot_behavior=bot_behavior, audio_file=audio_file))

        # Add the slap button
        self.add_item(SlapButton(bot_behavior=bot_behavior, audio_file=audio_file))

        # Add the isolate button
        #self.add_item(IsolateButton(bot_behavior=bot_behavior, audio_file=audio_file, label="Isolate", style=discord.ButtonStyle.secondary))

        # Add the change sound name button
        self.add_item(ChangeSoundNameButton(bot_behavior=bot_behavior, sound_name=audio_file, emoji="📝", style=discord.ButtonStyle.primary))

        # Add the new AssignUserEventButton
        self.add_item(AssignUserEventButton(bot_behavior=bot_behavior, audio_file=audio_file, emoji="📢", style=discord.ButtonStyle.primary))

        # Add the STS character select button
        self.add_item(STSCharacterSelectButton(bot_behavior=bot_behavior, audio_file=audio_file, emoji="🗣️", style=discord.ButtonStyle.primary))

class SoundBeingPlayedWithSuggestionsView(View):
    def __init__(self, bot_behavior, audio_file, similar_sounds, user_id=None, include_add_to_list_select: bool = False):
        super().__init__(timeout=None)
        self.bot_behavior = bot_behavior
        self.audio_file = audio_file
        self.user_id = user_id
        # Store similar sounds as an instance variable for later access
        self.similar_sounds = similar_sounds

        # First add all the buttons from SoundBeingPlayedView
        # Conditionally add AddToList button or select menu FIRST
        if include_add_to_list_select:
            lists = Database().get_sound_lists()
            if lists: # Only add select if there are lists
                # Check which list(s) the sound is already in
                lists_containing_sound = Database().get_lists_containing_sound(self.audio_file)
                default_list_id = lists_containing_sound[0][0] if lists_containing_sound else None

                # Ensure AddToListSelect can fit, check component count if necessary
                if len(self.children) < 25: # Basic check for component limit
                    # Pass the default_list_id to AddToListSelect
                    self.add_item(AddToListSelect(self.bot_behavior, self.audio_file, lists, default_list_id=default_list_id, row=4))
                else:
                    print("Warning: Could not add AddToListSelect to SoundBeingPlayedView due to component limit.")
                    # Fallback to button maybe? Or just omit. For now, omit if limit reached.
                    pass
            # If no lists, don't add the select or the button

        # Add the replay button
        self.add_item(ReplayButton(bot_behavior=bot_behavior, audio_file=audio_file, emoji="🔁", style=discord.ButtonStyle.primary))

        # Add the favorite button
        self.add_item(FavoriteButton(bot_behavior=bot_behavior, audio_file=audio_file))

        # Add the blacklist button
        self.add_item(BlacklistButton(bot_behavior=bot_behavior, audio_file=audio_file))

        # Add the slap button
        self.add_item(SlapButton(bot_behavior=bot_behavior, audio_file=audio_file))

        # Add the change sound name button
        self.add_item(ChangeSoundNameButton(bot_behavior=bot_behavior, sound_name=audio_file, emoji="📝", style=discord.ButtonStyle.primary))

        # Add the new AssignUserEventButton
        self.add_item(AssignUserEventButton(bot_behavior=bot_behavior, audio_file=audio_file, emoji="📢", style=discord.ButtonStyle.primary))

        # Add the STS character select button
        self.add_item(STSCharacterSelectButton(bot_behavior=bot_behavior, audio_file=audio_file, emoji="🗣️", style=discord.ButtonStyle.primary))
        
        # Add a dropdown to pick similar sounds instead of multiple buttons
        if similar_sounds:
            self.add_item(SimilarSoundsSelect(bot_behavior, similar_sounds))

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
        
        # Update both the content and description
        total_favorites = sum(len(page) for page in view.pages)
        current_page_start = (view.current_page * 20) + 1
        current_page_end = min((view.current_page + 1) * 20, total_favorites)
        
        title = (f"🤩 {view.owner}'s Favorites (Page {view.current_page + 1}/{len(view.pages)}) 🤩" if is_user_favorites 
                else f"⭐ All Favorite Sounds (Page {view.current_page + 1}/{len(view.pages)}) ⭐")
        
        description = f"Showing sounds {current_page_start}-{current_page_end} of {total_favorites}"
        
        await interaction.message.edit(
            content=None,
            embed=discord.Embed(
                title=title,
                description=description,
                color=discord.Color.blue()
            ),
            view=view
        )

class PaginatedFavoritesView(View):
    def __init__(self, bot_behavior, favorites, owner):
        super().__init__(timeout=None)
        self.bot_behavior = bot_behavior
        self.current_page = 0
        self.owner = owner  # Store the user who created the view
        
        # We can have 4 rows of sound buttons (row 0 is navigation)
        # Each row can have 5 buttons
        # So we can show 20 sounds per page
        chunk_size = 20
        self.pages = [favorites[i:i + chunk_size] for i in range(0, len(favorites), chunk_size)]
        
        # Add navigation buttons
        self.add_item(PaginationButton("Previous", "⬅️", discord.ButtonStyle.primary, "previous", 0))
        self.add_item(PaginationButton("Next", "➡️", discord.ButtonStyle.primary, "next", 0))
        
        # Add initial sound buttons
        self.update_page_buttons()
    
    def update_buttons(self):
        # Clear existing sound buttons (row 1 and beyond)
        self.clear_items()
        
        # Re-add navigation buttons
        self.add_item(PaginationButton("Previous", "⬅️", discord.ButtonStyle.primary, "previous", 0))
        self.add_item(PaginationButton("Next", "➡️", discord.ButtonStyle.primary, "next", 0))
        
        # Add sound buttons for current page
        self.update_page_buttons()
    
    def update_page_buttons(self):
        if not self.pages:
            return
            
        current_sounds = self.pages[self.current_page]
        for i, sound in enumerate(current_sounds):
            # Calculate row (starting from row 1, as row 0 is for navigation)
            # We have 5 buttons per row, and 4 available rows (1-4)
            row = (i // 5) + 1  # This will give us rows 1, 2, 3, 4 for up to 20 items
            self.add_item(PlaySoundButton(
                self.bot_behavior,
                sound[1],
                style=discord.ButtonStyle.danger,
                label=sound[2].split('/')[-1].replace('.mp3', ''),
                row=row
            ))

class ListUserFavoritesButton(Button):
    # Dictionary to track current favorites message per user
    current_user_messages = {}

    def __init__(self, bot_behavior, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction):
        await interaction.response.defer()
        
        # Delete previous message for this user if it exists
        if interaction.user.name in ListUserFavoritesButton.current_user_messages:
            try:
                await ListUserFavoritesButton.current_user_messages[interaction.user.name].delete()
            except:
                pass  # Message might already be deleted
        
        favorites = Database().get_sounds(num_sounds=1000, favorite_by_user=True, user=interaction.user.name)
        Database().insert_action(interaction.user.name, "list_user_favorites", len(favorites))
        
        if len(favorites) > 0:
            view = PaginatedFavoritesView(self.bot_behavior, favorites, interaction.user.name)  # Pass the owner
            message = await self.bot_behavior.send_message(
                title=f"🤩 {interaction.user.name}'s Favorites (Page 1/{len(view.pages)}) 🤩",
                description=f"Showing sounds 1-{min(20, len(favorites))} of {len(favorites)}",
                view=view,
                delete_time=300
            )
            # Store the new message for this user
            ListUserFavoritesButton.current_user_messages[interaction.user.name] = message
        else:
            await interaction.message.channel.send("No favorite sounds found.", delete_after=10)

#
class ControlsView(View):
    def __init__(self, bot_behavior):
        super().__init__(timeout=None)
        self.add_item(PlayRandomButton(bot_behavior, label="🎲Play Random🎲", style=discord.ButtonStyle.success))
        self.add_item(PlayRandomFavoriteButton(bot_behavior, label="🎲Play Random Favorite⭐", style=discord.ButtonStyle.success))
        self.add_item(ListFavoritesButton(bot_behavior, label="⭐Favorites⭐", style=discord.ButtonStyle.success))
        self.add_item(ListUserFavoritesButton(bot_behavior, label="💖My Favorites💖", style=discord.ButtonStyle.success))
        self.add_item(ListBlacklistButton(bot_behavior, label="🗑️Blacklisted🗑️", style=discord.ButtonStyle.success))
        self.add_item(PlaySlapButton(bot_behavior, label="", emoji="👋", style=discord.ButtonStyle.success))

        self.add_item(BrainRotButton(bot_behavior, label="🧠Brain Rot🧠", style=discord.ButtonStyle.success))
        self.add_item(StatsButton(bot_behavior, label="📊Stats📊", style=discord.ButtonStyle.success))
        self.add_item(UploadSoundButton(bot_behavior, label="⬆️Upload Sound⬆️", style=discord.ButtonStyle.success))
        self.add_item(ListLastScrapedSoundsButton(bot_behavior, label="🔽Last Downloaded Sounds🔽", style=discord.ButtonStyle.success))

class DownloadedSoundView(View):
    def __init__(self, bot_behavior, sound):
        super().__init__(timeout=None)
        self.add_item(PlaySoundButton(bot_behavior, sound, style=discord.ButtonStyle.danger, label=sound.split('/')[-1].replace('.mp3', '')))
                          
class SoundView(View):
    def __init__(self, bot_behavior, similar_sounds):
        super().__init__(timeout=None)
        for sound in similar_sounds:
            self.add_item(PlaySoundButton(bot_behavior, sound[1], style=discord.ButtonStyle.danger, label=sound[2].split('/')[-1].replace('.mp3', '')))

class DeleteEventButton(Button):
    def __init__(self, bot_behavior, user_id, event, sound):
        super().__init__(label=sound, style=discord.ButtonStyle.danger)
        self.bot_behavior = bot_behavior
        self.user_id = user_id
        self.event = event
        self.sound = sound

    async def callback(self, interaction):
        await interaction.response.defer()
        
        # If the owner clicks, delete the event
        if interaction.user.name == self.user_id.split('#')[0]:
            # Remove the event
            if Database().remove_user_event_sound(self.user_id, self.event, self.sound):
                Database().insert_action(interaction.user.name, f"delete_{self.event}_event", self.sound)
                
                # Get remaining events of this type
                remaining_events = Database().get_user_events(self.user_id, self.event)
                
                if not remaining_events:
                    # If no events left of this type, delete the message
                    await interaction.message.delete()
                else:
                    # Create new paginated view with remaining events
                    view = PaginatedEventView(self.bot_behavior, remaining_events, self.user_id, self.event)
                    
                    # Update the message with the first page
                    total_events = len(remaining_events)
                    current_page_end = min(20, total_events)
                    
                    description = "**Current sounds:**\n"
                    description += "\n".join([f"• {event[2]}" for event in remaining_events[:current_page_end]])
                    description += f"\nShowing sounds 1-{current_page_end} of {total_events}"
                    
                    embed = interaction.message.embeds[0]
                    embed.description = description
                    
                    await interaction.message.edit(embed=embed, view=view)
                
                await interaction.followup.send(f"Event {self.event} with sound {self.sound} deleted!", ephemeral=True)
            else:
                await interaction.followup.send("Failed to delete the event!", ephemeral=True)
        # If another user clicks, play the sound
        else:
            channel = self.bot_behavior.get_user_voice_channel(interaction.guild, interaction.user.name)
            if channel:
                #get most similar sound
                similar_sounds = Database().get_sounds_by_similarity(self.sound,1)
                await self.bot_behavior.play_audio(channel, similar_sounds[0][1], interaction.user.name)
                Database().insert_action(interaction.user.name, f"play_{self.event}_event_sound", self.sound)
            else:
                await interaction.followup.send("You need to be in a voice channel to play sounds! 😭", ephemeral=True)

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
        
        # Update buttons state
        view.update_buttons()
        
        # Update the content and description
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

class PaginatedEventView(View):
    def __init__(self, bot_behavior, events, user_id, event):
        super().__init__(timeout=None)
        self.bot_behavior = bot_behavior
        self.current_page = 0
        self.user_id = user_id
        self.event = event
        
        # Split events into pages of 20 events each (4 rows of 5 buttons)
        chunk_size = 20
        self.pages = [events[i:i + chunk_size] for i in range(0, len(events), chunk_size)]
        
        # Add navigation buttons
        self.add_item(EventPaginationButton("Previous", "⬅️", discord.ButtonStyle.primary, "previous", 0))
        self.add_item(EventPaginationButton("Next", "➡️", discord.ButtonStyle.primary, "next", 0))
        
        # Add initial event buttons
        self.update_page_buttons()
    
    def update_buttons(self):
        # Clear existing buttons
        self.clear_items()
        
        # Re-add navigation buttons
        self.add_item(EventPaginationButton("Previous", "⬅️", discord.ButtonStyle.primary, "previous", 0))
        self.add_item(EventPaginationButton("Next", "➡️", discord.ButtonStyle.primary, "next", 0))
        
        # Add event buttons for current page
        self.update_page_buttons()
    
    def update_page_buttons(self):
        if not self.pages:
            return
            
        current_events = self.pages[self.current_page]
        for i, event in enumerate(current_events):
            # Calculate row (1-4) and position in row (0-4)
            row = (i // 5) + 1  # +1 because row 0 is for navigation buttons
            button = DeleteEventButton(self.bot_behavior, self.user_id, self.event, event[2])
            button.row = row
            self.add_item(button)

class EventView(View):
    def __init__(self, bot_behavior, user_id, event, sounds):
        super().__init__(timeout=None)
        for sound in sounds:
            self.add_item(DeleteEventButton(bot_behavior, user_id, event, sound))

# Sound List UI Components
class SoundListButton(Button):
    def __init__(self, bot_behavior, list_id, list_name, **kwargs):
        # If label is not provided in kwargs, use list_name as the label
        if 'label' not in kwargs:
            kwargs['label'] = list_name
        if 'style' not in kwargs:
            kwargs['style'] = discord.ButtonStyle.primary
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior
        self.list_id = list_id
        self.list_name = list_name

    async def callback(self, interaction):
        await interaction.response.defer()
        # Get the sounds in the list
        sounds = Database().get_sounds_in_list(self.list_id)
        if not sounds:
            await self.bot_behavior.send_message(
                title=f"Sound List: {self.list_name}",
                description="This list is empty. Add sounds with `/addtolist`."
            )
            return
            
        # Create a paginated view with buttons for each sound
        view = PaginatedSoundListView(self.bot_behavior, self.list_id, self.list_name, sounds, interaction.user.name)
        
        # Send a message with the view
        await self.bot_behavior.send_message(
            title=f"Sound List: {self.list_name} (Page 1/{len(view.pages)})",
            description=f"Contains {len(sounds)} sounds. Showing sounds 1-{min(8, len(sounds))} of {len(sounds)}",
            view=view
        )

class SoundListItemButton(Button):
    def __init__(self, bot_behavior, sound_filename, display_name, **kwargs):
        # If label is not provided in kwargs, use display_name as the label
        if 'label' not in kwargs:
            kwargs['label'] = display_name
        if 'style' not in kwargs:
            kwargs['style'] = discord.ButtonStyle.secondary
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior
        self.sound_filename = sound_filename

    async def callback(self, interaction):
        await interaction.response.defer()
        # Play the sound
        asyncio.create_task(self.bot_behavior.play_audio(
            interaction.channel, 
            self.sound_filename, 
            interaction.user.name
        ))
        # Record the action
        Database().insert_action(interaction.user.name, "play_from_list", self.sound_filename)

class CreateListButton(Button):
    def __init__(self, bot_behavior, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction):
        # Create a modal for the user to enter the list name
        modal = CreateListModalWithSoundAdd(self.bot_behavior)
        await interaction.response.send_modal(modal)

class AddToListButton(Button):
    def __init__(self, bot_behavior, sound_filename, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior
        self.sound_filename = sound_filename

    async def callback(self, interaction):
        # Get all available lists instead of just the user's lists
        lists = Database().get_sound_lists()
        if not lists:
            await interaction.response.send_message(
                "There are no sound lists available. Create one with `/createlist`.",
                ephemeral=True
            )
            return
            
        # Create a select menu with all available lists
        select = AddToListSelect(self.bot_behavior, self.sound_filename, lists)
        view = discord.ui.View()
        view.add_item(select)
        
        await interaction.response.send_message(
            "Select a list to add this sound to:",
            view=view,
            ephemeral=True
        )

class RemoveFromListButton(Button):
    def __init__(self, bot_behavior, list_id, list_name, sound_filename, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior
        self.list_id = list_id
        self.list_name = list_name
        self.sound_filename = sound_filename

    async def callback(self, interaction):
        await interaction.response.defer()
        # Get the list
        sound_list = Database().get_sound_list(self.list_id)
        if not sound_list:
            await interaction.followup.send("List not found.", ephemeral=True)
            return
            
        # Check if the user is the creator of the list
        if sound_list[2] != interaction.user.name:
            await interaction.followup.send("You can only remove sounds from your own lists.", ephemeral=True)
            return
            
        # Remove the sound from the list
        success = Database().remove_sound_from_list(self.list_id, self.sound_filename)
        if success:
            await interaction.followup.send(f"Removed sound from list '{self.list_name}'.", ephemeral=True)
            
            # Refresh the list view
            sounds = Database().get_sounds_in_list(self.list_id)
            if not sounds:
                await self.bot_behavior.send_message(
                    title=f"Sound List: {self.list_name}",
                    description="This list is now empty. Add sounds with `/addtolist`."
                )
                return
                
            # Use the paginated view instead of the regular view
            view = PaginatedSoundListView(self.bot_behavior, self.list_id, self.list_name, sounds, interaction.user.name)
            await self.bot_behavior.send_message(
                title=f"Sound List: {self.list_name} (Page 1/{len(view.pages)})",
                description=f"Contains {len(sounds)} sounds. Showing sounds 1-{min(8, len(sounds))} of {len(sounds)}",
                view=view
            )
        else:
            await interaction.followup.send("Failed to remove sound from list.", ephemeral=True)

class DeleteListButton(Button):
    def __init__(self, bot_behavior, list_id, list_name, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior
        self.list_id = list_id
        self.list_name = list_name

    async def callback(self, interaction):
        await interaction.response.defer()
        # Get the list
        sound_list = Database().get_sound_list(self.list_id)
        if not sound_list:
            await interaction.followup.send("List not found.", ephemeral=True)
            return
            
        # Check if the user is the creator of the list
        if sound_list[2] != interaction.user.name:
            await interaction.followup.send("You can only delete your own lists.", ephemeral=True)
            return
            
        # Delete the list
        success = Database().delete_sound_list(self.list_id)
        if success:
            await interaction.followup.send(f"Deleted list '{self.list_name}'.", ephemeral=True)
            
            # Send a message confirming the deletion
            await self.bot_behavior.send_message(
                title="List Deleted",
                description=f"The list '{self.list_name}' has been deleted."
            )
        else:
            await interaction.followup.send("Failed to delete list.", ephemeral=True)

class SimilarSoundsSelect(discord.ui.Select):
    def __init__(self, bot_behavior, similar_sounds):
        self.bot_behavior = bot_behavior
        options = []
        for sound in similar_sounds[:25]:
            options.append(
                discord.SelectOption(
                    label=sound[2].split('/')[-1].replace('.mp3', ''),
                    value=sound[1]
                )
            )
        super().__init__(
            placeholder="Play a similar sound",
            min_values=1,
            max_values=1,
            options=options,
            row=3
        )

    async def callback(self, interaction):
        await interaction.response.defer()
        selected = self.values[0]
        channel = self.bot_behavior.get_user_voice_channel(interaction.guild, interaction.user.name)
        if channel:
            asyncio.create_task(self.bot_behavior.play_audio(channel, selected, interaction.user.name))
            Database().insert_action(interaction.user.name, "play_similar_sound", selected)
        else:
            await interaction.followup.send("You need to be in a voice channel to play sounds! 😭", ephemeral=True)

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

class AddToListSelect(discord.ui.Select):
    def __init__(self, bot_behavior, sound_filename, lists, default_list_id: int = None, row: int = 0):
        self.bot_behavior = bot_behavior
        self.sound_filename = sound_filename

        # Create options for each list, showing the creator's name
        options = []
        
        # Add "Create New List" option as the first option
        options.append(discord.SelectOption(
            label="➕ Create New List",
            value="create_new_list",
            description="Create a new sound list",
            emoji="➕"
        ))

        for list_info in lists[:24]:  # Limit to 24 since we added one option already
            list_id = list_info[0]
            option = discord.SelectOption(
                label=f"{list_info[1]} (by {list_info[2]})",  # list_name (by creator)
                value=str(list_id),  # list_id
                description=f"Created by {list_info[2]}"  # Show creator in description
            )
            # Set default if this list_id matches the provided default_list_id
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
        # Check if user selected "Create New List"
        if self.values[0] == "create_new_list":
            try:
                print(f"AddToListSelect: User selected create new list, sound_filename={self.sound_filename}")
                # Create and send the modal for creating a new list
                modal = CreateListModalWithSoundAdd(self.bot_behavior, self.sound_filename)
                print(f"AddToListSelect: Modal created successfully")
                await interaction.response.send_modal(modal)
                print(f"AddToListSelect: Modal sent successfully")
                
                # Reset the select menu by updating the message with a fresh view
                # This removes the selection from "Create New List"
                try:
                    # Get the current view from the interaction message
                    current_view = interaction.message.view
                    if current_view:
                        # Create a new select with the same options but no selection
                        lists = Database().get_sound_lists()
                        new_select = AddToListSelect(self.bot_behavior, self.sound_filename, lists, row=self.row)
                        
                        # Find the AddToListSelect in the view and replace it
                        for i, item in enumerate(current_view.children):
                            if isinstance(item, AddToListSelect):
                                current_view.children[i] = new_select
                                break
                        
                        # Update the message with the refreshed view
                        await interaction.edit_original_response(view=current_view)
                        print(f"AddToListSelect: Select menu reset successfully")
                except Exception as e:
                    print(f"AddToListSelect: Error resetting select menu: {e}")
                    # Don't fail the whole operation if we can't reset the select
                    pass
                
                return
            except Exception as e:
                print(f"AddToListSelect create modal error: {e}")
                import traceback
                traceback.print_exc()
                try:
                    await interaction.response.send_message("Failed to open create list dialog. Please try again.", ephemeral=True)
                except:
                    pass
                return
            
        await interaction.response.defer()
        list_id = int(self.values[0])

        # Get the list name and creator
        list_info = Database().get_sound_list(list_id)
        if not list_info:
            await interaction.followup.send("List not found.", ephemeral=True)
            return

        list_name = list_info[1]
        list_creator = list_info[2]

        # Add the sound to the list
        success, message = Database().add_sound_to_list(list_id, self.sound_filename)

        if success:
            # If the user adding the sound is not the creator, include that in the message
            if list_creator != interaction.user.name:
                await interaction.followup.send(f"Added sound to {list_creator}'s list '{list_name}'.", ephemeral=True)
                
                # Optionally notify in the channel about the addition
                await self.bot_behavior.send_message(
                    title=f"Sound Added to List",
                    description=f"{interaction.user.name} added a sound to {list_creator}'s list '{list_name}'."
                )
            else:
                await interaction.followup.send(f"Added sound to your list '{list_name}'.", ephemeral=True)
        else:
            await interaction.followup.send(f"Failed to add sound to list: {message}", ephemeral=True)

class CreateListModalWithSoundAdd(discord.ui.Modal):
    def __init__(self, bot_behavior, sound_filename=None):
        try:
            print(f"CreateListModalWithSoundAdd: Initializing modal with sound_filename={sound_filename}")
            super().__init__(title="Create New Sound List")
            self.bot_behavior = bot_behavior
            self.sound_filename = sound_filename
            
            self.list_name = discord.ui.InputText(
                label="List Name",
                placeholder="Enter a name for your sound list",
                min_length=1,
                max_length=100
            )
            self.add_item(self.list_name)
            print(f"CreateListModalWithSoundAdd: Modal initialized successfully")
        except Exception as e:
            print(f"CreateListModalWithSoundAdd __init__ error: {e}")
            import traceback
            traceback.print_exc()
            raise
        
    async def callback(self, interaction):
        try:
            print(f"CreateListModalWithSoundAdd: callback called")
            list_name = self.list_name.value
            print(f"CreateListModalWithSoundAdd: Creating list '{list_name}' for user {interaction.user.name}")
            
            # Check if the user already has a list with this name
            existing_list = Database().get_list_by_name(list_name, interaction.user.name)
            if existing_list:
                await interaction.response.send_message(f"You already have a list named '{list_name}'.", ephemeral=True)
                return
                
            # Create the list
            list_id = Database().create_sound_list(list_name, interaction.user.name)
            print(f"CreateListModalWithSoundAdd: Created list with ID {list_id}")
            
            if list_id:
                success_message = f"Created list '{list_name}'."
                
                # If this modal was called from AddToListSelect, also add the sound to the new list
                if self.sound_filename:
                    print(f"CreateListModalWithSoundAdd: Adding sound {self.sound_filename} to list {list_id}")
                    success, message = Database().add_sound_to_list(list_id, self.sound_filename)
                    if success:
                        success_message += f" Sound added to the list."
                    else:
                        success_message += f" However, failed to add sound: {message}"
                        print(f"CreateListModalWithSoundAdd: Failed to add sound: {message}")
                
                await interaction.response.send_message(success_message, ephemeral=True)
                print(f"CreateListModalWithSoundAdd: Success message sent")
                
                # Send a background message without blocking the modal response
                import asyncio
                asyncio.create_task(self._send_confirmation_message(list_name))
            else:
                await interaction.response.send_message("Failed to create list.", ephemeral=True)
                
        except Exception as e:
            print(f"CreateListModalWithSoundAdd error: {e}")
            import traceback
            traceback.print_exc()
            try:
                await interaction.response.send_message("An error occurred while creating the list. Please try again.", ephemeral=True)
            except:
                pass
    
    async def _send_confirmation_message(self, list_name):
        """Send confirmation message in background to avoid blocking modal response"""
        try:
            await self.bot_behavior.send_message(
                title="List Created",
                description=f"Created a new sound list: '{list_name}'" + (f"\nSound added to the list." if self.sound_filename else "\nAdd sounds with `/addtolist`.") 
            )
        except Exception as e:
            print(f"CreateListModalWithSoundAdd: Error sending confirmation message: {e}")

class ChangeSoundNameModal(discord.ui.Modal):
    def __init__(self, bot_behavior, sound_name):
        try:
            print(f"ChangeSoundNameModal: Initializing modal with sound_name={sound_name}")
            super().__init__(title="Change Sound Name")
            self.bot_behavior = bot_behavior
            self.sound_name = sound_name
            
            self.new_name = discord.ui.InputText(
                label="New Sound Name",
                placeholder=f"Current: {sound_name.replace('.mp3', '') if sound_name.endswith('.mp3') else sound_name}",
                min_length=1,
                max_length=100
            )
            self.add_item(self.new_name)
            print(f"ChangeSoundNameModal: Modal initialized successfully")
        except Exception as e:
            print(f"ChangeSoundNameModal __init__ error: {e}")
            import traceback
            traceback.print_exc()
            raise
        
    async def callback(self, interaction):
        try:
            print(f"ChangeSoundNameModal: callback called")
            new_name = self.new_name.value
            print(f"ChangeSoundNameModal: Changing '{self.sound_name}' to '{new_name}' for user {interaction.user.name}")
            
            if new_name:
                # Send immediate response and then do the work
                await interaction.response.defer(ephemeral=True)
                
                try:
                    # Do the actual filename change
                    await self.bot_behavior.change_filename(self.sound_name, new_name, interaction.user)
                    
                    # Send success message using the bot's standard message format
                    await self.bot_behavior.send_message(
                        title="Sound Name Changed",
                        description=f"Successfully changed sound name from **{self.sound_name}** to **{new_name}**!"
                    )
                    
                    print(f"ChangeSoundNameModal: Successfully changed filename from {self.sound_name} to {new_name}")
                except Exception as e:
                    # For errors, use both the standard message and private message
                    await self.bot_behavior.send_message(
                        title="Failed to Change Sound Name",
                        description=f"Could not change sound name from **{self.sound_name}** to **{new_name}**\n\nError: {str(e)}"
                    )
                    await interaction.followup.send("Failed to change sound name. Check the main channel for details.", ephemeral=True)
                    print(f"ChangeSoundNameModal: Error changing filename: {e}")
            else:
                await interaction.response.send_message("Invalid name provided.", ephemeral=True)
                
        except Exception as e:
            print(f"ChangeSoundNameModal error: {e}")
            import traceback
            traceback.print_exc()
            try:
                await interaction.response.send_message("An error occurred while changing the sound name. Please try again.", ephemeral=True)
            except:
                pass

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
        current_page_start = (view.current_page * 8) + 1
        current_page_end = min((view.current_page + 1) * 8, total_sounds)
        
        await interaction.message.edit(
            content=None,
            embed=discord.Embed(
                title=f"Sound List: {view.list_name} (Page {view.current_page + 1}/{len(view.pages)})",
                description=f"Contains {total_sounds} sounds. Showing sounds {current_page_start}-{current_page_end} of {total_sounds}",
                color=discord.Color.blue()
            ),
            view=view
        )

class PaginatedSoundListView(View):
    def __init__(self, bot_behavior, list_id, list_name, sounds, owner):
        super().__init__(timeout=None)
        self.bot_behavior = bot_behavior
        self.list_id = list_id
        self.list_name = list_name
        self.current_page = 0
        self.owner = owner  # Store the user who created the view
        
        # We can have 4 rows of sound buttons (row 1-4, as row 0 is for navigation)
        # Each row can have 2 pairs of buttons (sound + remove)
        # So we can show 8 sounds per page (2 pairs * 4 rows)
        chunk_size = 8
        self.pages = [sounds[i:i + chunk_size] for i in range(0, len(sounds), chunk_size)]
        
        # Add navigation buttons
        self.add_item(SoundListPaginationButton("Previous", "⬅️", discord.ButtonStyle.primary, "previous", 0))
        self.add_item(SoundListPaginationButton("Next", "➡️", discord.ButtonStyle.primary, "next", 0))
        
        # Add delete list button in the navigation row if on first page
        if self.current_page == 0:
            self.add_item(DeleteListButton(
                bot_behavior=self.bot_behavior,
                list_id=self.list_id,
                list_name=self.list_name,
                label="Delete List",
                style=discord.ButtonStyle.danger,
                row=0
            ))
        
        # Add initial sound buttons
        self.update_page_buttons()
    
    def update_buttons(self):
        # Clear existing sound buttons
        self.clear_items()
        
        # Re-add navigation buttons
        self.add_item(SoundListPaginationButton("Previous", "⬅️", discord.ButtonStyle.primary, "previous", 0))
        self.add_item(SoundListPaginationButton("Next", "➡️", discord.ButtonStyle.primary, "next", 0))
        
        # Add delete list button in the navigation row if on first page
        if self.current_page == 0:
            self.add_item(DeleteListButton(
                bot_behavior=self.bot_behavior,
                list_id=self.list_id,
                list_name=self.list_name,
                label="Delete List",
                style=discord.ButtonStyle.danger,
                row=0
            ))
        
        # Add sound buttons for current page
        self.update_page_buttons()
    
    def update_page_buttons(self):
        if not self.pages:
            return
            
        current_sounds = self.pages[self.current_page]
        for i, (filename, original_name) in enumerate(current_sounds):
            # Use the original name if available, otherwise use the filename
            display_name = original_name if original_name else filename
            # Truncate long names
            if len(display_name) > 80:
                display_name = display_name[:77] + "..."
            
            # Calculate row (starting from row 1, as row 0 is for navigation)
            # We can fit 2 pairs (sound + remove) per row
            row = (i // 2) + 1  # This will give us rows 1, 2, 3, 4 for up to 8 items
            
            # Add sound button
            self.add_item(SoundListItemButton(
                bot_behavior=self.bot_behavior,
                sound_filename=filename,
                display_name=display_name,
                row=row
            ))
            
            # Add remove button next to the sound button
            self.add_item(RemoveFromListButton(
                bot_behavior=self.bot_behavior,
                list_id=self.list_id,
                list_name=self.list_name,
                sound_filename=filename,
                label="❌",
                style=discord.ButtonStyle.blurple,
                row=row
            ))

class UserSoundListsView(discord.ui.View):
    def __init__(self, bot_behavior, lists, username):
        super().__init__(timeout=None)
        self.bot_behavior = bot_behavior
        
        # Add buttons for each list (up to 25 due to Discord's limit)
        for i, (list_id, list_name, creator, created_at) in enumerate(lists[:25]):
            button_label = list_name
            # If showing all lists (username is None), include creator name in button label
            if username is None:
                button_label = f"{list_name} (by {creator})"
                
            self.add_item(SoundListButton(
                bot_behavior=bot_behavior,
                list_id=list_id,
                list_name=list_name,
                label=button_label,
                row=i // 5  # Organize buttons in rows of 5
            ))
            
        # Add a create list button only when showing a specific user's lists
        if username is not None:
            self.add_item(CreateListButton(
                bot_behavior=bot_behavior,
                row=5  # Put at the bottom
            ))

class STSCharacterSelectButton(Button):
    def __init__(self, bot_behavior, audio_file, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior
        self.audio_file = audio_file

    async def callback(self, interaction):
        await interaction.response.defer()
        
        # Create a view with buttons for each character
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
        Database().insert_action(interaction.user.name, "sts_character_select", Database().get_sound(self.audio_file, True)[0])