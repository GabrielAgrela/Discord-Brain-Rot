import asyncio
import os
import time
import requests
from gtts import gTTS
from dotenv import load_dotenv
from pydub import AudioSegment
import io
import json

class TTS:
    def __init__(self, behavior, bot, filename="tts.mp3", cooldown_seconds=10):
        load_dotenv()
        self.api_key = os.getenv('EL_key')
        self.voice_id = os.getenv('EL_voice_id_pt')
        self.voice_id_pt = os.getenv('EL_voice_id_pt')
        self.voice_id_en = os.getenv('EL_voice_id_en')
        self.filename = filename
        self.behavior = behavior
        self.bot = bot
        self.db = behavior.db
        self.last_request_time = 0
        self.cooldown_seconds = cooldown_seconds

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
        for guild in self.bot.guilds:
            channel = self.behavior.get_largest_voice_channel(guild)
        await self.behavior.play_audio(channel, self.filename, "admin", is_tts=True)
        self.update_last_request_time()

    async def speech_to_speech(self, input_audio_name, char="en", region=""):
        boost_volume = 0
        
        filenames = self.db.get_most_similar_filenames(input_audio_name)
        filename = filenames[0][1] if filenames else None
        audio_file_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Sounds", filename))

        self.filename = f"{filename}-{char}-{time.strftime('%d-%m-%y-%H-%M-%S')}.mp3"
        
        if char == "ventura":
            self.voice_id = self.voice_id_pt
        elif char == "tyson":
            self.voice_id = self.voice_id_en
            boost_volume = 15

        if self.is_on_cooldown():
            print("Cooldown active. Please wait before making another request.")
            cooldown_message = await self.behavior.send_message(view=None, title="Cooldown Active", description="Please wait before making another request.")
            # Remove the cooldown message after 5 seconds
            await asyncio.sleep(5)
            await cooldown_message.delete()
            return
        
        #  audio file cannot be longer than 30 seconds
        if AudioSegment.from_file(audio_file_path).duration_seconds > 60:
            print("Audio file is too long. Please provide a file that is less than 15 seconds.")
            error_message = await self.behavior.send_message(view=None, title="Audio File Too Long", description="Please provide a file that is less than 15 seconds.")
            # Remove the error message after 5 seconds
            await asyncio.sleep(5)
            await error_message.delete()
            return

        url = f"https://api.elevenlabs.io/v1/speech-to-speech/{self.voice_id}/stream"
        headers = {
            "Accept": "application/json",
            "xi-api-key": self.api_key
        }
        data = {
            "model_id": "eleven_multilingual_sts_v2",
            "voice_settings": json.dumps({
                "stability": 0.3,
                "similarity_boost": 1,
                "style": 1,
                "use_speaker_boost": True
            })
        }
        files = {
            "audio": open(audio_file_path, "rb")
        }

        response = requests.post(url, headers=headers, data=data, files=files, stream=True)

        if response.ok:
            # Load the audio data into pydub
            audio = AudioSegment.from_mp3(io.BytesIO(response.content))
            
            # Increase volume if needed
            louder_audio = audio + boost_volume

            path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Sounds", self.filename))
            self.db.add_entry(os.path.basename(self.filename))

            # Export the louder audio
            louder_audio.export(path, format="mp3")

            for guild in self.bot.guilds:
                channel = self.behavior.get_largest_voice_channel(guild)
            await self.behavior.play_audio(channel, self.filename, "admin", is_tts=True)
            self.update_last_request_time()
            print("Audio stream saved and played successfully.")
        else:
            print(f"Error: {response.text}")

    async def save_as_mp3_EL(self, text, lang="pt", region=""):
        boost_volume = 0
        #create a unique self.filename based on the text and current time in the format dd-mm-yy-hh-mm-ss
        self.filename = f"{text[:10]}-{time.strftime('%d-%m-%y-%H-%M-%S')}.mp3"
        if lang == "pt":
            self.voice_id = self.voice_id_pt
        elif lang == "en":
            self.voice_id = self.voice_id_en
            boost_volume = 15

        if self.is_on_cooldown():
            print("Cooldown active. Please wait before making another request.")
            cooldown_message = await self.behavior.send_message(view=None, title="Não dês spam nesta merda (1/m)", description="Custa 11 euros por 2h de andre ventura fdp")
            #remove the cooldown message after 5 seconds
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
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": 0.7,
                "similarity_boost": 0.9,
                "style": 0.7,
                "use_speaker_boost": True
            }
        }

        response = requests.post(url, json=data, headers=headers)
    
        # Load the audio data into pydub
        audio = AudioSegment.from_mp3(io.BytesIO(response.content))
        
        # Increase volume by 50% (6 dB)
        louder_audio = audio + boost_volume

        path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Sounds", self.filename))
        self.db.add_entry(os.path.basename(self.filename))

        # Export the louder audio
        louder_audio.export(path, format="mp3")

        for guild in self.bot.guilds:
            channel = self.behavior.get_largest_voice_channel(guild)
        await self.behavior.play_audio(channel, self.filename, "admin", is_tts=True)
        self.update_last_request_time()
