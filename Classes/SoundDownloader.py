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
            print(self.__class__.__name__,": ",str(len(sound_elements)) + " Sounds found")
            random_sound_element = random.choice(sound_elements)
            
            self.driver.execute_script("arguments[0].scrollIntoView(true);", random_sound_element)
            time.sleep(2)
            self.driver.execute_script("arguments[0].click();", random_sound_element)
            time.sleep(1)
            try:
                # Find the <ins> tag with id starting with 'gpt'
                ins_tag = self.driver.find_element(By.CSS_SELECTOR, "ins[id^='gpt']")

                # Find the iframe within the <ins> tag
                iframe = ins_tag.find_element(By.TAG_NAME, "iframe")

                # Switch to the iframe
                self.driver.switch_to.frame(iframe)

                # Check if there's an extra iframe within the current iframe
                try:
                    inner_iframe = self.driver.find_element(By.TAG_NAME, "iframe")
                    self.driver.switch_to.frame(inner_iframe)
                    print(self.__class__.__name__, ": Switched to inner iframe")
                except Exception as e:
                    print(self.__class__.__name__, ": No inner iframe found")

                # Find the dismiss button
                dismiss_button = self.driver.find_element(By.ID, "dismiss-button")
                print(self.__class__.__name__, ": Clicking dismiss button")
                self.driver.execute_script("arguments[0].click();", dismiss_button)

                # Switch back to the main content
                self.driver.switch_to.default_content()
            except Exception as e:
                print(self.__class__.__name__, ": No dismiss button found ")
            time.sleep(1)
            #try to click //*[@id="dismiss-button"]
            try:
                # Find the <ins> tag
                ins_tag = self.driver.find_element(By.TAG_NAME, "ins")

                # Find the iframe within the <ins> tag
                iframe = ins_tag.find_element(By.TAG_NAME, "iframe")

                # Switch to the iframe
                self.driver.switch_to.frame(iframe)

                # Find the dismiss button
                dismiss_button = self.driver.find_element(By.ID, "dismiss-button")
                print(self.__class__.__name__, ": Clicking dismiss button")
                self.driver.execute_script("arguments[0].click();", dismiss_button)

                # Switch back to the main content
                self.driver.switch_to.default_content()
            except Exception as e:
                print(self.__class__.__name__, ": No dismiss button found ")
            download_button = wait.until(EC.element_to_be_clickable((By.XPATH, '//a[contains(@class, "instant-page-extra-button btn btn-primary")][contains(text(),"Download MP3")]')))
            print(self.__class__.__name__,": Clicking download sound")
            self.driver.execute_script("arguments[0].click();", download_button)
            # WAIT FOR DOWNLOAD TO FINISH
            print(self.__class__.__name__,": Waiting for download to finish")
            time.sleep(10)
        except Exception as e:
            print(self.__class__.__name__,": Error downloading sound: ", e)
            self.driver.quit()
        print(self.__class__.__name__,": Sound Dowloader finished")
        print("\n-----------------------------------\n")

        self.driver.quit()

    def move_sounds(self):
        list_of_files = glob.glob(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Downloads","*.mp3")))
        print(self.__class__.__name__," MOVER: ",str(len(list_of_files)) + " files found")
        for file in list_of_files:
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

        
