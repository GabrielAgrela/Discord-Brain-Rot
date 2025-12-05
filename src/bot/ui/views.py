import discord
from discord.ui import View, Button, Select

class ControlsView(View):
    def __init__(self, behavior):
        super().__init__(timeout=None)
        self.behavior = behavior

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.red, custom_id="stop_button")
    async def stop_button_callback(self, button, interaction):
        if not self.behavior.is_admin_or_mod(interaction.user):
            await interaction.response.send_message("Only admins can stop playback.", ephemeral=True)
            return

        voice_client = interaction.guild.voice_client
        if voice_client and voice_client.is_playing():
            voice_client.stop()
            await interaction.response.send_message("Playback stopped.", ephemeral=True)
        else:
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)

    @discord.ui.button(label="Play Random", style=discord.ButtonStyle.green, custom_id="play_random_button")
    async def play_random_button_callback(self, button, interaction):
        await interaction.response.defer()
        await self.behavior.play_random_sound(interaction.user.name)

class SoundView(View):
    def __init__(self, behavior, sounds):
        super().__init__(timeout=None)
        # Implement pagination or list view for sounds
        pass

# Add more views as needed for lists, etc.
