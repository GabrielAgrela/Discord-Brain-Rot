import discord
from discord.ui import View

class ControlsView(View):
    def __init__(self, bot_behavior):
        super().__init__(timeout=None)
        from bot.ui.buttons.misc import (
            PlayRandomButton, PlayRandomFavoriteButton, 
            ListFavoritesButton, ListUserFavoritesButton,
            BrainRotButton, StatsButton
        )
        from bot.ui.buttons.admin import MuteToggleButton, ListBlacklistButton
        from bot.ui.buttons.sounds import PlaySlapButton
        from bot.ui.buttons.upload import UploadSoundButton
        from bot.ui.buttons.list_buttons import ListLastScrapedSoundsButton

        self.add_item(PlayRandomButton(bot_behavior, label="🎲Play Random🎲", style=discord.ButtonStyle.success))
        self.add_item(PlayRandomFavoriteButton(bot_behavior, label="🎲Play Random Favorite⭐", style=discord.ButtonStyle.success))
        self.add_item(ListFavoritesButton(bot_behavior, label="⭐Favorites⭐", style=discord.ButtonStyle.success))
        self.add_item(ListUserFavoritesButton(bot_behavior, label="💖My Favorites💖", style=discord.ButtonStyle.success))
        self.add_item(ListBlacklistButton(bot_behavior, label="🗑️Blacklisted🗑️", style=discord.ButtonStyle.success))
        self.add_item(PlaySlapButton(bot_behavior, label="", emoji="👋", style=discord.ButtonStyle.success))

        self.add_item(BrainRotButton(bot_behavior, label="🧠Brain Rot🧠", style=discord.ButtonStyle.success))
        self.add_item(StatsButton(bot_behavior, label="📊Stats📊", style=discord.ButtonStyle.success))
        self.add_item(UploadSoundButton(bot_behavior, label="⬆️Upload⬆️", style=discord.ButtonStyle.success))
        self.add_item(ListLastScrapedSoundsButton(bot_behavior, label="🔽Last Downloaded Sounds🔽", style=discord.ButtonStyle.success))
        self.add_item(MuteToggleButton(bot_behavior))

class DownloadedSoundView(View):
    def __init__(self, bot_behavior, sound):
        super().__init__(timeout=None)
        from bot.ui.buttons.sounds import PlaySoundButton
        self.add_item(PlaySoundButton(bot_behavior, sound, style=discord.ButtonStyle.danger, label=sound.split('/')[-1].replace('.mp3', '')))
                          
class SoundView(View):
    def __init__(self, bot_behavior, similar_sounds):
        super().__init__(timeout=None)
        from bot.ui.buttons.sounds import PlaySoundButton
        for sound in similar_sounds:
            self.add_item(PlaySoundButton(bot_behavior, sound[1], style=discord.ButtonStyle.danger, label=sound[2].split('/')[-1].replace('.mp3', '')))
