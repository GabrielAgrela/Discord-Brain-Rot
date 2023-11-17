import pyttsx3

class TTS:
    def __init__(self,behavior,bot, filename="tts.mp3"):
        self.filename = filename
        self.behavior = behavior
        self.bot = bot
        self.engine = pyttsx3.init()

        # Setting voice to a Portuguese voice
        voices = self.engine.getProperty('voices')
        print(voices)
        for voice in voices:
            print(voice.name)
            if 'portuguese' in voice.name.lower():  # You might need to adjust this condition based on the voice names on your system
                self.engine.setProperty('voice', voice.id)
                break

    async def save_as_mp3(self, text):
        self.engine.save_to_file(text, "H:/bup82623/Downloads/sounds/"+self.filename)
        self.engine.runAndWait()
        for guild in self.bot.guilds:
            channel = self.behavior.get_largest_voice_channel(guild)
        await self.behavior.play_audio(channel, self.filename,"admin",is_tts=True)
