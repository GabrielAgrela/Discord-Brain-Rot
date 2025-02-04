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
    def __init__(self, bot_behavior, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction):
        await interaction.response.defer()
        favorites = Database().get_sounds(num_sounds=1000, favorite=True)
        Database().insert_action(interaction.user.name, "list_favorites", len(favorites))
        if len(favorites) > 0:
            favorite_entries = [f"{favorite[0]}: {favorite[2]}" for favorite in favorites]
            favorites_content = "\n".join(favorite_entries)
            
            with open("favorites.txt", "w") as f:
                f.write(favorites_content)
            
            await self.bot_behavior.send_message("🤩 Favorites 🤩",description="Check https://gabrielagrela.com for more details! 🤛🏿🐵", file=discord.File("favorites.txt", "favorites.txt"), delete_time=30)
            os.remove("favorites.txt")  # Clean up the temporary file
        else:
            await interaction.message.channel.send("No favorite sounds found.")

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

class PlaySlapButton(Button):
    def __init__(self, bot_behavior, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction):
        await interaction.response.defer()
        asyncio.create_task(self.bot_behavior.play_request(random.choice(["slap.mp3", "tiro.mp3", "pubg-pan-sound-effect.mp3", "slap-oh_LGvkhyt.mp3", "kid-slap-oh.mp3", "gunshot-one.mp3"]), interaction.user.name, 1))
       

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
        asyncio.create_task(self.bot_behavior.display_top_users(interaction.user, number=5, days=30, by="plays"))


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
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior
        self.sound_name = sound_name

    async def callback(self, interaction):
        await interaction.response.defer()
        asyncio.create_task(self.bot_behavior.play_audio(self.bot_behavior.get_user_voice_channel(interaction.guild, interaction.user.name), self.sound_name, interaction.user.name))

class SoundBeingPlayedView(View):
    def __init__(self, bot_behavior, audio_file):
        super().__init__(timeout=None)
        self.add_item(ReplayButton(bot_behavior, audio_file, label=None, emoji="🔁", style=discord.ButtonStyle.primary))
        self.add_item(FavoriteButton(bot_behavior, audio_file))
        self.add_item(BlacklistButton(bot_behavior, audio_file))
        self.add_item(ChangeSoundNameButton(bot_behavior, audio_file, label="📝", style=discord.ButtonStyle.primary))
        self.add_item(IsolateButton(bot_behavior, audio_file, label="🧑‍🎤🎶❌", style=discord.ButtonStyle.primary))
        self.add_item(STSButton(bot_behavior, audio_file, "ventura", label="🐷", style=discord.ButtonStyle.primary))
        self.add_item(STSButton(bot_behavior, audio_file, "tyson", label="🐵", style=discord.ButtonStyle.primary))
        self.add_item(STSButton(bot_behavior, audio_file, "costa", label="🐗", style=discord.ButtonStyle.primary))
        

class ControlsView(View):
    def __init__(self, bot_behavior):
        super().__init__(timeout=None)
        self.add_item(PlayRandomButton(bot_behavior, label="🎲Play Random🎲", style=discord.ButtonStyle.success))
        self.add_item(PlayRandomFavoriteButton(bot_behavior, label="🎲Play Random Favorite⭐", style=discord.ButtonStyle.success))
        self.add_item(PlaySlapButton(bot_behavior, label="👋/🔫/🍳", style=discord.ButtonStyle.success))
        self.add_item(ListFavoritesButton(bot_behavior, label="⭐Favorites⭐", style=discord.ButtonStyle.success))
        self.add_item(ListBlacklistButton(bot_behavior, label="🗑️Blacklisted🗑️", style=discord.ButtonStyle.success))
        
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
            self.add_item(PlaySoundButton(bot_behavior, sound[2], style=discord.ButtonStyle.danger, label=sound[2].split('/')[-1].replace('.mp3', '')))