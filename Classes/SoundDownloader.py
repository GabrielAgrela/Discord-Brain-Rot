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

class SoundDownloader:
    def __init__(self,db, chromedriver_path=""):
        self.db = db
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
            base_url = "https://www.myinstants.com/en/index/"
            country = random.choice(["pt", "us", "br"])
            self.driver.get(base_url+country+"/")
            print(self.__class__.__name__,": Opening ", base_url+country+"/")
            wait = WebDriverWait(self.driver, 0)
            consent_button = wait.until(EC.element_to_be_clickable((By.XPATH, '/html/body/div[3]/div[2]/div[1]/div[2]/div[2]/button[1]/p')))
            print(self.__class__.__name__,": Clicking consent button")
            consent_button.click()
            print(self.__class__.__name__,": Scrolling down to get more sounds")
            self.scroll_a_little(self.driver)
            sound_elements = wait.until(EC.presence_of_all_elements_located((By.XPATH, '//a[@class="instant-link link-secondary"]')))
            print(self.__class__.__name__,": Found ", len(sound_elements), " sounds")
            new_sounds_detected = 0
            new_sounds_downloaded = 0
            new_sounds_invalid = 0
            #for each sound_elements, download the sound by going to the url "https://www.myinstants.com/media/sounds/"+sound element text to lowercase+".mp3"
            for i in range(0, len(sound_elements)):
                filename = unidecode(sound_elements[i].text.lower().replace("*", "").replace("_", "-").replace("'", "").replace(" ", "-").replace(",", "").replace("?", "").replace("!", "").replace(":", "").replace("(", "").replace(")", "")) + ".mp3"
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

                if not self.db.check_if_sound_exists(filename):
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
        print(self.__class__.__name__,": Sound Dowloader finished " + str(new_sounds_detected) + " sounds detected, " + str(new_sounds_downloaded) + " sounds downloaded, " + str(new_sounds_invalid) + " sounds invalid")
        print("\n-----------------------------------\n")

        self.driver.quit()

    def move_sounds(self):    
        list_of_files = glob.glob(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Downloads","*.mp3")))
        print(self.__class__.__name__," MOVER: ",str(len(list_of_files)) + " files found")
        for file in list_of_files:
            try:
                print(self.__class__.__name__," MOVER: ",file, " chosen")
                print(self.__class__.__name__," MOVER: Adjusting sound volume")
                self.adjust_volume(file, -20.0)
                destination_folder = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Sounds"))
                
                if not self.db.check_if_sound_exists(os.path.basename(file)):
                    print(self.__class__.__name__," MOVER:Moving file to " + destination_folder)
                    shutil.move(file, os.path.join(destination_folder, os.path.basename(file)))
                    self.db.add_entry(os.path.basename(file))
                else:
                    print(self.__class__.__name__," MOVER: Sound already exists ", os.path.basename(file))
                    print(self.__class__.__name__," MOVER: Removing file")
                    os.remove(file)
            except Exception as e:
                os.remove(file)

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

        
