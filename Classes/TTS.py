from gtts import gTTS
import os
import speech_recognition as sr
import audioop

class TTS:
    def __init__(self, behavior, bot, filename="tts.mp3"):
        self.filename = filename
        self.behavior = behavior
        self.bot = bot

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

    def speech_to_text(self, discord_files):
        recognizer = sr.Recognizer()
        filename = r"C:\Users\netco\Desktop\Discordbot\p_17309788_212.wav"

        with sr.AudioFile(filename) as source:
            audio = recognizer.record(source)
        print(audio.sample_rate)

        if os.path.isfile(filename):
            print("audio.sample_rate")
            # Load the file into a recognizer
            print("Google Speech Recognition thinks you said in English: -  " + recognizer.recognize_google(audio))
