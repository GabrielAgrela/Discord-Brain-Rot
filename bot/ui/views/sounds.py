import discord
from discord.ui import View
from bot.database import Database

class SoundBeingPlayedView(View):
    def __init__(self, bot_behavior, audio_file, user_id=None, include_add_to_list_select: bool = False, include_sts_select: bool = True, progress_label: str = "▶️ 0:01", show_controls: bool = False):
        super().__init__(timeout=None)
        self.bot_behavior = bot_behavior
        self.audio_file = audio_file
        self.user_id = user_id
        self.include_add_to_list_select = include_add_to_list_select
        self.include_sts_select = include_sts_select
        self.initial_progress_label = progress_label
        self.show_controls = show_controls
        self.progress_button = None
        
        self._setup_items()

    def _setup_items(self):
        self.clear_items()
        
        from bot.ui.buttons.sounds import (
            ReplayButton, FavoriteButton, 
            SlapButton, ChangeSoundNameButton,
            AssignUserEventButton, ToggleControlsButton,
            SendControlsButton
        )
        from bot.ui.selects import STSCharacterSelect, AddToListSelect

        # Row 0: Progress Button + Toggle Button + Remote Button
        current_label = self.progress_button.label if self.progress_button else self.initial_progress_label
        self.progress_button = discord.ui.Button(style=discord.ButtonStyle.primary, label=current_label, disabled=True, row=0)
        self.add_item(self.progress_button)
        
        toggle_emoji = "🔼" if self.show_controls else "🔽"
        self.add_item(ToggleControlsButton(emoji=toggle_emoji, row=0))
        self.add_item(SendControlsButton(row=0)) # Always visible in Row 0 next to the eye ✅
        
        if self.show_controls:
            # Row 1: Common Actions (5 buttons)
            self.add_item(ReplayButton(bot_behavior=self.bot_behavior, audio_file=self.audio_file, emoji="🔁", style=discord.ButtonStyle.primary, row=1))
            self.add_item(FavoriteButton(bot_behavior=self.bot_behavior, audio_file=self.audio_file, row=1))
            self.add_item(SlapButton(bot_behavior=self.bot_behavior, audio_file=self.audio_file, row=1))
            self.add_item(ChangeSoundNameButton(bot_behavior=self.bot_behavior, sound_name=self.audio_file, emoji="📝", style=discord.ButtonStyle.primary, row=1))
            self.add_item(AssignUserEventButton(bot_behavior=self.bot_behavior, audio_file=self.audio_file, emoji="📢", style=discord.ButtonStyle.primary, row=1))
            
            current_row = 2
            
            # Row 2+: Selects
            if self.include_sts_select:
                self.add_item(STSCharacterSelect(bot_behavior=self.bot_behavior, audio_file=self.audio_file, row=current_row))
                current_row += 1

            if self.include_add_to_list_select:
                lists = Database().get_sound_lists()
                if lists:
                    lists_containing_sound = Database().get_lists_containing_sound(self.audio_file)
                    default_list_id = lists_containing_sound[0][0] if lists_containing_sound else None
                    self.add_item(AddToListSelect(self.bot_behavior, self.audio_file, lists, default_list_id=default_list_id, row=current_row))
                    current_row += 1

    def update_progress_label(self, label: str):
        """Update the label of the progress button."""
        if self.progress_button:
            self.progress_button.label = label

    def update_progress_emoji(self, emoji: str):
        """Update only the emoji prefix of the progress button, preserving bar and time."""
        if self.progress_button and self.progress_button.label:
            current = self.progress_button.label
            # Label format: "▶️ {bar} {time}" or similar - replace first emoji
            parts = current.split(" ", 1)
            if len(parts) == 2:
                self.progress_button.label = f"{emoji} {parts[1]}"
            else:
                self.progress_button.label = emoji

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item):
        print(f"DEBUG: SoundBeingPlayedView ERROR: {error} | Item: {item}")
        import traceback
        traceback.print_exc()
        if not interaction.response.is_done():
            await interaction.response.send_message("An error occurred. 😭", ephemeral=True)
        else:
            await interaction.followup.send("An error occurred. 😭", ephemeral=True)

