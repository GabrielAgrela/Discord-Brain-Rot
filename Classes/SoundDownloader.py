import asyncio
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options
import time
import os
import glob
import random
from pydub import AudioSegment
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
import shutil
import os
from unidecode import unidecode
import requests
from Classes.UI import SoundView
from Classes.UI import DownloadedSoundView

from Classes.Database import Database

class SoundDownloader:
    def __init__(self, bot, db, chromedriver_path=""):
        self.db = db
        self.bot = bot
        chromedriver_path = os.getenv("CHROMEDRIVER_PATH")
        if not chromedriver_path:
            chromedriver_path = ChromeDriverManager().install()
        self.service = Service(executable_path=chromedriver_path)
        self.options = webdriver.ChromeOptions()
        self.options.add_argument('--log-level=3')
        self.dwdir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Downloads"))
        self.options.add_experimental_option("prefs", {
            "download.default_directory": self.dwdir,
            "download.prompt_for_download": False,

        })
        self.options.add_argument('--headless')
        self.options.add_argument('window-size=1200x600')
        #self.options.add_argument('load-extension=' + r'C:\Users\netco\Desktop\1.52.2_0')

    def download_sound(self):
        try:
            print(self.__class__.__name__,": Opening Chrome")
            self.driver = webdriver.Chrome(service=self.service, options=self.options)
            base_url = "https://www.myinstants.com/en/"
            categories = random.choice(["index"])
            country = random.choice(["pt", "us", "br"])
            self.driver.get(base_url+categories+"/"+country+"/")
            print(self.__class__.__name__,": Opening ", base_url+categories+"/"+country+"/")
            wait = WebDriverWait(self.driver, 0)
            try:
                consent_button = wait.until(EC.element_to_be_clickable((By.XPATH, '/html/body/div[3]/div[2]/div[1]/div[2]/div[2]/button[1]/p')))
                print(self.__class__.__name__,": Clicking consent button")
                consent_button.click()
            except Exception as e:
                print(self.__class__.__name__,": No consent button found")
            print(self.__class__.__name__,": Scrolling down to get more sounds")
            self.scroll_a_little(self.driver)
            #get all divs with class instant
            sound_elements = self.driver.find_elements(By.CSS_SELECTOR, 'div.instant')
            print(self.__class__.__name__,": Found ", len(sound_elements), " sounds")
            new_sounds_detected = 0
            new_sounds_downloaded = 0
            new_sounds_invalid = 0
            for i in range(0, len(sound_elements)):
                button = sound_elements[i].find_element(By.CSS_SELECTOR, 'button.small-button')
                onclick_attr = button.get_attribute('onclick')
                filename = onclick_attr.split("'")[1].split('/')[-1]
                #sometimes it has multiple - in a row, so we need to replace them with just one
                filename = filename.replace("~", "")
                filename = filename.replace("#", "")
                filename = filename.replace("--", "-")
                filename = filename.replace("--", "-")
                filename = filename.replace("...", ".")
                filename = filename.replace("..", ".")
                filename = filename.replace(".mp3.mp3", ".mp3")
                filename = filename.replace('"','')
                url = "https://www.myinstants.com/media/sounds/" + filename

                if not Database().get_sound(filename, original_filename=True):
                    new_sounds_detected += 1
                    response = requests.get(url)
                    # if the file is not found, we will skip it
                    if response.status_code == 404:
                        new_sounds_invalid += 1
                        print(f"File {filename} not found, skipping download.")
                    else:
                        new_sounds_downloaded += 1
                        out_file_path = os.path.join(self.dwdir, filename)
                        with open(out_file_path, 'wb') as out_file:
                            # write the file to self.dwdir location
                            out_file.write(response.content)
        except Exception as e:
            print(self.__class__.__name__,": Error downloading sound: ", e)
            self.driver.quit()
        try:
            print(self.__class__.__name__,": Sound Dowloader finished. " + str(new_sounds_detected) + " new sounds detected, " + str(new_sounds_downloaded) + " sounds added, " + str(new_sounds_invalid) + " sounds invalid (wrong url)")
            print("\n-----------------------------------\n")
        except Exception as e:
            print(self.__class__.__name__,": Error printing sound downloader finished: ", e)

        self.driver.quit()

    async def move_sounds(self):   
        while True: 
            list_of_files = glob.glob(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Downloads","*.mp3")))
          #  print(self.__class__.__name__," MOVER: ",str(len(list_of_files)) + " files found")
            for file in list_of_files:
                try:
                    print(self.__class__.__name__," MOVER: ",file, " chosen")
                    print(self.__class__.__name__," MOVER: Adjusting sound volume")
                    self.adjust_volume(file, -20.0)
                    destination_folder = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Sounds"))
                    
                    if not Database().get_sound(os.path.basename(file), original_filename=True):
                        print(self.__class__.__name__," MOVER:Moving file to " + destination_folder)
                        sound_view = DownloadedSoundView(self.bot, os.path.basename(file))
                        await self.bot.send_message(title="I stole "+os.path.basename(file)+" to our database hehe", view=sound_view)
                        shutil.move(file, os.path.join(destination_folder, os.path.basename(file)))
                        Database().insert_sound(os.path.basename(file), os.path.basename(file))
                        Database().insert_action("admin", "scrape_sound", os.path.basename(file))
                    else:
                        print(self.__class__.__name__," MOVER: Sound already exists ", os.path.basename(file))
                        print(self.__class__.__name__," MOVER: Removing file")
                        os.remove(file)
                except Exception as e:
                    print(self.__class__.__name__," MOVER: Error moving sound: ", e)
                    os.remove(file)
            await asyncio.sleep(10)

    def scroll_a_little(self, driver):
        # Get the current scroll height of the page
        for i in range(0, 5):
            last_height = driver.execute_script("return document.body.scrollHeight")
            
            # Scroll to the random height
            driver.execute_script(f"window.scrollTo(0, {last_height*5});")
            time.sleep(.5)  # Allow the page to load

            # Every 2 scrolls down, scroll 1 up
            if i % 3 == 2:
                driver.execute_script(f"window.scrollTo(0, {last_height*-1});")
                time.sleep(.5)  # Allow the page to load
                
    def adjust_volume(self, sound_file, target_dBFS):
        sound = AudioSegment.from_file(sound_file, format="mp3")
        difference = target_dBFS - sound.dBFS
        adjusted_sound = sound.apply_gain(difference)
        adjusted_sound.export(sound_file, format="mp3")

        
