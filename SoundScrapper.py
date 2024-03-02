from asyncio import Queue
import asyncio
import os
import discord
from Classes.Environment import Environment
from Classes.Bot import Bot
from Classes.SoundEventsLoader import SoundEventLoader
from Classes.BotBehaviour import BotBehavior
import threading
from pynput import keyboard
import time
from collections import defaultdict
from datetime import datetime, timedelta
import csv
from collections import Counter
from Classes.AudioDatabase import AudioDatabase
from Classes.SoundDownloader import SoundDownloader

db = AudioDatabase(os.path.join(os.path.dirname(__file__), "Data/soundsDB.csv"), "null")
while True:
    SoundDownloader(db).download_sound()