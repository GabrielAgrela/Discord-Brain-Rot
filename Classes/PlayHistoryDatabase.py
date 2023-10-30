import csv
from datetime import datetime

class PlayHistoryDatabase:
    def __init__(self, csv_filename, db):
        self.csv_filename = csv_filename
        self.db = db

    def add_entry(self, filename, username):
        current_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self.csv_filename, mode='a', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            sound_id = self.db.get_id_by_filename(filename)
            writer.writerow([sound_id, username, current_datetime])
        print(f"Entry added: Sound ID:{sound_id}, Username: {username}, Datetime: {current_datetime}")