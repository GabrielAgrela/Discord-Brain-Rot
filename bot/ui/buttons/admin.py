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
                # Resolve channel similar to PlaySlapButton
                channel = self.bot_behavior._audio_service.get_user_voice_channel(interaction.guild, interaction.user.name)
                if not channel:
                    channel = self.bot_behavior._audio_service.get_largest_voice_channel(interaction.guild)
                
                if channel:
                    asyncio.create_task(self.bot_behavior._audio_service.play_slap(channel, random_slap[2], interaction.user.name))
            
            await self.bot_behavior._mute_service.activate(duration_seconds=1800, requested_by=interaction.user)
            Database().insert_action(interaction.user.name, "mute_30_minutes", "")

        self._refresh_state()
        if interaction.message and self.view:
            try:
                await interaction.message.edit(view=self.view)
            except discord.NotFound:
                pass

