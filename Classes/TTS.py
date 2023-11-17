import pyttsx3

class TTS:
    def __init__(self,behavior,bot, filename="tts.mp3"):
        self.filename = filename
        self.behavior = behavior
        self.bot = bot
        self.engine = pyttsx3.init()
        self.engine.setProperty('rate', 120)
        self.engine.setProperty('volume', 2.0)
        
    async def save_as_mp3(self, text):
        self.engine.save_to_file(text, "D:/eu/sounds/"+self.filename)
        self.engine.runAndWait()
        for guild in self.bot.guilds:
            channel = self.behavior.get_largest_voice_channel(guild)
        await self.behavior.play_audio(channel, self.filename,"admin",is_tts=True)

