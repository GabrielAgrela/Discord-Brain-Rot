import discord
from discord.ui import Button, View

class UploadSoundButton(Button):
    """Button that opens the unified upload modal (URL + File upload)."""
    
    def __init__(self, bot_behavior, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction):
        from bot.ui.modals import UploadSoundWithFileModal
        modal = UploadSoundWithFileModal(self.bot_behavior)
        await interaction.response.send_modal(modal)

class UploadURLChoiceButton(Button):
    def __init__(self, bot_behavior):
        super().__init__(label="Upload via URL", style=discord.ButtonStyle.primary)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction: discord.Interaction):
        from bot.ui.modals import UploadSoundModal
        modal = UploadSoundModal(self.bot_behavior)
        await interaction.response.send_modal(modal)

class UploadMP3ChoiceButton(Button):
    """Button that opens the new FileUpload modal for direct MP3 uploads."""
    
    def __init__(self, bot_behavior):
        super().__init__(label="Upload MP3 File", style=discord.ButtonStyle.success)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction: discord.Interaction):
        from bot.ui.modals import UploadSoundWithFileModal
        modal = UploadSoundWithFileModal(self.bot_behavior)
        await interaction.response.send_modal(modal)

class UploadChoiceView(View):
    def __init__(self, bot_behavior):
        super().__init__(timeout=60)
        self.add_item(UploadURLChoiceButton(bot_behavior))
        self.add_item(UploadMP3ChoiceButton(bot_behavior))

class UploadMP3FileButton(Button):
    def __init__(self, bot_behavior, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction):
        await self.bot_behavior._sound_service.prompt_upload_sound(interaction)
