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
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

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
    
    # Number of threads to use for downloading sounds
    DOWNLOAD_THREADS = 8
    
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
        self.chromedriver_path = os.getenv("CHROMEDRIVER_PATH")
        if not self.chromedriver_path:
            # Try to use system-installed chromium-driver first (Docker)
            if os.path.exists('/usr/bin/chromedriver'):
                self.chromedriver_path = '/usr/bin/chromedriver'
            elif os.path.exists('/usr/bin/chromium-driver'):
                self.chromedriver_path = '/usr/bin/chromium-driver'
            else:
                # Fallback to auto-download
                self.chromedriver_path = ChromeDriverManager().install()
        self.dwdir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "Downloads"))
        
    def _create_driver(self):
        """Create a new Chrome WebDriver instance."""
        service = Service(executable_path=self.chromedriver_path)
        options = webdriver.ChromeOptions()
        # Use chromium binary (installed in Docker as 'chromium')
        options.binary_location = '/usr/bin/chromium'
        options.add_argument('--log-level=3')
        options.add_experimental_option("prefs", {
            "download.default_directory": self.dwdir,
            "download.prompt_for_download": False,
        })
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')  # Required for Docker
        options.add_argument('--disable-dev-shm-usage')  # Overcome limited resource problems
        options.add_argument('--disable-gpu')  # Disable GPU acceleration
        options.add_argument('window-size=1200x600')
        return webdriver.Chrome(service=service, options=options)

    def _check_sound_exists_in_db(self, filename: str) -> bool:
        """
        Check if sound exists in database.
        
        Args:
            filename: Original filename to check.
            
        Returns:
            True if sound exists, False otherwise.
        """
        try:
            # Create a local connection/cursor for thread safety
            # SQLite cursors are not reentrant, so we must not reuse self.db.cursor
            # when called from multiple threads simultaneously (as in ThreadPoolExecutor)
            import sqlite3
            conn = sqlite3.connect(self.db.db_path, timeout=5.0)
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sounds WHERE originalfilename = ?", (filename,))
            result = cursor.fetchone()
            conn.close()
            return result is not None
        except Exception as e:
            print(f"{self.__class__.__name__}: DB check error: {e}")
            return False

    def _download_single_file(self, url: str, filename: str) -> tuple[str, bool, str]:
        """
        Download a single file from a URL.
        
        Args:
            url: URL to download from.
            filename: Name to save the file as.
            
        Returns:
            Tuple of (filename, success, error_message)
        """
        try:
            # Check if file already exists in Downloads folder
            out_file_path = os.path.join(self.dwdir, filename)
            if os.path.exists(out_file_path):
                return (filename, False, "already exists in Downloads")
            
            # Check if file already exists in Sounds folder
            sounds_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "Sounds"))
            sounds_file_path = os.path.join(sounds_dir, filename)
            if os.path.exists(sounds_file_path):
                return (filename, False, "already exists in Sounds")
            
            # Re-check database right before download (thread-safe, catches race conditions)
            if self._check_sound_exists_in_db(filename):
                return (filename, False, "already in database")
            
            response = requests.get(url, timeout=30)
            if response.status_code == 404:
                return (filename, False, "404 not found")
            with open(out_file_path, 'wb') as out_file:
                out_file.write(response.content)
            return (filename, True, "")
        except Exception as e:
            return (filename, False, str(e))

    def _scrape_single_site(self, country: str) -> list[tuple[str, str]]:
        """
        Scrape a single MyInstants site for sound URLs.
        
        Args:
            country: Country code (pt, us, br).
            
        Returns:
            List of (url, filename) tuples for sounds to download.
        """
        driver = None
        sounds_to_download = []
        
        try:
            print(f"{self.__class__.__name__}: Opening Chrome for {country}")
            driver = self._create_driver()
            base_url = "https://www.myinstants.com/en/"
            categories = "index"
            driver.get(base_url + categories + "/" + country + "/")
            print(f"{self.__class__.__name__}: Opening {base_url}{categories}/{country}/")
            
            wait = WebDriverWait(driver, 0)
            try:
                consent_button = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, '/html/body/div[3]/div[2]/div[1]/div[2]/div[2]/button[1]/p')
                ))
                print(f"{self.__class__.__name__}: Clicking consent button for {country}")
                consent_button.click()
            except Exception:
                print(f"{self.__class__.__name__}: No consent button found for {country}")
            
            print(f"{self.__class__.__name__}: Scrolling down to get more sounds for {country}")
            self.scroll_a_little(driver)
            
            # Get all divs with class instant
            sound_elements = driver.find_elements(By.CSS_SELECTOR, 'div.instant')
            print(f"{self.__class__.__name__}: Found {len(sound_elements)} sounds on {country}")
            
            for sound_element in sound_elements:
                try:
                    button = sound_element.find_element(By.CSS_SELECTOR, 'button.small-button')
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

                    if not self._check_sound_exists_in_db(filename):
                        # Also check if file already exists on disk
                        sounds_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "Sounds"))
                        downloads_dir = self.dwdir
                        if os.path.exists(os.path.join(sounds_dir, filename)):
                            continue
                        if os.path.exists(os.path.join(downloads_dir, filename)):
                            continue
                        sounds_to_download.append((url, filename))
                except Exception as e:
                    print(f"{self.__class__.__name__}: Error processing sound element: {e}")
                    
        except Exception as e:
            print(f"{self.__class__.__name__}: Error scraping {country}: {e}")
        finally:
            if driver:
                driver.quit()
                
        return sounds_to_download

    def download_sound(self) -> None:
        """
        Scrape and download sounds from MyInstants.
        
        Browses all country pages on MyInstants concurrently and downloads
        any sounds that aren't already in the database using multiple threads.
        """
        countries = ["pt", "us", "br"]
        all_sounds_to_download = []
        
        # Scrape all sites concurrently using threads
        print(f"{self.__class__.__name__}: Starting scrape of all {len(countries)} sites concurrently")
        with ThreadPoolExecutor(max_workers=len(countries)) as executor:
            futures = {executor.submit(self._scrape_single_site, country): country 
                      for country in countries}
            
            for future in as_completed(futures):
                country = futures[future]
                try:
                    sounds = future.result()
                    all_sounds_to_download.extend(sounds)
                    print(f"{self.__class__.__name__}: Got {len(sounds)} new sounds from {country}")
                except Exception as e:
                    print(f"{self.__class__.__name__}: Error getting results from {country}: {e}")
        
        # Remove duplicates (same URL might appear on multiple sites)
        unique_sounds = list({url: (url, filename) for url, filename in all_sounds_to_download}.values())
        print(f"{self.__class__.__name__}: {len(unique_sounds)} unique new sounds to download")
        
        if not unique_sounds:
            print(f"{self.__class__.__name__}: No new sounds found")
            print("\n-----------------------------------\n")
            return
        
        # Download all sounds concurrently using thread pool
        new_sounds_downloaded = 0
        new_sounds_invalid = 0
        
        print(f"{self.__class__.__name__}: Starting download with {self.DOWNLOAD_THREADS} threads")
        with ThreadPoolExecutor(max_workers=self.DOWNLOAD_THREADS) as executor:
            futures = {executor.submit(self._download_single_file, url, filename): filename 
                      for url, filename in unique_sounds}
            
            for future in as_completed(futures):
                filename = futures[future]
                try:
                    fname, success, error = future.result()
                    if success:
                        new_sounds_downloaded += 1
                        print(f"{self.__class__.__name__}: Downloaded {fname}")
                    else:
                        new_sounds_invalid += 1
                        print(f"{self.__class__.__name__}: Failed to download {fname}: {error}")
                except Exception as e:
                    new_sounds_invalid += 1
                    print(f"{self.__class__.__name__}: Error downloading {filename}: {e}")
        
        print(
            f"{self.__class__.__name__}: Sound Downloader finished. "
            f"{len(unique_sounds)} new sounds detected, "
            f"{new_sounds_downloaded} sounds added, {new_sounds_invalid} sounds invalid"
        )
        print("\n-----------------------------------\n")

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
                            title=f"🦝 I stole {os.path.basename(file)}",
                            view=sound_view,
                            message_format="image",
                            image_requester="Sound Thief",
                            image_show_footer=False,
                            image_show_sound_icon=False
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
