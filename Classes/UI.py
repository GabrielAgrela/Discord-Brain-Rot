from datetime import datetime
import random
from discord.ui import Button, View
import discord
import asyncio
import os
from Classes.Database import Database



class ReplayButton(Button):
    def __init__(self, bot_behavior, audio_file, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior
        self.audio_file = audio_file
        

    async def callback(self, interaction):
        await interaction.response.defer()
        asyncio.create_task(self.bot_behavior.play_audio(interaction.message.channel, self.audio_file, interaction.user.name))
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
            action_type = "unfavorite_sound"
        
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
        await interaction.response.defer()
        new_name = await self.bot_behavior.get_new_name(interaction)
        if new_name:
            #get username
            await self.bot_behavior.change_filename(self.sound_name, new_name,interaction.user)
            #self.bot_behavior.other_actions_db.add_entry(interaction.user.name, "change_sound_name", self.sound_name)

class UploadSoundButton(Button):
    def __init__(self, bot_behavior, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction):
        await interaction.response.defer()
        await self.bot_behavior.prompt_upload_sound(interaction)


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
        if Database().get_sound(self.audio_file, True)[6]:  # Check if slap (index 5)
            super().__init__(label="👋❌", style=discord.ButtonStyle.primary)
        else:
            super().__init__(label="", emoji="👋", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
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
        slap_sounds = Database().get_sounds(slap=True)
        if slap_sounds:
            random_slap = random.choice(slap_sounds)
            asyncio.create_task(self.bot_behavior.play_request(random_slap, interaction.user.name, 1, True)) #dont do this at home kids
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
        asyncio.create_task(self.bot_behavior.display_top_users(interaction.user, number_users=10, number_sounds=5, days=700, by="plays"))


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

class JoinEventButton(Button):
    def __init__(self, bot_behavior, audio_file, user_id=None):
        self.bot_behavior = bot_behavior
        self.audio_file = audio_file
        self.user_id = user_id
        self.last_used = {}  # Dictionary to track last usage per user
        super().__init__(label="", emoji="📢", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        # Check cooldown
        user_id = str(interaction.user.id)
        current_time = datetime.now()
        if user_id in self.last_used:
            time_diff = (current_time - self.last_used[user_id]).total_seconds()
            if time_diff < 5:  # 5 second cooldown
                await interaction.followup.send("Please wait 5 seconds before using this button again!", ephemeral=True, delete_after=5)
                return
        
        sound_name = self.audio_file.split('/')[-1].replace('.mp3', '')
        user_full_name = f"{interaction.user.name}#{interaction.user.discriminator}"
        
        # Check if sound is already set
        is_set = Database().get_user_event_sound(user_full_name, "join", sound_name)
        
        # Toggle the sound and send appropriate message
        Database().toggle_user_event_sound(user_full_name, "join", sound_name)
        
        message = f"{'Removed' if is_set else 'Added'} {sound_name} as join sound!"
        await interaction.followup.send(message, ephemeral=True, delete_after=5)
        
        # Update last used time
        self.last_used[user_id] = current_time

class LeaveEventButton(Button):
    def __init__(self, bot_behavior, audio_file, user_id=None):
        self.bot_behavior = bot_behavior
        self.audio_file = audio_file
        self.user_id = user_id
        self.last_used = {}  # Dictionary to track last usage per user
        super().__init__(label="", emoji="📢", style=discord.ButtonStyle.danger)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        # Check cooldown
        user_id = str(interaction.user.id)
        current_time = datetime.now()
        if user_id in self.last_used:
            time_diff = (current_time - self.last_used[user_id]).total_seconds()
            if time_diff < 5:  # 5 second cooldown
                await interaction.followup.send("Please wait 5 seconds before using this button again!", ephemeral=True, delete_after=5)
                return
        
        sound_name = self.audio_file.split('/')[-1].replace('.mp3', '')
        user_full_name = f"{interaction.user.name}#{interaction.user.discriminator}"
        
        # Check if sound is already set
        is_set = Database().get_user_event_sound(user_full_name, "leave", sound_name)
        
        # Toggle the sound and send appropriate message
        Database().toggle_user_event_sound(user_full_name, "leave", sound_name)
        
        message = f"{'Removed' if is_set else 'Added'} {sound_name} as leave sound!"
        await interaction.followup.send(message, ephemeral=True, delete_after=5)
        
        # Update last used time
        self.last_used[user_id] = current_time

class SoundBeingPlayedView(View):
    def __init__(self, bot_behavior, audio_file, user_id=None):
        super().__init__(timeout=None)
        self.bot_behavior = bot_behavior
        self.audio_file = audio_file
        self.user_id = user_id
        
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
        
        # Add the join event button
        self.add_item(JoinEventButton(bot_behavior=bot_behavior, audio_file=audio_file, user_id=user_id))
        
        # Add the leave event button
        self.add_item(LeaveEventButton(bot_behavior=bot_behavior, audio_file=audio_file, user_id=user_id))
        
        # Add the STS character select button
        self.add_item(STSCharacterSelectButton(bot_behavior=bot_behavior, audio_file=audio_file, emoji="🗣️", style=discord.ButtonStyle.primary))
        
        # Add the Add to List button
        self.add_item(AddToListButton(bot_behavior=bot_behavior, sound_filename=audio_file, emoji="📃", style=discord.ButtonStyle.success))

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

class ControlsView(View):
    def __init__(self, bot_behavior):
        super().__init__(timeout=None)
        self.add_item(PlayRandomButton(bot_behavior, label="🎲Play Random🎲", style=discord.ButtonStyle.success))
        self.add_item(PlayRandomFavoriteButton(bot_behavior, label="🎲Play Random Favorite⭐", style=discord.ButtonStyle.success))
        self.add_item(ListFavoritesButton(bot_behavior, label="⭐Favorites⭐", style=discord.ButtonStyle.success))
        self.add_item(ListUserFavoritesButton(bot_behavior, label="💖My Favorites💖", style=discord.ButtonStyle.success))
        self.add_item(ListBlacklistButton(bot_behavior, label="🗑️Blacklisted🗑️", style=discord.ButtonStyle.success))
        self.add_item(PlaySlapButton(bot_behavior, label="👋/🔫/🍳", style=discord.ButtonStyle.success))

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
                await interaction.followup.send("You need to be in a voice channel to play sounds! ��", ephemeral=True)

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
        modal = CreateListModal(self.bot_behavior)
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

class AddToListSelect(discord.ui.Select):
    def __init__(self, bot_behavior, sound_filename, lists):
        self.bot_behavior = bot_behavior
        self.sound_filename = sound_filename
        
        # Create options for each list, showing the creator's name
        options = [
            discord.SelectOption(
                label=f"{list_info[1]} (by {list_info[2]})",  # list_name (by creator)
                value=str(list_info[0]),  # list_id
                description=f"Created by {list_info[2]}"  # Show creator in description
            )
            for list_info in lists[:25]  # Discord limits to 25 options
        ]
        
        super().__init__(
            placeholder="Choose a list...",
            min_values=1,
            max_values=1,
            options=options
        )
        
    async def callback(self, interaction):
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

class CreateListModal(discord.ui.Modal):
    def __init__(self, bot_behavior):
        super().__init__(title="Create Sound List")
        self.bot_behavior = bot_behavior
        
        self.list_name = discord.ui.TextInput(
            label="List Name",
            placeholder="Enter a name for your sound list",
            min_length=1,
            max_length=100
        )
        self.add_item(self.list_name)
        
    async def on_submit(self, interaction):
        await interaction.response.defer()
        list_name = self.list_name.value
        
        # Check if the user already has a list with this name
        existing_list = Database().get_list_by_name(list_name, interaction.user.name)
        if existing_list:
            await interaction.followup.send(f"You already have a list named '{list_name}'.", ephemeral=True)
            return
            
        # Create the list
        list_id = Database().create_sound_list(list_name, interaction.user.name)
        if list_id:
            await interaction.followup.send(f"Created list '{list_name}'.", ephemeral=True)
            
            # Send a message confirming the creation
            await self.bot_behavior.send_message(
                title="List Created",
                description=f"Created a new sound list: '{list_name}'\nAdd sounds with `/addtolist`."
            )
        else:
            await interaction.followup.send("Failed to create list.", ephemeral=True)

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