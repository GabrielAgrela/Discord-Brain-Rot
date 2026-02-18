import asyncio
import os
import time
import requests
from gtts import gTTS
from dotenv import load_dotenv
from pydub import AudioSegment
import io
import json
import subprocess
import tempfile
import re
import aiohttp
from datetime import datetime
from typing import Optional
from bot.database import Database

class TTS:
    def __init__(self, behavior, bot, filename="tts.mp3", cooldown_seconds=10):
        load_dotenv()
        self.api_key = os.getenv('EL_key')
        self.voice_id = os.getenv('EL_voice_id_pt')
        self.voice_id_pt = os.getenv('EL_voice_id_pt')
        self.voice_id_en = os.getenv('EL_voice_id_en')
        self.voice_id_costa = os.getenv('EL_voice_id_costa')
        self.filename = filename
        self.behavior = behavior
        self.bot = bot
        self.last_request_time = 0
        self.last_request_time_by_guild: dict[int, float] = {}
        self.cooldown_seconds = cooldown_seconds
        self.locked = False
        self.locked_by_guild: dict[int, bool] = {}
        self.loudnorm_mode = (os.getenv("TTS_LOUDNORM_MODE", "off") or "off").strip().lower()
        # Loudness normalization targets (configurable via env if desired)
        try:
            self.lufs_target = float(os.getenv('TTS_LUFS_TARGET', '-16'))  # Integrated LUFS target
        except Exception:
            self.lufs_target = -16.0
        try:
            self.loudnorm_tp = float(os.getenv('TTS_TP_LIMIT', '-1.5'))   # True peak limit dBTP
        except Exception:
            self.loudnorm_tp = -1.5
        try:
            self.loudnorm_lra = float(os.getenv('TTS_LRA_TARGET', '11'))  # Loudness range target
        except Exception:
            self.loudnorm_lra = 11.0

    def _get_default_voice_channel(self, guild_id: Optional[int] = None):
        """Return the preferred voice channel for playback.

        Preference order:
          1. Any channel the bot is already connected to.
          2. The most recently discovered populated channel across guilds
             (matches the legacy behaviour while still allowing us to detect
             when *no* channel is available).
        """
        if guild_id is not None:
            guild = self.bot.get_guild(int(guild_id))
            if guild:
                settings_service = getattr(getattr(self.bot, "behavior", None), "_guild_settings_service", None)
                if settings_service:
                    settings = settings_service.get(guild.id)
                    configured_voice_id = settings.default_voice_channel_id
                    if configured_voice_id:
                        try:
                            configured_channel = guild.get_channel(int(configured_voice_id))
                            if configured_channel is not None:
                                return configured_channel
                        except (TypeError, ValueError):
                            pass
                if guild.voice_client and guild.voice_client.is_connected() and guild.voice_client.channel:
                    return guild.voice_client.channel
                return self.behavior.get_largest_voice_channel(guild)

        for voice_client in getattr(self.bot, "voice_clients", []):
            try:
                if voice_client and voice_client.is_connected() and voice_client.channel:
                    return voice_client.channel
            except Exception:
                continue

        last_channel = None
        for guild in self.bot.guilds:
            channel = self.behavior.get_largest_voice_channel(guild)
            if channel is not None:
                last_channel = channel
        return last_channel

    def _normalize_audio(self, audio: AudioSegment, target_dbfs: float = -20.0) -> AudioSegment:
        """Normalize an AudioSegment to a target dBFS for consistent loudness."""
        try:
            if audio.dBFS == float('-inf'):
                return audio
            change_in_dBFS = target_dbfs - audio.dBFS
            return audio.apply_gain(change_in_dBFS)
        except Exception as e:
            print(f"TTS normalization warning (segment): {e}")
            return audio

    def _normalize_file_inplace(self, file_path: str, target_dbfs: float = -20.0) -> None:
        """Normalize an audio file in-place to the target dBFS."""
        try:
            audio = AudioSegment.from_file(file_path)
            normalized = self._normalize_audio(audio, target_dbfs)
            normalized.export(file_path, format="mp3")
        except Exception as e:
            print(f"TTS normalization warning for {file_path}: {e}")

    def _extract_loudnorm_stats(self, text: str):
        """Extract JSON stats from ffmpeg loudnorm pass-1 output."""
        try:
            start = text.find('{')
            end = text.rfind('}')
            if start != -1 and end != -1 and end > start:
                payload = text[start:end+1]
                data = json.loads(payload)
                return {
                    'input_i': data.get('input_i'),
                    'input_tp': data.get('input_tp'),
                    'input_lra': data.get('input_lra'),
                    'input_thresh': data.get('input_thresh'),
                    'target_offset': data.get('target_offset')
                }
        except Exception as e:
            print(f"TTS loudnorm stats parse failed: {e}")
        return None

    def _loudnorm_inplace(self, file_path: str):
        """Run ffmpeg EBU R128 loudness normalization in-place (two-pass if possible)."""
        try:
            ffmpeg = getattr(self.behavior, 'ffmpeg_path', None) or 'ffmpeg'
            base_dir = os.path.dirname(file_path)
            tmp_out = os.path.join(base_dir, f".{os.path.basename(file_path)}.loudnorm.tmp.mp3")

            # Pass 1: analyze
            cmd1 = [
                ffmpeg, '-hide_banner', '-nostats', '-y',
                '-i', file_path,
                '-af', f"loudnorm=I={self.lufs_target}:TP={self.loudnorm_tp}:LRA={self.loudnorm_lra}:print_format=json",
                '-f', 'null', '-'
            ]
            p1 = subprocess.run(cmd1, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stats = self._extract_loudnorm_stats(p1.stderr.decode('utf-8', errors='ignore'))

            if stats and all(stats.get(k) is not None for k in ['input_i','input_tp','input_lra','input_thresh','target_offset']):
                # Pass 2: apply with measured values
                filter2 = (
                    f"loudnorm=I={self.lufs_target}:TP={self.loudnorm_tp}:LRA={self.loudnorm_lra}:"
                    f"measured_I={stats['input_i']}:measured_TP={stats['input_tp']}:"
                    f"measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}:"
                    f"offset={stats['target_offset']}:linear=true:print_format=summary"
                )
                cmd2 = [
                    ffmpeg, '-hide_banner', '-nostats', '-y',
                    '-i', file_path,
                    '-af', filter2,
                    '-ar', '44100', '-b:a', '128k',
                    tmp_out
                ]
            else:
                # Fallback: single-pass loudnorm
                cmd2 = [
                    ffmpeg, '-hide_banner', '-nostats', '-y',
                    '-i', file_path,
                    '-af', f"loudnorm=I={self.lufs_target}:TP={self.loudnorm_tp}:LRA={self.loudnorm_lra}",
                    '-ar', '44100', '-b:a', '128k',
                    tmp_out
                ]

            p2 = subprocess.run(cmd2, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if p2.returncode == 0 and os.path.exists(tmp_out):
                os.replace(tmp_out, file_path)
            else:
                # Leave original file untouched on failure
                if os.path.exists(tmp_out):
                    try:
                        os.remove(tmp_out)
                    except Exception:
                        pass
                print(f"TTS loudnorm warning: normalization failed for {file_path}; falling back to RMS dBFS normalization")
                try:
                    self._normalize_file_inplace(file_path, -20.0)
                except Exception:
                    pass
        except Exception as e:
            print(f"TTS loudnorm error: {e}")

    def is_on_cooldown(self, guild_id: Optional[int] = None):
        current_time = time.time()
        if guild_id is None:
            return current_time - self.last_request_time < self.cooldown_seconds
        last_request = self.last_request_time_by_guild.get(int(guild_id), 0)
        return current_time - last_request < self.cooldown_seconds

    def update_last_request_time(self, guild_id: Optional[int] = None):
        now = time.time()
        self.last_request_time = now
        if guild_id is not None:
            self.last_request_time_by_guild[int(guild_id)] = now

    def _is_locked(self, guild_id: Optional[int] = None) -> bool:
        """Check lock for guild-scoped TTS processing."""
        if guild_id is None:
            return self.locked
        return self.locked_by_guild.get(int(guild_id), False)

    def _set_locked(self, value: bool, guild_id: Optional[int] = None) -> None:
        """Set lock for guild-scoped TTS processing."""
        if guild_id is None:
            self.locked = value
            return
        self.locked_by_guild[int(guild_id)] = value

    def _apply_loudnorm_if_enabled(self, file_path: str):
        """Apply configurable loudness normalization."""
        if self.loudnorm_mode == "off":
            return
        if self.loudnorm_mode == "single":
            self._normalize_file_inplace(file_path, -20.0)
            return
        self._loudnorm_inplace(file_path)

    def _timestamp_token(self) -> str:
        """Generate a high-resolution timestamp token for unique filenames."""
        return datetime.now().strftime('%d-%m-%y-%H-%M-%S-%f')

    async def save_as_mp3(
        self,
        text,
        lang,
        region="",
        loading_message=None,
        requester_avatar_url=None,
        requester_name="admin",
        guild_id: Optional[int] = None,
    ):
        if region == "":
            tts = gTTS(text=text, lang=lang)
        else:
            tts = gTTS(text=text, lang=lang, tld=region)
            
        # Sanitize filename-safe text (keep it reasonably short for FS)
        safe_text = "".join(x for x in text[:30] if x.isalnum() or x in " -_")
        filename = f"tts-{self._timestamp_token()}-{safe_text}.mp3"
        self.filename = filename
        
        path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Sounds", filename))
        tts.save(path)
        # Apply configurable loudness normalization for consistent perceived volume
        self._apply_loudnorm_if_enabled(path)
        channel = self._get_default_voice_channel(guild_id=guild_id)
        if channel is None:
            await self.behavior.send_error_message("No available voice channel for TTS playback.")
            return
            
        # Record in database so it can be replayed or processed
        Database().insert_sound(
            os.path.basename(filename),
            os.path.basename(filename),
            is_elevenlabs=0,
            guild_id=guild_id,
        )
        
        await self.behavior.play_audio(
            channel, filename, requester_name, is_tts=True,
            original_message=text,
            loading_message=loading_message,
            requester_avatar_url=requester_avatar_url
        )
        self.update_last_request_time(guild_id=guild_id)

    async def speech_to_speech(self, input_audio_name, char="en", region="",
                               loading_message=None, requester_avatar_url=None, sts_thumbnail_url=None,
                               requester_name="admin", guild_id: Optional[int] = None):
        boost_volume = 0
        
        filenames = Database().get_sounds_by_similarity(input_audio_name, guild_id=guild_id)
        
        # get_sounds_by_similarity returns [(sound_data, score), ...]
        # sound_data is a sqlite3.Row or dict; use 'Filename' key
        if filenames:
            sound_data = filenames[0][0]
            sound_dict = sound_data if isinstance(sound_data, dict) else dict(sound_data)
            filename = sound_dict.get('Filename')
        else:
            filename = None

        if not filename:
            await self.behavior.send_error_message("No matching source sound found for speech-to-speech.")
            return

        audio_file_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Sounds", filename))
        source_stem = os.path.splitext(os.path.basename(filename))[0]
        output_filename = f"{source_stem}-{char}-{self._timestamp_token()}.mp3"
        self.filename = output_filename
        
        if char == "ventura":
            self.voice_id = self.voice_id_pt
            boost_volume = 5
        elif char == "costa":
            self.voice_id = self.voice_id_costa
            boost_volume = 5
        elif char == "tyson":
            self.voice_id = self.voice_id_en
            boost_volume = 10

        if self.is_on_cooldown(guild_id=guild_id):
            print("Cooldown active. Please wait before making another request.")
            cooldown_message = await self.behavior.send_message(view=None, title="Cooldown Active", description="Please wait before making another request.")
            await asyncio.sleep(5)
            await cooldown_message.delete()
            return
        
        if AudioSegment.from_file(audio_file_path).duration_seconds > 70:
            print("Audio file is too long. Please provide a file that is less than 70 seconds.")
            error_message = await self.behavior.send_message(view=None, title="Audio File Too Long", description="Please provide a file that is less than 70 seconds.")
            await asyncio.sleep(5)
            await error_message.delete()
            return
        
        if self._is_locked(guild_id=guild_id):
            print("Being processed. Please try again later.")
            locked_message = await self.behavior.send_message(view=None, title="Server Locked", description="Please try again later.")
            await asyncio.sleep(5)
            await locked_message.delete()
            return
        
        self._set_locked(True, guild_id=guild_id)
        try:
            url = f"https://api.elevenlabs.io/v1/speech-to-speech/{self.voice_id}/stream"
            headers = {
                "Accept": "application/json",
                "xi-api-key": self.api_key
            }
            data = {
                "model_id": "eleven_v3",
                # remove_background_noise leverages ElevenLabs' isolation model to
                # strip background noise from the input audio. According to the
                # official API specification this boolean enables vocal isolation
                # during the speech-to-speech request.
                "voice_settings": json.dumps({
                    "stability": 0.5,
                    "similarity_boost": 0.9,
                    "style": 1,
                    "use_speaker_boost": True
                })
            }

            async with aiohttp.ClientSession() as session:
                with open(audio_file_path, 'rb') as source_audio:
                    form = aiohttp.FormData()
                    form.add_field('audio', source_audio, filename=os.path.basename(audio_file_path))
                    form.add_field('data', json.dumps(data), content_type='application/json')

                    async with session.post(url, headers=headers, data=form) as response:
                        if response.status == 200:
                            audio_data = await response.read()
                            audio = AudioSegment.from_mp3(io.BytesIO(audio_data))
                            final_audio = audio

                            path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Sounds", output_filename))
                            Database().insert_sound(
                                os.path.basename(output_filename),
                                os.path.basename(output_filename),
                                is_elevenlabs=1,
                                guild_id=guild_id,
                            )
                            final_audio.export(path, format="mp3")
                            # Configurable loudness normalization
                            self._apply_loudnorm_if_enabled(path)

                            channel = self._get_default_voice_channel(guild_id=guild_id)
                            if channel is None:
                                await self.behavior.send_error_message("No available voice channel for TTS playback.")
                                return
                            # Pass character and original sound name for proper STS embed
                            original_sound_name = source_stem
                            await self.behavior.play_audio(
                                channel, output_filename, requester_name, is_tts=True,
                                original_message=original_sound_name, sts_char=char,
                                loading_message=loading_message,
                                requester_avatar_url=requester_avatar_url,
                                sts_thumbnail_url=sts_thumbnail_url
                            )

                            self.update_last_request_time(guild_id=guild_id)
                            print("Audio stream saved and played successfully.")
                        else:
                            print(f"Error: {await response.text()}")
        finally:
            self._set_locked(False, guild_id=guild_id)

    async def isolate_voice(self, input_audio_name, guild_id: Optional[int] = None):
        boost_volume = 0
        
        filenames = Database().get_sounds_by_similarity(input_audio_name, guild_id=guild_id)
        if filenames:
            sound_data = filenames[0][0]
            sound_dict = sound_data if isinstance(sound_data, dict) else dict(sound_data)
            filename = sound_dict.get('Filename')
        else:
            filename = None

        if not filename:
            await self.behavior.send_error_message("No matching source sound found for isolation.")
            return

        audio_file_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Sounds", filename))
        source_stem = os.path.splitext(os.path.basename(filename))[0]
        output_filename = f"{source_stem}-isolated-{self._timestamp_token()}.mp3"
        self.filename = output_filename

        if self.is_on_cooldown(guild_id=guild_id):
            print("Cooldown active. Please wait before making another request.")
            cooldown_message = await self.behavior.send_message(view=None, title="Cooldown Active", description="Please wait before making another request.")
            await asyncio.sleep(5)
            await cooldown_message.delete()
            return
        
        if AudioSegment.from_file(audio_file_path).duration_seconds > 60:
            print("Audio file is too long. Please provide a file that is less than 15 seconds.")
            error_message = await self.behavior.send_message(view=None, title="Audio File Too Long", description="Please provide a file that is less than 15 seconds.")
            await asyncio.sleep(5)
            await error_message.delete()
            return
        
        if self._is_locked(guild_id=guild_id):
            print("Being processed. Please try again later.")
            locked_message = await self.behavior.send_message(view=None, title="Server Locked", description="Please try again later.")
            await asyncio.sleep(5)
            await locked_message.delete()
            return
        
        self._set_locked(True, guild_id=guild_id)
        try:
            url = "https://api.elevenlabs.io/v1/audio-isolation"
            headers = {
                "Accept": "audio/mpeg",
                "xi-api-key": self.api_key
            }
            data = {
                "model_id": "eleven_v3",
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.9,
                    "style": 1,
                    "use_speaker_boost": True
                }
            }

            asyncio.create_task(self.behavior.send_message(view=None, title="Processing", description="Wait like 5s 🦍", delete_time=5))

            async with aiohttp.ClientSession() as session:
                with open(audio_file_path, 'rb') as source_audio:
                    form = aiohttp.FormData()
                    form.add_field('audio', source_audio, filename=os.path.basename(audio_file_path))
                    form.add_field('data', json.dumps(data), content_type='application/json')

                    async with session.post(url, headers=headers, data=form) as response:
                        if response.status == 200:
                            audio_data = await response.read()
                            audio = AudioSegment.from_mp3(io.BytesIO(audio_data))
                            louder_audio = audio + boost_volume
                            final_audio = louder_audio

                            path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Sounds", output_filename))
                            Database().insert_sound(
                                os.path.basename(output_filename),
                                os.path.basename(output_filename),
                                is_elevenlabs=1,
                                guild_id=guild_id,
                            )

                            final_audio.export(path, format="mp3")
                            # Configurable loudness normalization
                            self._apply_loudnorm_if_enabled(path)

                            channel = self._get_default_voice_channel(guild_id=guild_id)
                            if channel is None:
                                await self.behavior.send_error_message("No available voice channel for TTS playback.")
                                return
                            await self.behavior.play_audio(channel, output_filename, "admin", is_tts=True)
                            self.update_last_request_time(guild_id=guild_id)
                            print("Audio stream saved and played successfully.")
                        else:
                            print(f"Error: {await response.text()}")
        finally:
            self._set_locked(False, guild_id=guild_id)

    async def save_as_mp3_EL(self, text, lang="pt", region="", send_controls=True,
                             loading_message=None, requester_avatar_url=None, sts_thumbnail_url=None,
                             requester_name="admin", guild_id: Optional[int] = None):
        boost_volume = 0
        # Sanitize filename-safe text (keep it reasonably short for FS, but image gen will use full text)
        safe_text = "".join(x for x in text[:30] if x.isalnum() or x in " -_")
        filename = f"{self._timestamp_token()}-{safe_text}.mp3"
        self.filename = filename
        if lang == "pt":
            self.voice_id = self.voice_id_pt
            boost_volume = 0
        elif lang == "costa":
            self.voice_id = self.voice_id_costa
            boost_volume = 0
        elif lang == "en":
            self.voice_id = self.voice_id_en
            boost_volume = 0

        if self.is_on_cooldown(guild_id=guild_id):
            print("Cooldown active. Please wait before making another request.")
            cooldown_message = await self.behavior.send_message(view=None, title="Não dês spam nesta merda (1/m)", description="Custa 11 euros por 2h de andre ventura fdp")
            await asyncio.sleep(5)
            await cooldown_message.delete()
            return

        text = text[:1000]
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}"
        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": self.api_key
        }
        data = {
            "text": text,
            "model_id": "eleven_v3",
            "output_format": "mp3_44100_128",
            "voice_settings": {
                "speed": 1,
                "stability": 0.0,
                "similarity_boost": 1.0,
                "style":1,
                "use_speaker_boost": True
            },
            "use_enhanced": True
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=data, headers=headers) as response:
                if response.status == 200:
                    audio_data = await response.read()
                    audio = AudioSegment.from_mp3(io.BytesIO(audio_data))
                    louder_audio = audio + boost_volume
                    final_audio = louder_audio

                    path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Sounds", filename))
                    Database().insert_sound(
                        os.path.basename(filename),
                        os.path.basename(filename),
                        is_elevenlabs=1,
                        guild_id=guild_id,
                    )
                    #self.db.add_entry(os.path.basename(self.filename))

                    final_audio.export(path, format="mp3")
                    # Configurable loudness normalization
                    self._apply_loudnorm_if_enabled(path)

                    channel = self._get_default_voice_channel(guild_id=guild_id)
                    if channel is None:
                        await self.behavior.send_error_message("No available voice channel for TTS playback.")
                        return
                    await self.behavior.play_audio(
                        channel, filename, requester_name, is_tts=True,
                        original_message=text,
                        send_controls=send_controls,
                        loading_message=loading_message,
                        requester_avatar_url=requester_avatar_url,
                        sts_thumbnail_url=sts_thumbnail_url
                    )
                    self.update_last_request_time(guild_id=guild_id)
                    print("Audio stream saved and played successfully.")
                else:
                    error_msg = f"ElevenLabs API Error: {await response.text()}"
                    print(error_msg)
                    raise Exception(error_msg)