class SoundBeingPlayedWithSuggestionsView(View):
    def __init__(self, bot_behavior, audio_file, similar_sounds, user_id=None, include_add_to_list_select: bool = False, progress_label: str = "▶️ 0:01", show_controls: bool = False):
        super().__init__(timeout=None)
        self.bot_behavior = bot_behavior
        self.audio_file = audio_file
        self.user_id = user_id
        self.similar_sounds = similar_sounds
        self.include_add_to_list_select = include_add_to_list_select
        self.initial_progress_label = progress_label
        self.show_controls = show_controls
        self.progress_button = None
        
        self._setup_items()

    def _setup_items(self):
        self.clear_items()
        
        from bot.ui.buttons.sounds import (
            ReplayButton, FavoriteButton, 
            SlapButton, ChangeSoundNameButton,
            AssignUserEventButton, ToggleControlsButton,
            SendControlsButton
        )
        from bot.ui.selects import STSCharacterSelect, SimilarSoundsSelect, AddToListSelect

        # Row 0: Progress Button + Toggle Button + Remote Button
        current_label = self.progress_button.label if self.progress_button else self.initial_progress_label
        self.progress_button = discord.ui.Button(style=discord.ButtonStyle.primary, label=current_label, disabled=True, row=0)
        self.add_item(self.progress_button)
        
        toggle_emoji = "🔼" if self.show_controls else "🔽"
        self.add_item(ToggleControlsButton(emoji=toggle_emoji, row=0))
        self.add_item(SendControlsButton(row=0)) # Always visible in Row 0 next to the eye ✅
        
        if self.show_controls:
            # Row 1: Common Actions (5 buttons)
            self.add_item(ReplayButton(bot_behavior=self.bot_behavior, audio_file=self.audio_file, emoji="🔁", style=discord.ButtonStyle.primary, row=1))
            self.add_item(FavoriteButton(bot_behavior=self.bot_behavior, audio_file=self.audio_file, row=1))
            self.add_item(SlapButton(bot_behavior=self.bot_behavior, audio_file=self.audio_file, row=1))
            self.add_item(ChangeSoundNameButton(bot_behavior=self.bot_behavior, sound_name=self.audio_file, emoji="📝", style=discord.ButtonStyle.primary, row=1))
            self.add_item(AssignUserEventButton(bot_behavior=self.bot_behavior, audio_file=self.audio_file, emoji="📢", style=discord.ButtonStyle.primary, row=1))
            
            # Row 2: Voice Transformation
            self.add_item(STSCharacterSelect(bot_behavior=self.bot_behavior, audio_file=self.audio_file, row=2))

            current_row = 3
            if self.similar_sounds:
                self.add_item(SimilarSoundsSelect(self.bot_behavior, self.similar_sounds, row=current_row))
                current_row += 1

            if self.include_add_to_list_select:
                lists = Database().get_sound_lists()
                if lists:
                    lists_containing_sound = Database().get_lists_containing_sound(self.audio_file)
                    default_list_id = lists_containing_sound[0][0] if lists_containing_sound else None
                    self.add_item(AddToListSelect(self.bot_behavior, self.audio_file, lists, default_list_id=default_list_id, row=current_row))
                    current_row += 1

    def update_progress_label(self, label: str):
        """Update the label of the progress button."""
        if self.progress_button:
            self.progress_button.label = label

    def update_progress_emoji(self, emoji: str):
        """Update only the emoji prefix of the progress button, preserving bar and time."""
        if self.progress_button and self.progress_button.label:
            current = self.progress_button.label
            # Label format: "▶️ {bar} {time}" or similar - replace first emoji
            parts = current.split(" ", 1)
            if len(parts) == 2:
                self.progress_button.label = f"{emoji} {parts[1]}"
            else:
                self.progress_button.label = emoji
