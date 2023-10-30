import csv
import random
import os
import difflib


class AudioDatabase:
    def __init__(self, csv_filename):
        self.csv_filename = csv_filename

    def add_filename(self, filename):
        with open(self.csv_filename, mode='a', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow([filename])
        print(f"Filename added: {filename}")

    def modify_filename(self, old_filename, new_filename):
        print(f"Modifying {old_filename} to {new_filename}")
        sim, old_filename = self.get_most_similar_filename(old_filename)
        
        data = self._read_data()
        for row in data:
            if row['Filename.mp3'] == old_filename:
                row['Filename.mp3'] = new_filename+".mp3"  # Updating the originalfilename as well
                
                try:
                    # Check if new_filename already exists
                    if not os.path.exists("H:/bup82623/Downloads/sounds/" + new_filename + ".mp3"):
                        os.rename("H:/bup82623/Downloads/sounds/" + old_filename, "H:/bup82623/Downloads/sounds/" + new_filename + ".mp3")
                    else:
                        print("file already exists")
                        return
                except:
                    print("error renaming file")
                    return
                
                self._write_data(data)
                print(f"Modified {old_filename} to {new_filename}")
                return
        
        print(f"Filename not found: {old_filename}")

    def _read_data(self):
        data = []
        if os.path.exists(self.csv_filename):
            with open(self.csv_filename, mode='r', newline='', encoding='utf-8') as file:
                reader = csv.DictReader(file)
                data = [row for row in reader]
                print(f"Read {len(data)} rows")
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
                print(f"Read {len(filenames)} filenames")
        return filenames
    
    def get_most_similar_filename(self, query_filename):
        filenames = self._read_filenames()
        if not filenames:
            return None
        
        most_similar_filename = None
        max_similarity = 0
        for filename in filenames:
            
            similarity = difflib.SequenceMatcher(None, query_filename.replace("*play ",""), filename.replace(".mp3","")).ratio() * 100
            if similarity > max_similarity:
                max_similarity = similarity
                most_similar_filename = filename
                
        print(f"Maximum similarity is: {max_similarity:.2f}%")
        return max_similarity,most_similar_filename
    
    def get_id_by_filename(self, query_filename):
        similarity, most_similar_filename = self.get_most_similar_filename(query_filename)
        
        if most_similar_filename:
            data = self._read_data()
            for row in data:
                if row['Filename.mp3'] == most_similar_filename:
                    print(f"Most similar filename: {most_similar_filename} with similarity of {similarity:.2f}%.")
                    return row['id']
                    
        print("No similar filename found.")
        return None


