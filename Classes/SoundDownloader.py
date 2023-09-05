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

class SoundDownloader:
    def __init__(self):
        self.service = Service()
        self.options = webdriver.ChromeOptions()
        self.options.add_argument('--log-level=3')
        self.options.add_experimental_option("prefs", {
            "download.default_directory": r"H:\bup82623\Downloads",
            "download.prompt_for_download": False,

        })
        self.options.add_argument('--headless')
        self.options.add_argument('window-size=1200x600')


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
        print("")

    #def get_latest_mp3_in_downloads(self):
        

    async def download_sound(self, manual=True):
        print("01 " + time.strftime("%H:%M:%S", time.localtime()))
        self.driver = webdriver.Chrome(service=self.service, options=self.options)
        print("02 " + time.strftime("%H:%M:%S", time.localtime()))
        self.driver.get("https://www.myinstants.com/en/index/pt/")
        print("03 " + time.strftime("%H:%M:%S", time.localtime()))
        wait = WebDriverWait(self.driver, 0)
        print("1 " + time.strftime("%H:%M:%S", time.localtime()))
        consent_button = wait.until(EC.element_to_be_clickable((By.XPATH, '//button[contains(@class, "fc-cta-consent")]/p[text()="Consent"]')))
        consent_button.click()
        #wait = WebDriverWait(self.driver, 10)
        self.scroll_a_little(self.driver)
        print("2 " + time.strftime("%H:%M:%S", time.localtime()))
        sound_elements = wait.until(EC.presence_of_all_elements_located((By.XPATH, '//a[@class="instant-link link-secondary"]')))
        print("I FOUND " + str(len(sound_elements)) + " MOTHERFUCKING SOUNDS " + time.strftime("%H:%M:%S", time.localtime()))
        random_sound_element = random.choice(sound_elements)
        self.driver.execute_script("arguments[0].scrollIntoView(true);", random_sound_element)
        self.driver.execute_script("arguments[0].click();", random_sound_element)
        print("3 " + time.strftime("%H:%M:%S", time.localtime()))
        download_button = wait.until(EC.element_to_be_clickable((By.XPATH, '//a[contains(@class, "instant-page-extra-button btn btn-primary")][contains(text(),"Download MP3")]')))
        print("4 " + time.strftime("%H:%M:%S", time.localtime()))
        self.driver.execute_script("arguments[0].click();", download_button)
        time.sleep(2)
        try:
            list_of_files = glob.glob('H:/bup82623/Downloads/*')
            latest_file = max(list_of_files, key=os.path.getctime)
            self.adjust_volume(latest_file, -20.0)
            print("5 " + time.strftime("%H:%M:%S", time.localtime()))
            self.driver.quit()
        except:
            print("error ")
            self.driver.quit()
        #time.sleep(2)

        
