import discord
from discord.ui import Button, View

class UploadSoundButton(Button):
    def __init__(self, bot_behavior, **kwargs):
        super().__init__(**kwargs)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction):
        try:
            view = UploadChoiceView(self.bot_behavior)
            await interaction.response.send_message(
                content="Choose how you want to upload:",
                view=view,
                ephemeral=True,
                delete_after=60
            )
        except Exception:
            from bot.ui.modals import UploadSoundModal
            modal = UploadSoundModal(self.bot_behavior)
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
    def __init__(self, bot_behavior):
        super().__init__(label="Upload MP3 File", style=discord.ButtonStyle.success)
        self.bot_behavior = bot_behavior

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.bot_behavior._sound_service.prompt_upload_sound(interaction)

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
