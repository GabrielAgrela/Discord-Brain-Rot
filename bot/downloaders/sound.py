"""
Sound downloader using Selenium.

This module provides functionality to scrape sounds from MyInstants
and automatically add them to the database.
"""

import asyncio
import glob
import os
import random
import shutil
import time

import requests
from pydub import AudioSegment
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from unidecode import unidecode
from webdriver_manager.chrome import ChromeDriverManager


class SoundDownloader:
    """
    Utility class for scraping sounds from MyInstants.
    
    Uses Selenium to browse MyInstants and download sound files,
    then processes and moves them to the Sounds directory.
    """
    
    def __init__(self, bot, db, chromedriver_path: str = ""):
        """
        Initialize the sound downloader.
        
        Args:
            bot: Bot behavior instance for sending messages.
            db: Database instance for storing sound info.
            chromedriver_path: Path to ChromeDriver executable.
        """
        self.db = db
        self.bot = bot
        chromedriver_path = os.getenv("CHROMEDRIVER_PATH")
        if not chromedriver_path:
            chromedriver_path = ChromeDriverManager().install()
        self.service = Service(executable_path=chromedriver_path)
        self.options = webdriver.ChromeOptions()
        self.options.add_argument('--log-level=3')
        self.dwdir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "Downloads"))
        self.options.add_experimental_option("prefs", {
            "download.default_directory": self.dwdir,
            "download.prompt_for_download": False,
        })
        self.options.add_argument('--headless')
        self.options.add_argument('window-size=1200x600')

    def download_sound(self) -> None:
        """
        Scrape and download sounds from MyInstants.
        
        Browses random pages on MyInstants and downloads any sounds
        that aren't already in the database.
        """
        # Import here to avoid circular imports
        from bot.database import Database
        
        try:
            print(self.__class__.__name__, ": Opening Chrome")
            self.driver = webdriver.Chrome(service=self.service, options=self.options)
            base_url = "https://www.myinstants.com/en/"
            categories = random.choice(["index"])
            country = random.choice(["pt", "us", "br"])
            self.driver.get(base_url + categories + "/" + country + "/")
            print(self.__class__.__name__, ": Opening ", base_url + categories + "/" + country + "/")
            wait = WebDriverWait(self.driver, 0)
            try:
                consent_button = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, '/html/body/div[3]/div[2]/div[1]/div[2]/div[2]/button[1]/p')
                ))
                print(self.__class__.__name__, ": Clicking consent button")
                consent_button.click()
            except Exception:
                print(self.__class__.__name__, ": No consent button found")
            
            print(self.__class__.__name__, ": Scrolling down to get more sounds")
            self.scroll_a_little(self.driver)
            
            # Get all divs with class instant
            sound_elements = self.driver.find_elements(By.CSS_SELECTOR, 'div.instant')
            print(self.__class__.__name__, ": Found ", len(sound_elements), " sounds")
            
            new_sounds_detected = 0
            new_sounds_downloaded = 0
            new_sounds_invalid = 0
            
            for i in range(0, len(sound_elements)):
                button = sound_elements[i].find_element(By.CSS_SELECTOR, 'button.small-button')
                onclick_attr = button.get_attribute('onclick')
                filename = onclick_attr.split("'")[1].split('/')[-1]
                
                # Clean up filename
                filename = filename.replace("~", "")
                filename = filename.replace("#", "")
                filename = filename.replace("--", "-")
                filename = filename.replace("--", "-")
                filename = filename.replace("...", ".")
                filename = filename.replace("..", ".")
                filename = filename.replace(".mp3.mp3", ".mp3")
                filename = filename.replace('"', '')
                url = "https://www.myinstants.com/media/sounds/" + filename

                if not Database().get_sound(filename, original_filename=True):
                    new_sounds_detected += 1
                    response = requests.get(url)
                    if response.status_code == 404:
                        new_sounds_invalid += 1
                        print(f"File {filename} not found, skipping download.")
                    else:
                        new_sounds_downloaded += 1
                        out_file_path = os.path.join(self.dwdir, filename)
                        with open(out_file_path, 'wb') as out_file:
                            out_file.write(response.content)
                            
        except Exception as e:
            print(self.__class__.__name__, ": Error downloading sound: ", e)
            self.driver.quit()
            
        try:
            print(
                self.__class__.__name__, 
                f": Sound Downloader finished. {new_sounds_detected} new sounds detected, "
                f"{new_sounds_downloaded} sounds added, {new_sounds_invalid} sounds invalid (wrong url)"
            )
            print("\n-----------------------------------\n")
        except Exception as e:
            print(self.__class__.__name__, ": Error printing sound downloader finished: ", e)

        self.driver.quit()

    async def move_sounds(self) -> None:
        """
        Monitor Downloads directory and move new sounds to Sounds directory.
        
        Runs as a background task, checking every 10 seconds for new MP3 files,
        normalizing their volume, and adding them to the database.
        """
        # Import here to avoid circular imports
        from bot.database import Database
        from bot.ui import DownloadedSoundView
        
        while True:
            downloads_path = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "..", "Downloads", "*.mp3")
            )
            list_of_files = glob.glob(downloads_path)
            
            for file in list_of_files:
                try:
                    print(self.__class__.__name__, " MOVER: ", file, " chosen")
                    print(self.__class__.__name__, " MOVER: Adjusting sound volume")
                    self.adjust_volume(file, -20.0)
                    destination_folder = os.path.abspath(
                        os.path.join(os.path.dirname(__file__), "..", "..", "Sounds")
                    )
                    
                    if not self.db.get_sound(os.path.basename(file), original_filename=True):
                        print(self.__class__.__name__, " MOVER: Moving file to " + destination_folder)
                        sound_view = DownloadedSoundView(self.bot, os.path.basename(file))
                        await self.bot.send_message(
                            title=f"I stole {os.path.basename(file)} to our database hehe",
                            view=sound_view
                        )
                        shutil.move(file, os.path.join(destination_folder, os.path.basename(file)))
                        self.db.insert_sound(os.path.basename(file), os.path.basename(file))
                        self.db.insert_action("admin", "scrape_sound", os.path.basename(file))
                    else:
                        print(self.__class__.__name__, " MOVER: Sound already exists ", os.path.basename(file))
                        print(self.__class__.__name__, " MOVER: Removing file")
                        os.remove(file)
                except Exception as e:
                    print(self.__class__.__name__, " MOVER: Error moving sound: ", e)
                    os.remove(file)
                    
            await asyncio.sleep(10)

    def scroll_a_little(self, driver) -> None:
        """
        Scroll the page to load more content.
        
        Args:
            driver: Selenium WebDriver instance.
        """
        for i in range(0, 5):
            last_height = driver.execute_script("return document.body.scrollHeight")
            driver.execute_script(f"window.scrollTo(0, {last_height * 5});")
            time.sleep(0.5)

            # Every 3 scrolls down, scroll 1 up
            if i % 3 == 2:
                driver.execute_script(f"window.scrollTo(0, {last_height * -1});")
                time.sleep(0.5)

    def adjust_volume(self, sound_file: str, target_dBFS: float) -> None:
        """
        Normalize a sound file to a target volume level.
        
        Args:
            sound_file: Path to the MP3 file.
            target_dBFS: Target volume level in dBFS.
        """
        sound = AudioSegment.from_file(sound_file, format="mp3")
        difference = target_dBFS - sound.dBFS
        adjusted_sound = sound.apply_gain(difference)
        adjusted_sound.export(sound_file, format="mp3")
