import json
import os
from Classes.SoundEventFactory import SoundEventFactory

class SoundEventLoader:
    def __init__(self, script_path):
        script_dir = os.path.dirname(script_path)

        self.sounds_path = os.path.join(script_dir, 'Data', 'Sounds.json')
        self.users_path = os.path.join(script_dir, 'Data', 'Users.json')

    def load_sound_events(self):
        with open(self.sounds_path, 'r') as f:
            sound_keys = json.load(f)

        with open(self.users_path, 'r', encoding='utf-8') as f:
            user_data = json.load(f)

        sounds = {sound: os.getenv(f'SOUND_{sound}') for sound in sound_keys}
        users = {user: [SoundEventFactory.create_sound_event(user, event['event'], sounds[event['sound']]) for event in events] for user, events in user_data.items()}

        return users, sounds
