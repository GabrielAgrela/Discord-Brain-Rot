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
        asyncio.create_task(self.bot_behavior.sts_EL(interaction.message.channel, self.audio_file, self.char))
        Database().insert_action(interaction.user.name, "sts_EL", Database().get_sound(self.audio_file, True)[0])

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
        self.update_button_state()

    def update_button_state(self):
        if Database().get_sound(self.audio_file, True)[3]:  # Check if favorite (index 3)
            super().__init__(label="⭐❌", style=discord.ButtonStyle.primary)
        else:
            super().__init__(label="⭐", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        sound = Database().get_sound(self.audio_file, True)
        favorite = 1 if not sound[3] else 0
        await Database().update_sound(sound[2], None, favorite)

        
        # Update the button state
        self.update_button_state()
        
        # Update the entire view
        await interaction.message.edit(view=SoundBeingPlayedView(self.bot_behavior, self.audio_file))
        Database().insert_action(interaction.user.name, "favorite_sound", sound[0])

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
        if (datetime.now() - self.bot_behavior.lastInteractionDateTime).total_seconds() > 1:
            asyncio.create_task(interaction.channel.send("Gertrudes may need some seconds for this one", delete_after=3))
            self.bot_behavior.color = discord.Color.teal()
            task = random.choice([self.bot_behavior.family_guy, self.bot_behavior.family_guy, self.bot_behavior.family_guy, self.bot_behavior.subway_surfers, self.bot_behavior.slice_all])
            asyncio.create_task(task(interaction.user))
            self.bot_behavior.lastInteractionDateTime = datetime.now()
        else:
            asyncio.create_task(interaction.channel.send("STOP SPAMMING, GERTRUDES IS RUNNING ON 150€ AMAZON SECOND HAND THINKPAD 🔥🔥🔥", delete_after=3))
        await interaction.response.defer()

class StatsButton(Button):
    def __init__(self, bot_behavior, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction):
        await interaction.response.defer()
        asyncio.create_task(self.bot_behavior.display_top_users(interaction.user, number=5, days=7, by="plays"))


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
        self.add_item(ReplayButton(bot_behavior, audio_file, label=None, emoji="🔁", style=discord.ButtonStyle.primary))
        self.add_item(FavoriteButton(bot_behavior, audio_file))
        self.add_item(BlacklistButton(bot_behavior, audio_file))
        self.add_item(ChangeSoundNameButton(bot_behavior, audio_file, label="📝", style=discord.ButtonStyle.primary))
        self.add_item(SlapButton(bot_behavior, audio_file))
        #self.add_item(IsolateButton(bot_behavior, audio_file, label="🧑‍🎤🎶❌", style=discord.ButtonStyle.primary))
        self.add_item(STSButton(bot_behavior, audio_file, "ventura", label="🐷", style=discord.ButtonStyle.primary))
        self.add_item(STSButton(bot_behavior, audio_file, "tyson", label="🐵", style=discord.ButtonStyle.primary))
        self.add_item(STSButton(bot_behavior, audio_file, "costa", label="🐗", style=discord.ButtonStyle.primary))
        self.add_item(JoinEventButton(bot_behavior, audio_file, user_id))
        self.add_item(LeaveEventButton(bot_behavior, audio_file, user_id))
        

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
        
        description = (f"Your favorite sounds based on your history\n" if is_user_favorites 
                      else f"All favorite sounds in the database\n")
        description += f"Showing sounds {current_page_start}-{current_page_end} of {total_favorites}"
        
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
                description=f"Your favorite sounds based on your history\nShowing sounds 1-{min(20, len(favorites))} of {len(favorites)}",
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