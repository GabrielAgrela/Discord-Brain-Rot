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
    def __init__(self, csv_filename, bot):
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

    async def modify_filename(self, old_filename, new_filename):
        print(f"Modifying {old_filename} to {new_filename}")
        sim, old_filename = self.get_most_similar_filename(old_filename)
        
        data = self._read_data()
        for row in data:
            if row['Filename.mp3'] == old_filename:
                row['Filename.mp3'] = new_filename+".mp3"  # Updating the originalfilename as well
                
                try:
                    # Check if new_filename already exists
                    if not os.path.exists("D:/eu/sounds/" + new_filename + ".mp3"):
                        os.rename("D:/eu/sounds/" + old_filename, "D:/eu/sounds/" + new_filename + ".mp3")
                    else:
                        print("file already exists")
                        return
                except:
                    print("error renaming file")
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

        query_filename = query_filename.replace("*p ", "").replace(" ", "-").lower()
        print(query_filename)

        highest_score = 0
        most_similar_filename = None

        for filename in filenames:
            filename = filename.replace(".mp3", "").lower()
            score = fuzz.token_sort_ratio(query_filename, filename)
            # Additional weight if the query word appears in the filename
            if query_filename in filename.lower():
                score += 20
                if score > 100:
                    score = 100
            
            if score > highest_score:
                highest_score = score
                most_similar_filename = filename

        return highest_score, most_similar_filename+".mp3"






    
    def get_id_by_filename(self, query_filename):
        similarity, most_similar_filename = self.get_most_similar_filename(query_filename)
        
        if most_similar_filename:
            data = self._read_data()
            for row in data:
                if row['Filename.mp3'] == most_similar_filename:
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
