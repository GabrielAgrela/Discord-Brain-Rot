import json
import os
import random

class UsersUtils:
    def __init__(self, json_file):
        self.json_file = json_file
        self.users = self.load_users(json_file)
    
    def load_users(self, json_file):
        with open(json_file, 'r') as f:
            data = json.load(f)
            return [User(name, events_data) for name, events_data in data.items()]
        
    def get_users_names(self):
        return [user.name for user in self.users]

    def get_user_events_by_name(self, name):
        for user in self.users:
            if user.name == name:
                unique_events = []
                event_names = set()
                random.shuffle(user.events)  # Randomly shuffle the events
                for event in user.events:
                    if event.event_code not in event_names:
                        event_names.add(event.event_code)
                        unique_events.append(event)
                return unique_events
        return None

class User:
    def __init__(self, name, events_data):
        self.name = name
        self.events = [Event(event_data) for event_data in events_data]

class Event:
    def __init__(self, event_data):
        self.event_code = event_data.get('event')
        self.sound = event_data.get('sound')





