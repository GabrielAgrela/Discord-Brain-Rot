import os
from Classes.AudioDatabase import AudioDatabase
from Classes.SoundDownloader import SoundDownloader

db = AudioDatabase(os.path.join(os.path.dirname(__file__), "Data/soundsDB.csv"), "null")
while True:
    SoundDownloader(db).download_sound()