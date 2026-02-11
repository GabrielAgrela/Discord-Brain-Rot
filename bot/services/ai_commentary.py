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
from bot.database import Database
from config import ENABLE_VENTURA

class AICommentaryService:
    """
    Service to automatically trigger AI commentary based on voice activity.
    """
    def __init__(self, behavior):
        self.behavior = behavior
        self.llm_service = behavior._llm_service
        self.last_trigger_time = 0
        self.min_speech_duration = 2.0
        self.is_processing = False
        self.is_first_trigger = True  # Track if this is the first trigger
        
        # Short cooldown on startup for quick testing/responsiveness
        self.cooldown_seconds = 5
        print(f"[AICommentary] Initial startup cooldown: {self.cooldown_seconds}s")
        
        # Directory for debug audio
        self.debug_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "Debug", "llm_audio"))
        os.makedirs(self.debug_dir, exist_ok=True)
        
        # Track if we've sent the "listening" notification
        self.cooldown_ended_notified = False
        self.listening_msg = None
        
        # Enable/Disable flag
        self.enabled = ENABLE_VENTURA

    def set_enabled(self, enabled: bool):
        """Enable or disable the AI commentary routine."""
        self.enabled = enabled
        status = "enabled" if enabled else "disabled"
        print(f"[AICommentary] Routine {status}. (enabled={self.enabled})")

    def _set_random_cooldown(self):
        """Set a random cooldown between 5 and 15 minutes."""
        self.cooldown_seconds = random.randint(300, 900)
        print(f"[AICommentary] Next sighting scheduled with {self.cooldown_seconds/60:.1f} minute cooldown.")

    def should_trigger(self) -> bool:
        """Check if the cooldown has passed and we aren't already processing."""
        if not self.enabled:
            return False
            
        if self.is_processing:
            return False
        
        time_since_last = time.time() - self.last_trigger_time
        if time_since_last < self.cooldown_seconds:
            return False
        return True
    
    async def notify_listening_if_ready(self, guild_id: int):
        """Send 'Ventura is listening' message when cooldown ends."""
        if not self.enabled:
            return

        if self.cooldown_ended_notified or self.is_processing:
            return
        
        if self.get_cooldown_remaining() > 0:
            return
        
        self.cooldown_ended_notified = True
        
        guild = self.behavior.bot.get_guild(guild_id)
        if not guild:
            return
        
        channel = self._get_target_channel(guild)
        if channel:
            try:
                self.listening_msg = await self.behavior.send_message(
                    title="👂 Ventura está a ouvir...",
                    description="O cooldown terminou. A gravar a conversa...",
                    color=discord.Color.blue(),
                    channel=channel
                )
            except Exception as e:
                print(f"[AICommentary] Error sending listening msg: {e}")

    def get_cooldown_remaining(self) -> float:
        """Return the number of seconds remaining until the next commentary can be triggered."""
        time_since_last = time.time() - self.last_trigger_time
        remaining = self.cooldown_seconds - time_since_last
        return max(0, remaining)

    async def trigger_commentary(self, guild_id: int, force: bool = False, duration: float = 10.0):
        """Orchestrate the AI commentary flow."""
        if not force and not self.should_trigger():
            print(f"[AICommentary] Trigger skipped (enabled={self.enabled}, processing={self.is_processing}, cooldown_remaining={self.get_cooldown_remaining():.1f}s).")
            return
        
        if self.is_processing:
            print(f"[AICommentary] Already processing. Blocked trigger (force={force}).")
            return
            
        self.is_processing = True
        self.last_trigger_time = time.time()
        
        print(f"[AICommentary] Triggering commentary (force={force}, duration={duration:.1f}s)...")
        
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
            print(f"[AICommentary] Step 1: Getting audio segment ({int(duration)}s)...")
            audio_pcm, active_users = self.behavior._audio_service.get_last_audio_segment_with_users(guild_id, seconds=int(duration))
            
            if not audio_pcm or not active_users:
                print(f"[AICommentary] No audio or users found for trigger. (audio={len(audio_pcm) if audio_pcm else 0} bytes, users={active_users})")
                self.is_processing = False
                return

            print(f"[AICommentary] Triggered! Users: {active_users}")

            # Delete the listening message if it exists
            if self.listening_msg:
                try:
                    await self.listening_msg.delete()
                except:
                    pass
                self.listening_msg = None

            # Send "processing" message
            processing_msg = await self.behavior.send_message(
                title="🎧 Ventura a processar...",
                description=f"Ouvi {len(active_users)} pessoas ({', '.join(active_users)}). A preparar o áudio... 🎙️",
                channel=channel
            )

            # 2. Trim first 1s to remove Opus decoder initialization artifacts, then convert to WAV
            # 48kHz stereo 16-bit = 192000 bytes per second
            trim_bytes = 192000
            if len(audio_pcm) > trim_bytes * 2:  # Only trim if we have enough audio
                audio_pcm = audio_pcm[trim_bytes:]
            
            wav_data = self._pcm_to_wav(audio_pcm)

            # Debug: Save the audio file sent to Gemini
            try:
                timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
                debug_filename = f"gemini_audio_{timestamp}.wav"
                debug_path = os.path.join(self.debug_dir, debug_filename)
                with open(debug_path, 'wb') as f:
                    f.write(wav_data)
                print(f"[AICommentary] Debug: Saved audio to {debug_path}")
            except Exception as e:
                print(f"[AICommentary] Debug save failed: {e}")

            # Update status to "analyzing"
            if processing_msg:
                await self.behavior._message_service.update_message(
                    processing_msg,
                    title="🧠 Ventura a analisar...",
                    description="A enviar para o Gemini... 👁️‍🗨️"
                )

            # 4. Get LLM response with memory context
            print(f"[AICommentary] Step 4: Calling LLM with {len(wav_data)} bytes of audio...")
            memories = Database().get_recent_ai_memories(guild_id, limit=3)
            if memories:
                print(f"[AICommentary] Including {len(memories)} past memories in context")
            
            llm_result = await self.llm_service.prompt_llm(
                text="Excerpto dos utilizadores que acabaram de falar nos últimos segundos:",
                active_users=active_users,
                audio_data=wav_data,
                memories=memories
            )
            print(f"[AICommentary] Step 4: LLM response received.")

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
                # Suppress controls here because we send them with the embed below
                await self.behavior._voice_transformation_service.tts_EL(
                    guild.me, 
                    llm_response, 
                    lang="ventura",
                    send_controls=False
                )
                
                # Send the final result with formatted audio tags visible
                await self.behavior.send_message(
                    title="O Ventura ouviu isto:",
                    description=f"_{transcription}_\n\n**Resposta (com tags de áudio):**\n`{llm_response}`\n\n**Usuários ouvidos:** {', '.join(active_users)}",
                    color=discord.Color.red(),
                    channel=channel
                )
                
                # Save memory for next time
                Database().save_ai_memory(guild_id, transcription, llm_response)
                
                # Delete the processing message now that we have the final result
                if processing_msg:
                    await processing_msg.delete()
                
                # After first successful trigger, switch to random cooldown
                if self.is_first_trigger:
                    self.is_first_trigger = False
                    self._set_random_cooldown()
                else:
                    # Re-roll cooldown for subsequent triggers
                    self._set_random_cooldown()
                
                # Reset listening notification for next cooldown cycle
                self.cooldown_ended_notified = False
                
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
            # Average both stereo channels (0.5 left + 0.5 right)
            mono_data = audioop.tomono(pcm_data, 2, 0.5, 0.5)
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
