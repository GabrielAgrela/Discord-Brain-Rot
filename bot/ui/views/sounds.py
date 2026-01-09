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
        from bot.ui.selects import STSCharacterSelect, SimilarSoundsSelect, AddToListSelect, EmbeddingSimilarSoundsSelect

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

        # Row 4: AI-based similar sounds (embedding similarity)
        embedding_similar = self._get_embedding_similar_sounds(audio_file)
        if embedding_similar:
            self.add_item(EmbeddingSimilarSoundsSelect(bot_behavior, embedding_similar, row=current_row))
            current_row += 1

        # Keep add to list at the end - but Discord only allows 5 rows max (0-4)
        # So we skip it if we already have 5 rows
        if include_add_to_list_select and current_row < 5:
            lists = Database().get_sound_lists()
            if lists:
                lists_containing_sound = Database().get_lists_containing_sound(self.audio_file)
                default_list_id = lists_containing_sound[0][0] if lists_containing_sound else None
                self.add_item(AddToListSelect(self.bot_behavior, self.audio_file, lists, default_list_id=default_list_id, row=current_row))
                current_row += 1

    def _get_embedding_similar_sounds(self, audio_file):
        """Get similar sounds using embedding similarity."""
        try:
            from bot.repositories.embedding_repository import EmbeddingRepository
            from bot.repositories.sound import SoundRepository
            from bot.services.embedding_service import EmbeddingService
            
            sound_repo = SoundRepository()
            emb_repo = EmbeddingRepository()
            service = EmbeddingService()
            
            # Get the sound from database
            sound = sound_repo.get_sound_by_name(audio_file)
            if not sound:
                return []
            
            sound_id = sound[0]
            
            # Get its embedding
            emb_data = emb_repo.get_embedding(sound_id)
            if not emb_data:
                return []  # No embedding yet
            
            emb_bytes, model, dim = emb_data
            query_emb = service.bytes_to_embedding(emb_bytes, dim if dim else service.embedding_dim)
            
            # Get all embeddings
            all_embeddings = emb_repo.get_all_embeddings()
            
            # Exclude self
            all_embeddings = [(sid, fn, eb) for sid, fn, eb in all_embeddings if sid != sound_id]
            
            # Find top 25 similar
            similar = service.find_similar(query_emb, all_embeddings, top_k=25)
            
            return similar
        except Exception as e:
            print(f"[SoundView] Error getting embedding similar sounds: {e}")
            return []

