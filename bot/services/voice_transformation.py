import discord
from bot.repositories import ActionRepository
from bot.tts import TTS
from typing import Optional
import asyncio
import os

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
        self._guild_locks: dict[int, asyncio.Lock] = {}
        self._tts_max_jobs = max(1, int(os.getenv("TTS_MAX_CONCURRENT_JOBS", "2")))
        self._tts_semaphore = asyncio.Semaphore(self._tts_max_jobs)
        
        # Legacy TTS expects a 'behavior' object with specific methods.
        # We pass self to satisfy those dependencies.
        self.tts_engine = TTS(self, bot)

    @staticmethod
    def _resolve_guild_id(user) -> Optional[int]:
        """Resolve guild ID from a Discord user/member object."""
        guild = getattr(user, "guild", None)
        return guild.id if guild else None

    def _get_guild_lock(self, guild_id: Optional[int]) -> asyncio.Lock:
        """Get per-guild lock so one guild cannot block another."""
        if guild_id is None:
            guild_id = 0
        if guild_id not in self._guild_locks:
            self._guild_locks[guild_id] = asyncio.Lock()
        return self._guild_locks[guild_id]

    async def _run_tts_job(self, guild_id: Optional[int], job_coro):
        """Run a TTS/STS job with global and per-guild concurrency control."""
        queue_start = asyncio.get_running_loop().time()
        async with self._tts_semaphore:
            queue_wait = asyncio.get_running_loop().time() - queue_start
            print(f"[VoiceTransformationService] [PERF] tts_queue_wait guild_id={guild_id} wait={queue_wait:.4f}s")
            lock = self._get_guild_lock(guild_id)
            async with lock:
                return await job_coro
    
    async def tts(self, user, speech: str, lang: str = "en", region: str = "",
                  loading_message=None, requester_avatar_url=None):
        """Standard gTTS text-to-speech."""
        guild_id = self._resolve_guild_id(user)
        self.action_repo.insert(user.name, "tts", speech, guild_id=guild_id)
        requester_name = getattr(user, 'display_name', getattr(user, 'name', str(user)))
        await self._run_tts_job(guild_id, self.tts_engine.save_as_mp3(
            speech, lang, region,
            loading_message=loading_message,
            requester_avatar_url=requester_avatar_url,
            requester_name=requester_name,
            guild_id=guild_id,
        ))

    async def tts_EL(self, user, speech: str, lang: str = "en", region: str = "", send_controls=True,
                     loading_message=None, requester_avatar_url=None, sts_thumbnail_url=None):
        """ElevenLabs text-to-speech."""
        guild_id = self._resolve_guild_id(user)
        self.action_repo.insert(user.name, "tts_EL", speech, guild_id=guild_id)
        requester_name = getattr(user, 'display_name', getattr(user, 'name', str(user)))
        await self._run_tts_job(guild_id, self.tts_engine.save_as_mp3_EL(
            speech, lang, region, send_controls=send_controls,
            loading_message=loading_message,
            requester_avatar_url=requester_avatar_url,
            sts_thumbnail_url=sts_thumbnail_url,
            requester_name=requester_name,
            guild_id=guild_id,
        ))

    async def sts_EL(self, user, sound: str, char: str = "ventura", region: str = "",
                     loading_message=None, requester_avatar_url=None, sts_thumbnail_url=None):
        """ElevenLabs speech-to-speech voice transformation."""
        guild_id = self._resolve_guild_id(user)
        requester_name = getattr(user, 'display_name', getattr(user, 'name', str(user)))
        await self._run_tts_job(guild_id, self.tts_engine.speech_to_speech(
            sound, char, region,
            loading_message=loading_message,
            requester_avatar_url=requester_avatar_url,
            sts_thumbnail_url=sts_thumbnail_url,
            requester_name=requester_name,
            guild_id=guild_id,
        ))
        
    async def isolate_voice(self, sound_name: str, guild_id: Optional[int] = None):
        """ElevenLabs voice isolation feature."""
        await self._run_tts_job(guild_id, self.tts_engine.isolate_voice(sound_name, guild_id=guild_id))

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
