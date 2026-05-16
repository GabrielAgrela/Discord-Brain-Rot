import asyncio
import logging
import os
import time
import requests
import urllib.parse
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

logger = logging.getLogger(__name__)

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

        # --- ElevenLabs TTS optimization knobs ---
        self.el_tts_streaming_enabled = os.getenv("EL_TTS_STREAMING_ENABLED", "true").strip().lower() in ("true", "1", "yes")
        self.el_tts_live_playback_enabled = os.getenv("EL_TTS_LIVE_PLAYBACK_ENABLED", "true").strip().lower() in ("true", "1", "yes")
        raw_latency = os.getenv("EL_TTS_OPTIMIZE_STREAMING_LATENCY", "3")
        self.el_tts_optimize_streaming_latency = self._parse_optimize_latency(raw_latency)
        self.el_tts_model_id = os.getenv("EL_TTS_MODEL_ID", "eleven_v3")
        self.el_tts_output_format = os.getenv("EL_TTS_OUTPUT_FORMAT", "mp3_44100_128")
        try:
            self.el_tts_timeout_seconds = int(os.getenv("EL_TTS_TIMEOUT_SECONDS", "30"))
        except Exception:
            self.el_tts_timeout_seconds = 30

    @staticmethod
    def _parse_optimize_latency(raw: Optional[str]) -> Optional[int]:
        """Parse and validate the optimize_streaming_latency env value.

        Returns ``None`` if the value is empty/blank/invalid, otherwise clamps
        to the valid range 0-4 and logs a warning if clamping was needed.
        """
        if not raw or not raw.strip():
            return None
        try:
            val = int(raw.strip())
        except (ValueError, TypeError):
            logger.warning(
                "Ignoring invalid EL_TTS_OPTIMIZE_STREAMING_LATENCY=%r; "
                "must be an integer 0-4 or empty. Falling back to None.",
                raw,
            )
            return None
        if val < 0 or val > 4:
            logger.warning(
                "Clamping EL_TTS_OPTIMIZE_STREAMING_LATENCY=%d to valid "
                "range 0-4. Using effective value None.",
                val,
            )
            return None
        return val

    def _effective_el_tts_streaming_latency(self) -> Optional[int]:
        """Return the latency param to send.

        The ``eleven_v3`` model does **not** support
        ``optimize_streaming_latency`` and returns a 400 error if it receives
        the parameter.  Returns ``None`` for ``eleven_v3`` (case-insensitive)
        and the configured value otherwise.
        """
        model = (self.el_tts_model_id or "").strip().lower()
        if model == "eleven_v3":
            return None
        return self.el_tts_optimize_streaming_latency

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
                               requester_name="admin", guild_id: Optional[int] = None,
                               allow_tts_interrupt: bool = False):
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
                                sts_thumbnail_url=sts_thumbnail_url,
                                allow_tts_interrupt=allow_tts_interrupt,
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

    def _build_el_tts_url(self) -> str:
        """Build the ElevenLabs TTS endpoint URL based on streaming configuration.

        Returns:
            Full URL string for the ElevenLabs TTS API.
        """
        base = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}"
        if self.el_tts_streaming_enabled:
            base += "/stream"
        params = {}
        # output_format can be passed as query parameter to both streaming and
        # non-streaming endpoints. The streaming endpoint also accepts an
        # optional optimize_streaming_latency parameter (0-4, default 0).
        params["output_format"] = self.el_tts_output_format
        effective_latency = self._effective_el_tts_streaming_latency()
        if effective_latency is not None:
            params["optimize_streaming_latency"] = str(effective_latency)
        return f"{base}?{urllib.parse.urlencode(params)}"

    def _log_el_tts_perf(self, start: float, first_chunk_time: Optional[float],
                         write_end: float, url: str, model_id: str,
                         output_format: str, latency: Optional[int],
                         text_len: int, file_size: Optional[int]):
        """Log ElevenLabs TTS performance metrics at INFO level."""
        total_s = write_end - start
        if first_chunk_time is not None:
            ttf_first_s = first_chunk_time - start
            write_s = write_end - first_chunk_time
            logger.info(
                "EL_TTS perf | model=%s fmt=%s latency=%s text_len=%d "
                "ttf_first=%.3fs write=%.3fs total=%.3fs file_size=%s",
                model_id, output_format, latency, text_len,
                ttf_first_s, write_s, total_s,
                file_size if file_size is not None else "?"
            )
        else:
            logger.info(
                "EL_TTS perf | model=%s fmt=%s latency=%s text_len=%d "
                "total=%.3fs file_size=%s",
                model_id, output_format, latency, text_len,
                total_s, file_size if file_size is not None else "?"
            )

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
            cooldown_message = await self.behavior.send_message(view=None, title="Cooldown Active", description="Please wait before making another request.")
            await asyncio.sleep(5)
            await cooldown_message.delete()
            return

        # Resolve channel early for live-stream eligibility check
        live_channel = None
        if self.el_tts_live_playback_enabled:
            live_channel = self._get_default_voice_channel(guild_id=guild_id)

        text = text[:1000]
        url = self._build_el_tts_url()
        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": self.api_key
        }
        model_id = self.el_tts_model_id
        data = {
            "text": text,
            "model_id": model_id,
            "voice_settings": {
                "speed": 1,
                "stability": 0.0,
                "similarity_boost": 1.0,
                "style": 1,
                "use_speaker_boost": True
            },
            "use_enhanced": True
        }

        perf_start = time.time()
        path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Sounds", filename))
        timeout = aiohttp.ClientTimeout(total=self.el_tts_timeout_seconds)
        first_chunk_time: Optional[float] = None
        http_status = None

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=data, headers=headers) as response:
                http_status = response.status
                if response.status == 200:
                    # ---- Track whether live streaming was started ----
                    live_playback_started = False

                    # ---- Determine whether live-streaming can be used ----
                    should_live = (
                        self.el_tts_live_playback_enabled
                        and self.el_tts_streaming_enabled
                        and boost_volume == 0
                        and self.loudnorm_mode == "off"
                        and live_channel is not None
                    )

                    if boost_volume == 0 and not self.el_tts_streaming_enabled:
                        # Non-streaming, no boost: read all, write directly (skip pydub decode/re-encode)
                        audio_data = await response.read()
                        first_chunk_time = time.time()  # response fully received
                        os.makedirs(os.path.dirname(path), exist_ok=True)
                        with open(path, "wb") as f:
                            f.write(audio_data)
                        file_size = os.path.getsize(path)
                    elif boost_volume == 0 and self.el_tts_streaming_enabled:
                        # Streaming, no boost: write chunks directly to file,
                        # optionally live-stream to a FIFO for concurrent playback.
                        os.makedirs(os.path.dirname(path), exist_ok=True)

                        # --- Live streaming setup (FIFO) ---
                        fifo_path: Optional[str] = None
                        live_fifo_fd: Optional[int] = None
                        live_ready_event: Optional[asyncio.Event] = None

                        if should_live:
                            try:
                                fifo_dir = tempfile.mkdtemp(prefix="el_tts_live_")
                                fifo_path = os.path.join(fifo_dir, "stream.mp3")
                                os.mkfifo(fifo_path)

                                live_ready_event = asyncio.Event()
                                live_task = asyncio.create_task(
                                    self.behavior.play_tts_live_stream(
                                        fifo_path=fifo_path,
                                        audio_file=filename,
                                        channel=live_channel,
                                        user=requester_name,
                                        original_message=text,
                                        send_controls=send_controls,
                                        loading_message=loading_message,
                                        requester_avatar_url=requester_avatar_url,
                                        sts_thumbnail_url=sts_thumbnail_url,
                                        ready_event=live_ready_event,
                                    )
                                )

                                # Wait for FFmpeg to open the FIFO read end
                                # (i.e. voice_client.play was called).  Use a
                                # generous timeout for voice connection.
                                try:
                                    await asyncio.wait_for(
                                        live_ready_event.wait(), timeout=15.0
                                    )
                                except asyncio.TimeoutError:
                                    logger.warning(
                                        "EL_TTS live playback setup timed out"
                                    )
                                    live_task.cancel()
                                    try:
                                        await live_task
                                    except Exception:
                                        pass
                                    raise RuntimeError("live timeout")

                                # Check the task result — play_tts_live_stream
                                # may have returned False.
                                if live_task.done() and not live_task.result():
                                    logger.warning(
                                        "EL_TTS live playback returned False"
                                    )
                                    raise RuntimeError("live failed")

                                # Open the FIFO write end with O_RDWR so the
                                # open never blocks (Linux FIFO semantics).
                                live_fifo_fd = os.open(
                                    fifo_path, os.O_RDWR
                                )
                                # Bump pipe buffer to ~256 KB so short
                                # connection races do not stall the event loop.
                                try:
                                    import fcntl
                                    fcntl.fcntl(
                                        live_fifo_fd, 1031, 262144
                                    )  # F_SETPIPE_SZ
                                except (ImportError, OSError):
                                    pass
                                live_playback_started = True
                                logger.info(
                                    "EL_TTS live playback ready fifo=%s",
                                    fifo_path,
                                )
                            except Exception as e:
                                logger.warning(
                                    "EL_TTS live setup failed, falling back "
                                    "to save-then-play: %s", e,
                                )
                                # Cancel live task if still running
                                try:
                                    live_task.cancel()
                                    await live_task
                                except Exception:
                                    pass
                                # Cleanup FIFO resources
                                if live_fifo_fd is not None:
                                    try:
                                        os.close(live_fifo_fd)
                                    except Exception:
                                        pass
                                    live_fifo_fd = None
                                if fifo_path is not None:
                                    try:
                                        os.unlink(fifo_path)
                                        os.rmdir(
                                            os.path.dirname(fifo_path)
                                        )
                                    except Exception:
                                        pass
                                fifo_path = None
                                live_playback_started = False

                        # --- Chunk loop: write to file (+ FIFO if live) ---
                        with open(path, "wb") as f:
                            async for chunk in response.content.iter_chunked(
                                8192
                            ):
                                if first_chunk_time is None:
                                    first_chunk_time = time.time()
                                f.write(chunk)
                                # Feed the FIFO writer (non-blocking: O_RDWR
                                # open + pipe buffer)
                                if live_fifo_fd is not None:
                                    try:
                                        os.write(live_fifo_fd, chunk)
                                    except (BrokenPipeError, OSError) as e:
                                        logger.debug(
                                            "EL_TTS FIFO write error, "
                                            "disabling live: %s", e,
                                        )
                                        try:
                                            os.close(live_fifo_fd)
                                        except Exception:
                                            pass
                                        live_fifo_fd = None

                        # --- Close FIFO write end ---
                        if live_fifo_fd is not None:
                            try:
                                os.close(live_fifo_fd)
                            except Exception:
                                pass
                            live_fifo_fd = None

                        # --- Cleanup FIFO file ---
                        if fifo_path is not None:
                            try:
                                os.unlink(fifo_path)
                                os.rmdir(os.path.dirname(fifo_path))
                            except Exception as e:
                                logger.debug(
                                    "EL_TTS FIFO cleanup: %s", e,
                                )

                        file_size = os.path.getsize(path)
                    else:
                        # Boost is non-zero: use pydub path (decode, apply gain, re-encode)
                        audio_data = await response.read()
                        first_chunk_time = time.time()
                        audio = AudioSegment.from_mp3(io.BytesIO(audio_data))
                        louder_audio = audio + boost_volume
                        final_audio = louder_audio
                        os.makedirs(os.path.dirname(path), exist_ok=True)
                        final_audio.export(path, format="mp3")
                        file_size = os.path.getsize(path)

                    # Configurable loudness normalization
                    self._apply_loudnorm_if_enabled(path)

                    # Insert DB row only after successful file write
                    Database().insert_sound(
                        os.path.basename(filename),
                        os.path.basename(filename),
                        is_elevenlabs=1,
                        guild_id=guild_id,
                    )

                    perf_end = time.time()
                    self._log_el_tts_perf(
                        perf_start, first_chunk_time, perf_end,
                        url, model_id, self.el_tts_output_format,
                        self._effective_el_tts_streaming_latency(),
                        len(text), file_size,
                    )

                    # Playback: if live-stream was started, it is already
                    # playing.  Otherwise fall back to save-then-play.
                    if not live_playback_started:
                        channel = self._get_default_voice_channel(guild_id=guild_id)
                        if channel is None:
                            await self.behavior.send_error_message(
                                "No available voice channel for TTS playback."
                            )
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
                    logger.info(
                        "Audio stream saved and played successfully. "
                        "path=%s size=%s live=%s",
                        path, file_size, live_playback_started,
                    )
                else:
                    error_body = await response.text()
                    error_msg = f"ElevenLabs API Error: status={http_status} body={error_body}"
                    logger.error(error_msg)
                    raise Exception(error_msg)
