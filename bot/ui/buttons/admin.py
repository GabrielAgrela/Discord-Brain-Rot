import discord
from discord.ui import Button
import asyncio
import random
import os
from bot.database import Database

class MuteToggleButton(Button):
    def __init__(self, bot_behavior, **kwargs):
        kwargs.setdefault("style", discord.ButtonStyle.success)
        kwargs.setdefault("label", "🔇30m Mute🔇")
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior
        self._refresh_state()

    def _refresh_state(self):
        if self.bot_behavior._mute_service.get_remaining_seconds() > 0:
            self.label = "🔊Unmute🔊"
        else:
            self.label = "🔇30m Mute🔇"

    async def callback(self, interaction):
        await interaction.response.defer()

        is_muted = self.bot_behavior._mute_service.get_remaining_seconds() > 0

        if is_muted:
            await self.bot_behavior._mute_service.deactivate(requested_by=interaction.user)
            Database().insert_action(interaction.user.name, "unmute", "")
        else:
            slap_sounds = Database().get_sounds(slap=True, num_sounds=100)
            if slap_sounds:
                random_slap = random.choice(slap_sounds)
                asyncio.create_task(self.bot_behavior._sound_service.play_request(random_slap[1], interaction.user.name, exact=True))
                await asyncio.sleep(3)
            
            await self.bot_behavior._mute_service.activate(duration_seconds=1800, requested_by=interaction.user)
            Database().insert_action(interaction.user.name, "mute_30_minutes", "")

        self._refresh_state()
        if interaction.message and self.view:
            try:
                await interaction.message.edit(view=self.view)
            except discord.NotFound:
                pass

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
            
            await self.bot_behavior._message_service.send_message("🗑️ Blacklisted Sounds 🗑️", file=discord.File("blacklisted.txt", "blacklisted.txt"), delete_time=30)
            os.remove("blacklisted.txt")  
        else:
            await interaction.followup.send("No blacklisted sounds found.", ephemeral=True)
