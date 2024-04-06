import os
from Classes.AudioDatabase import AudioDatabase
from Classes.SoundDownloader import SoundDownloader
from dotenv import load_dotenv
db = AudioDatabase(os.path.join(os.path.dirname(__file__), "Data/soundsDB.csv"), "null")
load_dotenv()

while True:
    SoundDownloader(db,os.getenv("CHROMEDRIVER_PATH")).download_sound()