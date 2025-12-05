import os
import threading
import time
from src.common.database import Database
from src.common.config import Config
# from src.scraper.sound_downloader import SoundDownloader # To be implemented/ported

class ScraperService:
    def __init__(self):
        self.db = Database()
        # self.downloader = SoundDownloader(...)

    def run(self):
        while True:
            # self.downloader.download_sound()
            print("Scraper checking for new sounds...")
            time.sleep(60)

if __name__ == "__main__":
    service = ScraperService()
    service.run()
