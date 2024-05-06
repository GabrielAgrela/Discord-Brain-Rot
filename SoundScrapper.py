import os
from Classes.AudioDatabase import AudioDatabase
from Classes.SoundDownloader import SoundDownloader
from dotenv import load_dotenv
import threading
import time
db = AudioDatabase(os.path.join(os.path.dirname(__file__), "Data/soundsDB.csv"), "null")
load_dotenv()

sound_downloader_instance = SoundDownloader(db, os.getenv("CHROMEDRIVER_PATH"))

def download_sounds():
    while True:
        #sound_downloader_instance.move_sounds()
        SoundDownloader(db, os.getenv("CHROMEDRIVER_PATH")).download_sound()
        time.sleep(60)

download_thread = threading.Thread(target=download_sounds)
download_thread.start()


#while True:
    #sound_downloader_instance.move_sounds()
    #time.sleep(10)


