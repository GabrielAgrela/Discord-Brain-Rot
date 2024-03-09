import asyncio
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
                writer.writerow([filename, new_id, filename, False, False])
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
    
    def update_favorite_status(self, audio_file, status):
        print(f"Updating favorite status for {audio_file} to {status}")
        data = self._read_data()
        for row in data:
            if row['Filename.mp3'].strip().lower() == audio_file.strip().lower():
                row['favorite'] = status
                self._write_data(data)
                return
        print(f"Filename not found: {audio_file}")

    def update_blacklist_status(self, audio_file, status):
        print(f"Updating blacklist status for {audio_file} to {status}")
        data = self._read_data()
        for row in data:
            if row['Filename.mp3'].strip().lower() == audio_file.strip().lower():
                row['blacklist'] = status
                self._write_data(data)
                return
        print(f"Filename not found: {audio_file}")

    def is_favorite(self, audio_file):
        data = self._read_data()
        for row in data:
            if row['Filename.mp3'].strip().lower() == audio_file.strip().lower():
                # return row['favorite'] to bool
                return row['favorite'] == "True"
        print(f"Filename not found: {audio_file}")
        return False
    
    def is_blacklisted(self, audio_file):
        data = self._read_data()
        for row in data:
            if row['Filename.mp3'].strip().lower() == audio_file.strip().lower():
                # return row['favorite'] to bool
                return row['blacklist'] == "True"
        print(f"Filename not found: {audio_file}")
        return False
    
    def get_favorite_sounds(self):
        data = self._read_data()
        favorite_sounds = []
        for row in data:
            if row['favorite'] == "True":
                favorite_sounds.append(row['Filename.mp3'])
        return favorite_sounds
    
    def get_blacklisted_sounds(self):
        data = self._read_data()
        blacklisted_sounds = []
        for row in data:
            if row['blacklist'] == "True":
                blacklisted_sounds.append(row['Filename.mp3'])
        return blacklisted_sounds

    async def modify_filename(self, old_filename, new_filename):
        old_filenames = self.get_most_similar_filenames(old_filename)
        old_filename = old_filenames[0][1] if old_filenames else None
        data = self._read_data()
        for row in data:
            if row['Filename.mp3'].strip().lower() == old_filename.strip().lower():
                row['Filename.mp3'] = new_filename+".mp3"  # Updating the originalfilename as well
                bot_channel = await self.bot.get_bot_channel()
                try:
                    # Check if new_filename already exists
                    old_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Sounds", old_filename))
                    new_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Sounds", new_filename + ".mp3"))
                    if not os.path.exists(new_path):
                        os.rename(old_path, new_path)
                    else:
                        await bot_channel.send(embed=discord.Embed(title=f"File already exists",color=self.bot.color))
                        return
                except Exception as e:
                    print("error renaming file" + str(e))
                    # wait 2 seconds and try again
                    if 'used by another process' in str(e):
                        await asyncio.sleep(2)
                        await self.modify_filename(old_filename, new_filename)
                    return
                
                self._write_data(data)
               
                embed = discord.Embed(
                    title=f"Modified {old_filename} to {new_filename}",
                    color=self.bot.color
                )
                #delete last message
                await bot_channel.send(embed=embed)
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
            writer = csv.DictWriter(file, fieldnames=['Filename.mp3', 'id', 'originalfilename', 'favorite', 'blacklist'])
            writer.writeheader()
            writer.writerows(data)

    def get_random_filename(self):
        filenames = self._read_filenames()
        random.shuffle(filenames)  # Shuffle the filenames
        for filename in filenames:  # Iterate over filenames
            if not self.is_blacklisted(filename):  # If filename is not blacklisted
                return filename  # Return the filename
        return None  # Return None if all filenames are blacklisted

    def _read_filenames(self):
        filenames = []
        if os.path.exists(self.csv_filename):
            with open(self.csv_filename, mode='r', newline='', encoding='utf-8') as file:
                reader = csv.reader(file)
                filenames = [row[0] for row in reader]
        return filenames
    
    



    def get_most_similar_filenames(self, query_filename, num_results=1):
        filenames = self._read_filenames()
        if not filenames:
            return None, None
        # Clear query_filename of commands and spaces
        query_filename = query_filename.replace("*p ", "").lower()

        scores = []

        for filename in filenames:
            # Clear db's filename of .mp3
            filename = filename.lower()
            score = fuzz.token_sort_ratio(query_filename, filename)

            query_filename = query_filename.replace("-", " ").replace("_", " ")
            # Split query_filename into words
            query_words = query_filename.split()

            # Calculate the initial fuzz score

            # Increment score for each matching word
            for word in query_words:
                if word in filename:
                    score_increment = (100 - score) / 1.5
                    score += score_increment

            # Update the highest score and corresponding filename
            scores.append((round(score, 2), filename))

        # Sort the scores in descending order and get the top 'num_results' scores
        scores.sort(key=lambda x: x[0], reverse=True)
        top_scores = scores[:num_results]

        # print the top scores and their corresponding filenames
        for score, filename in top_scores:
            print(f"Found {filename}: {score}")

        # Return the top 'num_results' filenames with their scores
        return top_scores






    
    def get_id_by_filename(self, query_filename):
        most_similar_filenames = self.get_most_similar_filenames(query_filename)
        most_similar_filename = most_similar_filenames[0][1] if most_similar_filenames else None
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
