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
from Classes.Database import Database

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
        self.db = behavior.db
        self.last_request_time = 0
        self.cooldown_seconds = cooldown_seconds
        self.locked = False
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

    def is_on_cooldown(self):
        current_time = time.time()
        return current_time - self.last_request_time < self.cooldown_seconds

    def update_last_request_time(self):
        self.last_request_time = time.time()

    async def save_as_mp3(self, text, lang, region=""):
        if region == "":
            tts = gTTS(text=text, lang=lang)
        else:
            tts = gTTS(text=text, lang=lang, tld=region)
        path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Sounds", self.filename))
        tts.save(path)
        # Apply integrated loudness normalization for consistent perceived volume
        self._loudnorm_inplace(path)
        for guild in self.bot.guilds:
            channel = self.behavior.get_largest_voice_channel(guild)
        await self.behavior.play_audio(channel, self.filename, "admin", is_tts=True)
        self.update_last_request_time()

    async def speech_to_speech(self, input_audio_name, char="en", region=""):
        boost_volume = 0
        
        filenames = Database().get_sounds_by_similarity(input_audio_name)
        
        filename = filenames[0][1] if filenames else None

        tmp_filename = f"{filename}-{char}.mp3"
         # Check if the file already exists

        audio_file_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Sounds", filename))

        self.filename = f"{filename}-{char}-{time.strftime('%d-%m-%y-%H-%M-%S')}.mp3"
        
        if char == "ventura":
            self.voice_id = self.voice_id_pt
            boost_volume = 5
        elif char == "costa":
            self.voice_id = self.voice_id_costa
            boost_volume = 5
        elif char == "tyson":
            self.voice_id = self.voice_id_en
            boost_volume = 10

        if self.is_on_cooldown():
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
        
        if self.locked:
            print("Being processed. Please try again later.")
            locked_message = await self.behavior.send_message(view=None, title="Server Locked", description="Please try again later.")
            await asyncio.sleep(5)
            await locked_message.delete()
            return
        
        self.locked = True

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

        form = aiohttp.FormData()
        form.add_field('audio', open(audio_file_path, 'rb'), filename=os.path.basename(audio_file_path))
        form.add_field('data', json.dumps(data), content_type='application/json')

        # send a message to chat, in a new thread to avoid blocking the main thread and then delete it after 5 seconds
        await self.behavior.send_message(view=None, title="Processing", description="Wait like 5s 🦍", delete_time=5)

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, data=form) as response:
                if response.status == 200:
                    audio_data = await response.read()
                    audio = AudioSegment.from_mp3(io.BytesIO(audio_data))
                    final_audio = audio

                    path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Sounds", self.filename))
                    Database().insert_sound(os.path.basename(self.filename), os.path.basename(self.filename))
                    final_audio.export(path, format="mp3")
                    # Integrated loudness normalization (EBU R128)
                    self._loudnorm_inplace(path)

                    for guild in self.bot.guilds:
                        channel = self.behavior.get_largest_voice_channel(guild)
                    await self.behavior.play_audio(channel, self.filename, "admin", is_tts=True)
                    self.update_last_request_time()
                    print("Audio stream saved and played successfully.")
                else:
                    print(f"Error: {await response.text()}")

        self.locked = False

    async def isolate_voice(self, input_audio_name):
        boost_volume = 0
        
        filenames = self.db.get_most_similar_filenames(input_audio_name)
        filename = filenames[0][1] if filenames else None
        audio_file_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Sounds", filename))

        self.filename = f"{filename}-isolated-{time.strftime('%d-%m-%y-%H-%M-%S')}.mp3"

        if self.is_on_cooldown():
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
        
        if self.locked:
            print("Being processed. Please try again later.")
            locked_message = await self.behavior.send_message(view=None, title="Server Locked", description="Please try again later.")
            await asyncio.sleep(5)
            await locked_message.delete()
            return
        
        self.locked = True

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

        form = aiohttp.FormData()
        form.add_field('audio', open(audio_file_path, 'rb'), filename=os.path.basename(audio_file_path))
        form.add_field('data', json.dumps(data), content_type='application/json')

        asyncio.create_task(self.behavior.send_message(view=None, title="Processing", description="Wait like 5s 🦍", delete_time=5))

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, data=form) as response:
                if response.status == 200:
                    audio_data = await response.read()
                    audio = AudioSegment.from_mp3(io.BytesIO(audio_data))
                    louder_audio = audio + boost_volume
                    final_audio = louder_audio

                    path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Sounds", self.filename))
                    self.db.add_entry(os.path.basename(self.filename))

                    final_audio.export(path, format="mp3")
                    # Integrated loudness normalization (EBU R128)
                    self._loudnorm_inplace(path)

                    for guild in self.bot.guilds:
                        channel = self.behavior.get_largest_voice_channel(guild)
                    await self.behavior.play_audio(channel, self.filename, "admin", is_tts=True)
                    self.update_last_request_time()
                    print("Audio stream saved and played successfully.")
                else:
                    print(f"Error: {await response.text()}")

        self.locked = False

    async def save_as_mp3_EL(self, text, lang="pt", region=""):
        boost_volume = 0
        self.filename = f"{time.strftime('%d-%m-%y-%H-%M-%S')}-{text[:10]}.mp3"
        if lang == "pt":
            self.voice_id = self.voice_id_pt
            boost_volume = 0
        elif lang == "costa":
            self.voice_id = self.voice_id_costa
            boost_volume = 0
        elif lang == "en":
            self.voice_id = self.voice_id_en
            boost_volume = 0

        if self.is_on_cooldown():
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
                "speed": 0.65,
                "stability": 0,
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

                    path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Sounds", self.filename))
                    Database().insert_sound(os.path.basename(self.filename), os.path.basename(self.filename))
                    #self.db.add_entry(os.path.basename(self.filename))

                    final_audio.export(path, format="mp3")
                    # Integrated loudness normalization (EBU R128)
                    self._loudnorm_inplace(path)

                    for guild in self.bot.guilds:
                        channel = self.behavior.get_largest_voice_channel(guild)
                    await self.behavior.play_audio(channel, self.filename, "admin", is_tts=True)
                    self.update_last_request_time()
                    print("Audio stream saved and played successfully.")
                else:
                    print(f"Error: {await response.text()}")
