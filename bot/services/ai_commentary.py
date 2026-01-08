import asyncio
import os
import time
import base64
import json
import io
import wave
import audioop
import discord
import random
from pydub import AudioSegment
from typing import List, Optional
from bot.services.llm import LLMService

class AICommentaryService:
    """
    Service to automatically trigger AI commentary based on voice activity.
    """
    def __init__(self, behavior):
        self.behavior = behavior
        self.llm_service = LLMService()
        self.last_trigger_time = 0
        self.min_speech_duration = 2.0
        self.is_processing = False
        self._set_random_cooldown()
        
        # Directory for debug audio (kept for structure, but writing disabled)
        self.debug_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "Debug", "llm_audio"))
        os.makedirs(self.debug_dir, exist_ok=True)

    def _set_random_cooldown(self):
        """Set a random cooldown between 1 and 3 hours."""
        self.cooldown_seconds = random.randint(3600, 10800)
        print(f"[AICommentary] Next sighting scheduled with {self.cooldown_seconds/3600:.1f} hour cooldown.")

    def should_trigger(self) -> bool:
        """Check if the cooldown has passed and we aren't already processing."""
        if self.is_processing:
            return False
        
        time_since_last = time.time() - self.last_trigger_time
        if time_since_last < self.cooldown_seconds:
            # print(f"[AICommentary] Cooldown active: {self.cooldown_seconds - time_since_last:.1f}s remaining")
            return False
        return True

    def get_cooldown_remaining(self) -> float:
        """Return the number of seconds remaining until the next commentary can be triggered."""
        time_since_last = time.time() - self.last_trigger_time
        remaining = self.cooldown_seconds - time_since_last
        return max(0, remaining)

    async def trigger_commentary(self, guild_id: int):
        """Orchestrate the AI commentary flow."""
        if not self.should_trigger():
            return
            
        self.is_processing = True
        self.last_trigger_time = time.time()
        
        # Wait 5 seconds to capture more of the sentence/context
        await asyncio.sleep(5.0)
        
        try:
            guild = self.behavior.bot.get_guild(guild_id)
            if not guild:
                self.is_processing = False
                return

            # Find a text channel to send the transcription (defaulting to a likely one)
            # Ideally this would be the last channel used or a configured one
            channel = self._get_target_channel(guild)
            if not channel:
                print(f"[AICommentary] No text channel found for guild {guild_id}")
                self.is_processing = False
                return

            # 1. Get audio and user context
            audio_pcm, active_users = self.behavior._audio_service.get_last_audio_segment_with_users(guild_id, seconds=10)
            
            if not audio_pcm or not active_users:
                print("[AICommentary] No audio or users found for trigger.")
                self.is_processing = False
                return

            print(f"[AICommentary] Triggered! Users: {active_users}")

            # Send initial "Processing" message using the standard function
            processing_msg = await self.behavior.send_message(
                title="André Ventura a ouvir...",
                description=f"Ouvi {len(active_users)} pessoas ({', '.join(active_users)}). A processar o áudio... 🎙️",
                channel=channel
            )

            # 2. Convert to WAV in memory
            wav_data = self._pcm_to_wav(audio_pcm)

            # Update status using the service's update method
            if processing_msg:
                await self.behavior._message_service.update_message(
                    processing_msg,
                    description="A analisar a vossa conversa... 👁️‍🗨️"
                )

            # 4. Get LLM response
            llm_result = await self.llm_service.prompt_llm(
                text="Excerpto dos utilizadores que acabaram de falar nos últimos segundos:",
                active_users=active_users,
                audio_data=wav_data
            )

            llm_response = llm_result.get("response")
            transcription = llm_result.get("transcription", "Sem transcrição.")

            if not llm_response:
                print("[AICommentary] LLM returned no response.")
                if processing_msg: await processing_msg.delete()
                self.is_processing = False
                return

            # 5. Play Voice (Ventura)
            try:
                # Play audio using the bot's own member object for logging
                await self.behavior._voice_transformation_service.tts_EL(guild.me, llm_response, lang="ventura")
                
                # Send the final result using the standard function we always use
                await self.behavior.send_message(
                    title="O Ventura ouviu isto:",
                    description=f"_{transcription}_\n\n**Resposta:**\n{llm_response}\n\n**Usuários ouvidos:** {', '.join(active_users)}",
                    color=discord.Color.red(),
                    channel=channel
                )
                
                # Delete the processing message now that we have the final result
                if processing_msg:
                    await processing_msg.delete()
                
                # Re-roll cooldown for the next time
                self._set_random_cooldown()
                
                print(f"[AICommentary] Successfully sent transcription to channel: {channel.name}")
            except Exception as e:
                print(f"[AICommentary] Playback/Display error: {e}")
                if processing_msg: await processing_msg.delete()

        except Exception as e:
            print(f"[AICommentary] Error in auto-trigger: {e}")
        finally:
            self.is_processing = False

    def _get_target_channel(self, guild):
        """Heuristic to find a text channel to send the transcript to."""
        # 1. Try to get the standard bot channel
        bot_channel = self.behavior._message_service.get_bot_channel(guild)
        if bot_channel:
            permissions = bot_channel.permissions_for(guild.me)
            if permissions.send_messages and permissions.embed_links:
                return bot_channel
            
        # 2. Heuristic fallback
        priorities = ['geral', 'chat', 'general', 'brain-rot', 'bot']
        for p in priorities:
            for channel in guild.text_channels:
                if p in channel.name.lower():
                    permissions = channel.permissions_for(guild.me)
                    if permissions.send_messages and permissions.embed_links:
                        return channel
                        
        # 3. Fallback to any channel where we can talk
        for channel in guild.text_channels:
            permissions = channel.permissions_for(guild.me)
            if permissions.send_messages and permissions.embed_links:
                return channel
                
        return None

    def _pcm_to_wav(self, pcm_data: bytes) -> bytes:
        """Convert raw PCM data to mono 16kHz WAV."""
        try:
            mono_data = audioop.tomono(pcm_data, 2, 1, 0)
            resampled_data, _ = audioop.ratecv(mono_data, 2, 1, 48000, 16000, None)
            with io.BytesIO() as wav_io:
                with wave.open(wav_io, 'wb') as wav_file:
                    wav_file.setnchannels(1)
                    wav_file.setsampwidth(2)
                    wav_file.setframerate(16000)
                    wav_file.writeframes(resampled_data)
                return wav_io.getvalue()
        except:
            return pcm_data
