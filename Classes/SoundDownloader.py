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

class SoundDownloader:
    def __init__(self):
        self.service = Service(ChromeDriverManager().install())
        self.options = webdriver.ChromeOptions()

        self.options.add_experimental_option("prefs", {
            "download.default_directory": r"C:\Users\netco\Downloads",
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True
        })
        self.options.add_argument('--headless')
        self.options.add_argument('window-size=1200x600')


    def scroll_a_little(self, driver):
        # Get the current scroll height of the page
        last_height = driver.execute_script("return document.body.scrollHeight")
    
        
        # Scroll to the random height
        driver.execute_script(f"window.scrollTo(0, {last_height*3});")
        time.sleep(2)  # Allow the page to load




    def adjust_volume(self, sound_file, target_dBFS):
        sound = AudioSegment.from_file(sound_file, format="mp3")
        difference = target_dBFS - sound.dBFS
        adjusted_sound = sound.apply_gain(difference)
        adjusted_sound.export(sound_file, format="mp3")

    def download_sound(self):
        self.driver = webdriver.Chrome(service=self.service, options=self.options)
        self.driver.get("https://www.myinstants.com/en/index/pt/")
        wait = WebDriverWait(self.driver, 2)
        consent_button = wait.until(EC.element_to_be_clickable((By.XPATH, '//button[contains(@class, "fc-cta-consent")]/p[text()="Consent"]')))
        consent_button.click()
        wait = WebDriverWait(self.driver, 10)
        self.scroll_a_little(self.driver)

        sound_elements = wait.until(EC.presence_of_all_elements_located((By.XPATH, '//a[@class="instant-link link-secondary"]')))
        print("-------------------------------" + str(len(sound_elements)))
        random_sound_element = random.choice(sound_elements)
        self.driver.execute_script("arguments[0].scrollIntoView(true);", random_sound_element)
        self.driver.execute_script("arguments[0].click();", random_sound_element)

        download_button = wait.until(EC.element_to_be_clickable((By.XPATH, '//a[contains(@class, "instant-page-extra-button btn btn-primary")][contains(text(),"Download MP3")]')))
        self.driver.execute_script("arguments[0].click();", download_button)
        time.sleep(2)

        list_of_files = glob.glob('C:/Users/netco/Downloads/*')
        latest_file = max(list_of_files, key=os.path.getctime)
        new_file_path = r"C:\Users\netco\Downloads\random.mp3"
        if os.path.exists(new_file_path): 
            os.remove(new_file_path)
        os.rename(latest_file, new_file_path)
        self.adjust_volume(new_file_path, -20.0)
        time.sleep(2)

        self.driver.quit()
