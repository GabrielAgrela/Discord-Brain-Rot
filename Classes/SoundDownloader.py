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

class SoundDownloader:
    def __init__(self,db):
        self.db = db
        self.service = Service()
        self.options = webdriver.ChromeOptions()
        self.options.add_argument('--log-level=3')
        self.options.add_experimental_option("prefs", {
            "download.default_directory": r"H:\bup82623\Downloads",
            "download.prompt_for_download": False,

        })
        self.options.add_argument('--headless')
        self.options.add_argument('window-size=1200x600')
        self.options.add_argument('load-extension=' + r'C:\Users\netco\Desktop\1.52.2_0')

    def download_sound(self):
        try:
            print(self.__class__.__name__,": Opening Chrome")
            self.driver = webdriver.Chrome(service=self.service, options=self.options)
            self.driver.get("https://www.myinstants.com/en/index/pt/")
            print(self.__class__.__name__,": Opening MyInstants")
            wait = WebDriverWait(self.driver, 0)
            consent_button = wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="tyche_cmp_modal"]/div/div/div/div[5]/div[2]/a')))
            print(self.__class__.__name__,": Clicking consent button")
            consent_button.click()
            print(self.__class__.__name__,": Scrolling down to get more sounds")
            self.scroll_a_little(self.driver)
            sound_elements = wait.until(EC.presence_of_all_elements_located((By.XPATH, '//a[@class="instant-link link-secondary"]')))
            print(self.__class__.__name__,": ",str(len(sound_elements)) + " Sounds found")
            random_sound_element = random.choice(sound_elements)
            
            self.driver.execute_script("arguments[0].scrollIntoView(true);", random_sound_element)
            self.driver.execute_script("arguments[0].click();", random_sound_element)
            print(self.__class__.__name__,": ",random_sound_element, " chosen")
            download_button = wait.until(EC.element_to_be_clickable((By.XPATH, '//a[contains(@class, "instant-page-extra-button btn btn-primary")][contains(text(),"Download MP3")]')))
            print(self.__class__.__name__,": Clicking download sound")
            self.driver.execute_script("arguments[0].click();", download_button)
            time.sleep(5)
            list_of_files = glob.glob('H:/bup82623/Downloads/*')
            latest_file = max(list_of_files, key=os.path.getctime)
            print(self.__class__.__name__,": Adjusting sound volume")
            self.adjust_volume(latest_file, -20.0)
            destination_folder = 'H:/bup82623/Downloads/sounds/'
            if not os.path.exists(os.path.join(destination_folder, os.path.basename(latest_file))):
                print(self.__class__.__name__,":Moving file to " + destination_folder)
                shutil.move(latest_file, os.path.join(destination_folder, os.path.basename(latest_file)))
                self.db.add_entry(os.path.basename(latest_file))
                
            else:
                
                print(self.__class__.__name__,": Sound already exists")
                print(self.__class__.__name__,": Removing file")
                os.remove(latest_file)
            #delete file
            

            self.driver.quit()
        except Exception as e:
            print(self.__class__.__name__,": Error downloading sound: ", e)
            time.sleep(15)
            self.driver.quit()
        print(self.__class__.__name__,": Sound Dowloader finished")
        print("\n-----------------------------------\n")

    def scroll_a_little(self, driver):
        # Get the current scroll height of the page
        for i in range(0, 5):
            last_height = driver.execute_script("return document.body.scrollHeight")
        
            
            # Scroll to the random height
            driver.execute_script(f"window.scrollTo(0, {last_height*5});")
            time.sleep(1)  # Allow the page to load

    def adjust_volume(self, sound_file, target_dBFS):
        sound = AudioSegment.from_file(sound_file, format="mp3")
        difference = target_dBFS - sound.dBFS
        adjusted_sound = sound.apply_gain(difference)
        adjusted_sound.export(sound_file, format="mp3")

        
