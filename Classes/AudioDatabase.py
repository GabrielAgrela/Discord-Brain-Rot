import csv
import random
import os
import difflib
import discord
import Levenshtein
from difflib import SequenceMatcher
import re
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
from fuzzywuzzy import process
from fuzzywuzzy import fuzz
class AudioDatabase:
    def __init__(self, csv_filename, bot=""):
        self.csv_filename = csv_filename
        self.bot = bot

    def add_entry(self, filename, original_filename=None):
        
        if filename:
            data = self._read_data()
            new_id = len(data) + 1  # Assigning the next ID based on the number of existing rows

            with open(self.csv_filename, mode='a', newline='', encoding='utf-8') as file:
                writer = csv.writer(file)
                writer.writerow([filename, new_id, filename])
                print(f"Entry added: id: {new_id}, Filename: {filename}, Original Filename: {filename}")
        else:
            print("No similar filename found. Entry not added.")
    
    def check_if_sound_exists(self, filename):
        print(f"Checking if {filename} exists")
        data = self._read_data()
        for row in data:
            if row['originalfilename'] == filename:
                return True
        return False

    async def modify_filename(self, old_filename, new_filename):
        print(f"Modifying {old_filename} to {new_filename}")
        sim, old_filename = self.get_most_similar_filename(old_filename)
        
        data = self._read_data()
        for row in data:
            if row['Filename.mp3'] == old_filename:
                row['Filename.mp3'] = new_filename+".mp3"  # Updating the originalfilename as well
                
                try:
                    # Check if new_filename already exists
                    old_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Sounds", old_filename))
                    new_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Sounds", new_filename + ".mp3"))
                    if not os.path.exists(new_path):
                        os.rename(old_path, new_path)
                    else:
                        print("file already exists")
                        return
                except Exception as e:
                    print("error renaming file" + str(e))
                    return
                
                self._write_data(data)
                bot_channel = discord.utils.get(self.bot.guilds[0].text_channels, name='bot')
        
                embed = discord.Embed(
                    title=f"Modified {old_filename} to {new_filename}",
                    color=discord.Color.purple()
                )
                #delete last message
                await bot_channel.send(embed=embed)

                print()
                return
        
        print(f"Filename not found: {old_filename}")

    def _read_data(self):
        data = []
        if os.path.exists(self.csv_filename):
            with open(self.csv_filename, mode='r', newline='', encoding='utf-8') as file:
                reader = csv.DictReader(file)
                data = [row for row in reader]
        return data

    def _write_data(self, data):
        with open(self.csv_filename, mode='w', newline='', encoding='utf-8') as file:
            writer = csv.DictWriter(file, fieldnames=['Filename.mp3', 'id', 'originalfilename'])
            writer.writeheader()
            writer.writerows(data)

    def get_random_filename(self):
        filenames = self._read_filenames()
        return random.choice(filenames) if filenames else None

    def _read_filenames(self):
        filenames = []
        if os.path.exists(self.csv_filename):
            with open(self.csv_filename, mode='r', newline='', encoding='utf-8') as file:
                reader = csv.reader(file)
                filenames = [row[0] for row in reader]
        return filenames
    
    



    def get_most_similar_filename(self, query_filename):
        filenames = self._read_filenames()
        if not filenames:
            return None, None
        #Clear query_filename of commands and spaces
        query_filename = query_filename.replace("*p ", "").lower()

        highest_score = 0
        most_similar_filename = None

        for filename in filenames:
            # Clear db's filename of .mp3
            filename = filename.replace(".mp3", "").lower()
            score = fuzz.token_sort_ratio(query_filename, filename)

            query_filename = query_filename.replace("-", " ")
            # Split query_filename into words
            query_words = query_filename.split()

            # Calculate the initial fuzz score
            

            # Increment score for each matching word
            for word in query_words:
                if word in filename:
                    score_increment = (100 - score) / 1.5
                    score += score_increment
                    # Cap the score at 99
                    if score > 99:
                        score = 99

            # Update the highest score and corresponding filename
            if score > highest_score:
                highest_score = score
                most_similar_filename = filename


        #return with .mp3 for comparison (fix this later, kinda stinky)
        return highest_score, most_similar_filename+".mp3"






    
    def get_id_by_filename(self, query_filename):
        similarity, most_similar_filename = self.get_most_similar_filename(query_filename)
        
        if most_similar_filename:
            data = self._read_data()
            for row in data:
                if row['Filename.mp3'].lower() == most_similar_filename.lower():
                    return row['id']
                    
        print("No similar filename found.")
        return None

    def get_filename_by_id(self, query_id):
        data = self._read_data()  # Reading the data from the CSV
        for row in data:
            
            if int(row['id']) == int(query_id):  # Comparing ids as integers
                filename = row['Filename.mp3']
                return filename  # Returning the filename if id is found
            
        print(f"No filename found for id: {query_id}")  # Printing a message if no matching id is found
        return None  # Returning None if no matching id is found
