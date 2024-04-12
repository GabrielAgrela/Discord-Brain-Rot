from datetime import datetime
import random
from discord.ui import Button, View
import discord
import asyncio


class ReplayButton(Button):
    def __init__(self, bot_behavior, audio_file, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior
        self.audio_file = audio_file
        

    async def callback(self, interaction):
        await interaction.response.defer()
        asyncio.create_task(self.bot_behavior.play_audio(interaction.message.channel, self.audio_file, interaction.user.name))

class FavoriteButton(Button):
    def __init__(self, bot_behavior, audio_file):
        if bot_behavior.db.is_favorite(audio_file):
            super().__init__(label="⭐❌", style=discord.ButtonStyle.primary)
        else:
            super().__init__(label="⭐", style=discord.ButtonStyle.primary)
        self.bot_behavior = bot_behavior
        self.audio_file = audio_file

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        self.bot_behavior.db.update_favorite_status(self.audio_file, not self.bot_behavior.db.is_favorite(self.audio_file))
        await interaction.message.edit(view=SoundBeingPlayedView(self.bot_behavior, self.audio_file))

class BlacklistButton(Button):
    def __init__(self, bot_behavior, audio_file):
        if bot_behavior.db.is_blacklisted(audio_file):
            super().__init__( label="🗑️❌", style=discord.ButtonStyle.primary)
        else:
            super().__init__(label="", emoji="🗑️", style=discord.ButtonStyle.primary)
        self.bot_behavior = bot_behavior
        self.audio_file = audio_file

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        self.bot_behavior.db.update_blacklist_status(self.audio_file, not self.bot_behavior.db.is_blacklisted(self.audio_file))
        view = SoundBeingPlayedView(self.bot_behavior, self.audio_file)
        await interaction.message.edit(view=view)

class ChangeSoundNameButton(Button):
    def __init__(self, bot_behavior, sound_name, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior
        self.sound_name = sound_name

    async def callback(self, interaction):
        await interaction.response.defer()
        new_name = await self.bot_behavior.get_new_name(interaction)
        if new_name:
            await self.bot_behavior.change_filename(self.sound_name, new_name)

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
        favorites = self.bot_behavior.db.get_favorite_sounds()
        if len(favorites) > 0:
            await self.bot_behavior.write_list(favorites, "Favorite sounds")
        else:
            await interaction.message.channel.send("No favorite sounds found.")

class ListBlacklistButton(Button):
    def __init__(self, bot_behavior, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction):
        await interaction.response.defer()
        blacklisted = self.bot_behavior.db.get_blacklisted_sounds()
        if len(blacklisted) > 0:
            await self.bot_behavior.write_list(blacklisted, "Blacklisted sounds")
        else:
            await interaction.message.channel.send("No blacklisted sounds found.")

class PlaySlapButton(Button):
    def __init__(self, bot_behavior, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction):
        await interaction.response.defer()
        asyncio.create_task(self.bot_behavior.play_request(random.choice(["slap.mp3", "tiro.mp3", "pubg-pan-sound-effect.mp3"]), interaction.user.name, 1))
       

class ListSoundsButton(Button):
    def __init__(self, bot_behavior, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction):
        await interaction.response.defer()
        asyncio.create_task(self.bot_behavior.list_sounds())

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
        if (datetime.now() - self.bot_behavior.lastInteractionDateTime).total_seconds() > 10:
            self.bot_behavior.color = discord.Color.teal()
            task = random.choice([self.bot_behavior.family_guy, self.bot_behavior.family_guy, self.bot_behavior.family_guy, self.bot_behavior.subway_surfers, self.bot_behavior.slice_all])
            asyncio.create_task(task())
            self.bot_behavior.lastInteractionDateTime = datetime.now()
        else:
            print("Too many requests")


class ListTopSoundsButton(Button):
    def __init__(self, bot_behavior, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction):
        await interaction.response.defer()
        asyncio.create_task(self.bot_behavior.player_history_db.write_top_played_sounds())

class ListTopUsersButton(Button):
    def __init__(self, bot_behavior, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction):
        await interaction.response.defer()
        asyncio.create_task(self.bot_behavior.player_history_db.write_top_users())

class ListLastScrapedSoundsButton(Button):
    def __init__(self, bot_behavior, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction):
        await interaction.response.defer()
        asyncio.create_task(self.bot_behavior.list_sounds(25))

class PlaySoundButton(Button):
    def __init__(self, bot_behavior, sound_name, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior
        self.sound_name = sound_name

    async def callback(self, interaction):
        await interaction.response.defer()
        asyncio.create_task(self.bot_behavior.play_audio(interaction.message.channel, self.sound_name, interaction.user.name))

class SoundBeingPlayedView(View):
    def __init__(self, bot_behavior, audio_file):
        super().__init__(timeout=None)
        self.add_item(ReplayButton(bot_behavior, audio_file, label=None, emoji="🔁", style=discord.ButtonStyle.primary))
        self.add_item(FavoriteButton(bot_behavior, audio_file))
        self.add_item(BlacklistButton(bot_behavior, audio_file))
        self.add_item(ChangeSoundNameButton(bot_behavior, audio_file, label="📝", style=discord.ButtonStyle.primary))

class ControlsView(View):
    def __init__(self, bot_behavior):
        super().__init__(timeout=None)
        self.add_item(PlayRandomButton(bot_behavior, label="🎲Play Random🎲", style=discord.ButtonStyle.success))
        self.add_item(PlayRandomFavoriteButton(bot_behavior, label="🎲Play Random Favorite⭐", style=discord.ButtonStyle.success))
        self.add_item(PlaySlapButton(bot_behavior, label="👋/🔫/🍳", style=discord.ButtonStyle.success))
        self.add_item(ListFavoritesButton(bot_behavior, label="⭐Favorites⭐", style=discord.ButtonStyle.success))
        self.add_item(ListBlacklistButton(bot_behavior, label="🗑️Blacklisted🗑️", style=discord.ButtonStyle.success))
        
        self.add_item(BrainRotButton(bot_behavior, label="🧠Brain Rot🧠", style=discord.ButtonStyle.success))
        self.add_item(ListTopSoundsButton(bot_behavior, label="📈Top Sounds📈", style=discord.ButtonStyle.success))
        self.add_item(ListTopUsersButton(bot_behavior, label="📊Top Users📊", style=discord.ButtonStyle.success))
        self.add_item(ListSoundsButton(bot_behavior, label="📜List Sounds📜", style=discord.ButtonStyle.success))
        self.add_item(ListLastScrapedSoundsButton(bot_behavior, label="🔽Last Downloaded Sounds🔽", style=discord.ButtonStyle.success))

class SoundView(View):
    def __init__(self, bot_behavior, similar_sounds):
        super().__init__(timeout=None)
        for sound in similar_sounds:
            self.add_item(PlaySoundButton(bot_behavior, sound, style=discord.ButtonStyle.danger, label=sound.split('/')[-1].replace('.mp3', '')))