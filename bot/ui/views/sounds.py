import discord
from discord.ui import View
from bot.database import Database

class SoundBeingPlayedView(View):
    def __init__(self, bot_behavior, audio_file, user_id=None, include_add_to_list_select: bool = False):
        super().__init__(timeout=None)
        self.bot_behavior = bot_behavior
        self.audio_file = audio_file
        self.user_id = user_id

        from bot.ui.buttons.sounds import (
            ReplayButton, FavoriteButton, 
            SlapButton, DownloadSoundButton, ChangeSoundNameButton,
            AssignUserEventButton
        )
        from bot.ui.selects import STSCharacterSelect, AddToListSelect

        # Row 0: Common Actions (3 buttons)
        self.add_item(ReplayButton(bot_behavior=bot_behavior, audio_file=audio_file, emoji="🔁", style=discord.ButtonStyle.primary, row=0))
        self.add_item(FavoriteButton(bot_behavior=bot_behavior, audio_file=audio_file, row=0))
        self.add_item(SlapButton(bot_behavior=bot_behavior, audio_file=audio_file, row=0))
        
        # Row 1: Management & Download (3 buttons)
        self.add_item(DownloadSoundButton(bot_behavior=bot_behavior, audio_file=audio_file, row=1))
        self.add_item(ChangeSoundNameButton(bot_behavior=bot_behavior, sound_name=audio_file, emoji="📝", style=discord.ButtonStyle.primary, row=1))
        self.add_item(AssignUserEventButton(bot_behavior=bot_behavior, audio_file=audio_file, emoji="📢", style=discord.ButtonStyle.primary, row=1))
        
        # Row 2: Voice Transformation
        self.add_item(STSCharacterSelect(bot_behavior=bot_behavior, audio_file=audio_file, row=2))

        current_row = 3
        if include_add_to_list_select:
            lists = Database().get_sound_lists()
            if lists:
                lists_containing_sound = Database().get_lists_containing_sound(self.audio_file)
                default_list_id = lists_containing_sound[0][0] if lists_containing_sound else None
                self.add_item(AddToListSelect(self.bot_behavior, self.audio_file, lists, default_list_id=default_list_id, row=current_row))
                current_row += 1

class SoundBeingPlayedWithSuggestionsView(View):
    def __init__(self, bot_behavior, audio_file, similar_sounds, user_id=None, include_add_to_list_select: bool = False):
        super().__init__(timeout=None)
        self.bot_behavior = bot_behavior
        self.audio_file = audio_file
        self.user_id = user_id
        self.similar_sounds = similar_sounds

        from bot.ui.buttons.sounds import (
            ReplayButton, FavoriteButton, 
            SlapButton, DownloadSoundButton, ChangeSoundNameButton,
            AssignUserEventButton
        )
        from bot.ui.selects import STSCharacterSelect, SimilarSoundsSelect, AddToListSelect

        # Row 0: Common Actions (3 buttons)
        self.add_item(ReplayButton(bot_behavior=bot_behavior, audio_file=audio_file, emoji="🔁", style=discord.ButtonStyle.primary, row=0))
        self.add_item(FavoriteButton(bot_behavior=bot_behavior, audio_file=audio_file, row=0))
        self.add_item(SlapButton(bot_behavior=bot_behavior, audio_file=audio_file, row=0))
        
        # Row 1: Management & Download (3 buttons)
        self.add_item(DownloadSoundButton(bot_behavior=bot_behavior, audio_file=audio_file, row=1))
        self.add_item(ChangeSoundNameButton(bot_behavior=bot_behavior, sound_name=audio_file, emoji="📝", style=discord.ButtonStyle.primary, row=1))
        self.add_item(AssignUserEventButton(bot_behavior=bot_behavior, audio_file=audio_file, emoji="📢", style=discord.ButtonStyle.primary, row=1))
        
        # Row 2: Voice Transformation
        self.add_item(STSCharacterSelect(bot_behavior=bot_behavior, audio_file=audio_file, row=2))

        current_row = 3
        if similar_sounds:
            self.add_item(SimilarSoundsSelect(bot_behavior, similar_sounds, row=current_row))
            current_row += 1

        if include_add_to_list_select:
            lists = Database().get_sound_lists()
            if lists:
                lists_containing_sound = Database().get_lists_containing_sound(self.audio_file)
                default_list_id = lists_containing_sound[0][0] if lists_containing_sound else None
                self.add_item(AddToListSelect(self.bot_behavior, self.audio_file, lists, default_list_id=default_list_id, row=current_row))
                current_row += 1
