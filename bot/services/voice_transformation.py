import discord
from bot.repositories import ActionRepository
from bot.tts import TTS
from typing import Optional

class VoiceTransformationService:
    """
    Service for Speech-to-Speech and Text-to-Speech transformations.
    
    This service currently wraps the legacy TTS class while providing
    a modern service interface.
    """
    
    def __init__(self, bot, audio_service, message_service):
        self.bot = bot
        self.audio_service = audio_service
        self.message_service = message_service
        self.action_repo = ActionRepository()
        
        # Legacy TTS expects a 'behavior' object with specific methods.
        # We pass self to satisfy those dependencies.
        self.tts_engine = TTS(self, bot)
    
    async def tts(self, user, speech: str, lang: str = "en", region: str = ""):
        """Standard gTTS text-to-speech."""
        self.action_repo.insert(user.name, "tts", speech)
        await self.tts_engine.save_as_mp3(speech, lang, region)

    async def tts_EL(self, user, speech: str, lang: str = "en", region: str = "", send_controls=True):
        """ElevenLabs text-to-speech."""
        self.action_repo.insert(user.name, "tts_EL", speech)
        await self.tts_engine.save_as_mp3_EL(speech, lang, region, send_controls=send_controls)

    async def sts_EL(self, user, sound: str, char: str = "ventura", region: str = ""):
        """ElevenLabs speech-to-speech voice transformation."""
        await self.tts_engine.speech_to_speech(sound, char, region)
        
    async def isolate_voice(self, sound_name: str):
        """ElevenLabs voice isolation feature."""
        await self.tts_engine.isolate_voice(sound_name)

    # --- Compatibility methods for legacy TTS class ---
    
    async def play_audio(self, *args, **kwargs):
        """Wrapper for AudioService.play_audio."""
        return await self.audio_service.play_audio(*args, **kwargs)
    
    async def send_message(self, *args, **kwargs):
        """Wrapper for MessageService.send_message."""
        return await self.message_service.send_message(*args, **kwargs)
        
    async def send_error_message(self, message: str):
        """Wrapper for MessageService.send_error."""
        return await self.message_service.send_error(message)

    def get_largest_voice_channel(self, guild: discord.Guild):
        """Wrapper for AudioService.get_largest_voice_channel."""
        return self.audio_service.get_largest_voice_channel(guild)
        
    @property
    def ffmpeg_path(self):
        """ffmpeg path from AudioService."""
        return self.audio_service.ffmpeg_path
