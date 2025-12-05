import asyncio
import csv
from collections import Counter
from datetime import datetime
import discord
import os

class OtherActionsDatabase:
    def __init__(self, csv_filename, bot):
        self.csv_filename = csv_filename
        self.bot = bot
        self._ensure_file_exists()

    def _ensure_file_exists(self):
        if not os.path.exists(self.csv_filename):
            with open(self.csv_filename, mode='w', newline='', encoding='utf-8') as file:
                writer = csv.writer(file)
                writer.writerow(['user', 'action', 'target', 'timestamp'])

    def add_entry(self, user, action, target="none"):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self.csv_filename, mode='a', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow([user, action, target, timestamp])
        print(f"Entry added: User: {user}, Action: {action}, Target: {target}, Timestamp: {timestamp}")

    def get_recent_actions(self, num_results=0):
        data = self._read_data()
        recent_actions = list(reversed(data))
        
        if num_results == 0:
            return recent_actions
        else:
            return recent_actions[:min(num_results, 150)]

    def _read_data(self):
        data = []
        if os.path.exists(self.csv_filename):
            with open(self.csv_filename, mode='r', newline='', encoding='utf-8') as file:
                reader = csv.reader(file)
                next(reader, None)  # Skip the header
                data = [row for row in reader]
        return data

    def _write_data(self, data):
        with open(self.csv_filename, mode='w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow(['user', 'action', 'target', 'timestamp'])  # Writing the header
            writer.writerows(data)