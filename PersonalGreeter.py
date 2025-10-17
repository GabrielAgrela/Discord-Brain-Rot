import asyncio
import base64
import os
import subprocess
import discord
from discord.ext import tasks
import sqlite3
import datetime
from Classes.Environment import Environment
from Classes.Bot import Bot
from Classes.BotBehaviour import BotBehavior
from discord.commands import Option
from discord import default_permissions
from Classes.UsersUtils import UsersUtils
from Classes.SoundDownloader import SoundDownloader
from Classes.Database import Database
from Classes.MinecraftLogMonitor import MinecraftLogMonitor
import random
import time
import wave
import io
import numpy as np
from pydub import AudioSegment
from pydub.effects import normalize
from pydub.silence import detect_nonsilent
from discord.sinks import WaveSink
import json
from Classes.SpeechRecognition import SpeechRecognizer, DiscordVoiceListener
import platform # Added for OS detection
import re # Add import for regex

env = Environment()
intents = discord.Intents(guilds=True, voice_states=True, messages=True, message_content=True, members=True)
bot = Bot(command_prefix="*", intents=intents, token=env.bot_token, ffmpeg_path=env.ffmpeg_path)

# Usage
#userUtils = UsersUtils(os.path.abspath(os.path.join(os.path.dirname(__file__), "Data", "Users.json")))

behavior = BotBehavior(bot, env.ffmpeg_path)
db = Database(behavior=behavior)
file_name = 'play_requests.csv'

EMBEDDED_PROFILE_THUMBNAILS = {
    "ventura": {
        "filename": "ventura.jpg",
        "data": (
            "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAIBAQEBAQIBAQECAgICAgQDAgICAgUEBAMEBgUGBgYF"
            "BgYGBwkIBgcJBwYGCAsICQoKCgoKBggLDAsKDAkKCgr/2wBDAQICAgICAgUDAwUKBwYHCgoKCgoK"
            "CgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgr/wAARCAEAAQADASIA"
            "AhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQA"
            "AAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3"
            "ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWm"
            "p6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEA"
            "AwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSEx"
            "BhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElK"
            "U1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3"
            "uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD5Dooo"
            "r8LP9VAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooA"
            "KKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAo"
            "oooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACii"
            "igAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKK"
            "ACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooA"
            "KKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAo"
            "oooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACii"
            "igD6Y/Yf/wCCWHx2/b78D6x44+DPxG8CWCaFqgsdR07xHqd5DdIWjWRJdsNpKvlsCwB3ZzG4wMAn"
            "23/iG4/bj/6Kr8KP/B5qf/yurn/+CAv7SX/Cmf21B8K9Yv8AytH+JGmNpjq7YRb+HdNaufUnE0IH"
            "rcCv3Tr7jI8lyrM8Aqk0+ZNp69f+Gsfy34peJnHvBPFk8Fh5w9hKMZ07wTfK9Gm+tpKS9LH4mf8A"
            "ENx+3H/0VX4Uf+DzU/8A5XUf8Q3H7cf/AEVX4Uf+DzU//ldX7Z0V7H+qmUdn95+c/wDEfvEP/n5T"
            "/wDBa/zP5ev2hfgT47/Zl+NPiH4EfEuO2Gt+Gr/7NevZSM0E2VV0ljZ1VjG6MjqWVSVYZAPFcZX6"
            "Zf8AByJ+zj/wjfxZ8HftQ6JYbbXxNp7aLrkiLwLy2+eB2P8AeeB2Ue1rX5m1+fZng3gMfUodE9PR"
            "6r8D+vuB+I48WcKYXM9Oacfft0nH3Zq3RcydvKwUUUVwH1gUUUUAFdx+zd+z74//AGqPjboHwE+F"
            "62g1vxDcvFay6hI6W8KpG8sksrIjsqKiMxIVjgcA1w9fqD/wba/s4/2x468b/tUa3YboNGtE8P6D"
            "K65BuZts1yy+jJEsK/S4avQyvB/X8fCh0b19Fq/wPkeO+JFwlwniszVueEbQv1nJ8sNOq5mm12TO"
            "D/4huP24/wDoqvwo/wDB5qf/AMrqP+Ibj9uP/oqvwo/8Hmp//K6v2zor9A/1Uyjs/vP5D/4j94h/"
            "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"
            "JoPiC1t5beK+S0huB5Uq7XRo50eNwR/eU4IBGCAR6WU4/wDs3HRrvZaO3Z/1c+M8QOFP9c+Fa+Vx"
            "aVSVnByvZTi7puybSesW0m7N6H9QlFfz6/8AD77/AIKhf9HO/wDll6J/8hUf8Pvv+CoX/Rzv/ll6"
            "J/8AIVfbf645Z/JP7o//ACR/L3/EuPHH/QRhv/A6v/yk/oKor+fX/h99/wAFQv8Ao53/AMsvRP8A"
            "5Co/4fff8FQv+jnf/LL0T/5Co/1xyz+Sf3R/+SD/AIlx44/6CMN/4HV/+Un1n/wcmftJeVaeB/2T"
            "tDv+ZWbxJ4hjRv4Rvt7RDjsT9pYqf7sZ9K/J6uw+O3x8+Ln7THxLvfi/8cPGMmu+ItQihjutQe1h"
            "gBSKNY0VY4ESNAFUcKoyck5JJPH18RmuO/tHHzrrZ7X7LY/qPgHhZcG8K4fK205xTc2r2c5O8mm0"
            "m0tk2k7JaIKKKK84+xCiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
            "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigA"
            "ooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigD/9k="
        ),
    },
    "costa": {
        "filename": "costa.jpg",
        "data": (
            "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAIBAQEBAQIBAQECAgICAgQDAgICAgUEBAMEBgUGBgYF"
            "BgYGBwkIBgcJBwYGCAsICQoKCgoKBggLDAsKDAkKCgr/2wBDAQICAgICAgUDAwUKBwYHCgoKCgoK"
            "CgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgr/wAARCAEAAQADASIA"
            "AhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQA"
            "AAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3"
            "ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWm"
            "p6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEA"
            "AwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSEx"
            "BhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElK"
            "U1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3"
            "uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDxeiii"
            "v7cP4vCiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigA"
            "ooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
            "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKK"
            "KACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
            "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigA"
            "ooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
            "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKK"
            "KACiiigAooooAK6D4afCf4mfGXxPF4M+FPgTVfEGqS8rZaVZPM6rnG9towijuzYUdyK+uf8Agn3/"
            "AMEe/Hn7SdrZfFr48TXvhfwTMFlsbRE2ahrEfUMgYEQQkdJGBLD7q4Icfq98GfgR8IP2e/B8XgT4"
            "NeANP0DTYwN8VlD887AY3yyNl5n/ANpyx96/NuJ/EjLMkqSw2EXtqq0evuxfm+r8l6Npn6Lw14dZ"
            "lnMI4jFP2VJ6rT3pLyXReb9Umj8vPgV/wQP/AGhPGsEOrfHL4g6P4Lt3AZtOtE/tK9X/AGWCMsK/"
            "USPj0r6k+HH/AAQs/Ym8HxRv4yXxP4smGDL/AGprRt4mP+ytqsTKPYuT719mUV+QZj4gcV5jJ3xD"
            "prtD3bfNe998mfreX8B8L5fFWoKb7z96/wAn7v3I8O8O/wDBNX9g/wALxrFpn7L/AIXlCjg6jbPe"
            "H8TOzk/jXQp+xF+xnHH5S/sm/DbGMZbwRYE/mYs16hRXzk84zerK88RNvznJ/qfQQyjKaatDDwS8"
            "oR/yPGtb/wCCeX7DviCMx3/7LHguMEYJsdEjtT+cIUivMPH/APwRP/YJ8aRONE8D634YlfOZ9A8Q"
            "zEg+oW6MyD6BcV9aUV0YfiPP8JK9LFVF/wBvyt917HPiOHsixUbVcLTf/bkb/fa5+XXxm/4N8fFl"
            "hFNqPwB+O1nqOMmLSvFVi1u+PT7RDvVmPvGg9xXxd8f/ANjX9pj9mG7aP4z/AAj1TS7QSbI9XjjE"
            "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"
            "W1q4Q3N82Rg/6RKWdQe6qQvtXqtFFfHYnF4rG1nVxE3OT6ybb+9n1+GwuGwdJUqEFCK6RSS+5H8+"
            "37e3/J7HxW/7H7VP/Sl68kr1v9vb/k9j4rf9j9qn/pS9eSV/YmUf8inD/wCCH/pKP5Fzb/kaV/8A"
            "HL/0phRRRXoHAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAPtrm5srmO8s7h4Z"
            "oXDxSxOVZGByGBHIIPOa+1v2Tf8Agtz+0F8FLa28IfHDT/8AhYGgwgIl3dXPlarbp04nIInx1xKC"
            "x6eYBXxNRXl5rkuV53Q9jjaSmul916Nar5M9PK85zPJq/tcHVcH1ts/VPR/NH7tfAr/gqp+xJ8eI"
            "YYNN+L9r4c1KUDOkeL8afKrHookcmFyewSRj7V9CWGoWGq2ceo6XfQ3NvMu6Ge3lDo6+oYcEfSv5"
            "oa6DwP8AFj4pfDK4N38N/iVr/h+UtuMmiaxPaMT65iZa/L8x8IMHUk5YLEuHlJc34rlf4M/S8v8A"
            "FnF04qONw6l5xfL+DuvxR/SJRX4IeHf+Cmn7enheNYtM/ae8SShRwdRkivD+JnRyfxroU/4LAf8A"
            "BReOPyl/aMfGOreFtJJ/M2ua+dn4RZ+n7lek15ua/wDbGfQw8WMha9+jVT8lF/8At6P3OoJAGScA"
            "dSa/BzXP+CqH/BQHxBGY7/8AaX1iMEYJsbK0tT+cMKkV5h4+/aJ+P3xUjaD4l/G3xZr8T9YNX8Q3"
            "NxH9AjuVA9gK6MP4QZrKX7/Ewiv7qlL81E58R4tZXFfuMPOT/vOMfy5j90/jN+3v+x/8A4pl+I/x"
            "60CK7hyH0rTrr7beBv7pgt97rnplgB718UftI/8ABf2aeK48Pfsr/CxoSQUTxJ4swWHbdHaxsRnu"
            "GeQ+6dq/NGivtcp8LuHsvkp4jmrSX82kf/AV+TbR8dmvibn+Pi4Ye1GL/l1l/wCBP9Ema3jvxx4o"
            "+JnjTVfiH421Q32sa3qEt7qd4YkTzp5HLu+1AFXLEnAAA7Csmiiv0eEIU4KMVZLRJdEfnc5yqScp"
            "O7erfcKKKKokKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooA"
            "KKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAo"
            "oooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigD/2Q=="
        ),
    },
    "tyson": {
        "filename": "tyson.jpg",
        "data": (
            "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAIBAQEBAQIBAQECAgICAgQDAgICAgUEBAMEBgUGBgYF"
            "BgYGBwkIBgcJBwYGCAsICQoKCgoKBggLDAsKDAkKCgr/2wBDAQICAgICAgUDAwUKBwYHCgoKCgoK"
            "CgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgr/wAARCAEAAQADASIA"
            "AhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQA"
            "AAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3"
            "ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWm"
            "p6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEA"
            "AwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSEx"
            "BhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElK"
            "U1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3"
            "uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD8x6KK"
            "KACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
            "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigA"
            "ooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACi"
            "iigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKK"
            "KACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoooo"
            "AKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigA"
            "ooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACv"
            "pX9kr/gln+0F+2V8Lpfi38MPGHg2w02HVptOaDXtQu4pzLGkbsQIraRduJFwd2eDx6/NVfsb/wAE"
            "HP8Akya+/wCx8v8A/wBJ7Wvxnx343z3w/wCA3muUSiq3tYQ96PMrS5r6fI+h4Yy3C5rmfsK9+Xlb"
            "0dtrHyt/w4C/bH/6KV8M/wDwc6h/8g0f8OAv2x/+ilfDP/wc6h/8g1+vlFfxX/xNT4tf8/aP/gpf"
            "5n6L/qRkX8sv/Aj8g/8AhwF+2P8A9FK+Gf8A4OdQ/wDkGj/hwF+2P/0Ur4Z/+DnUP/kGv18oo/4m"
            "p8Wv+ftH/wAFL/MP9SMi/ll/4EfkH/w4C/bH/wCilfDP/wAHOof/ACDR/wAOAv2x/wDopXwz/wDB"
            "zqH/AMg1+vlFH/E1Pi1/z9o/+Cl/mH+pGRfyy/8AAj8g/wDhwF+2P/0Ur4Z/+DnUP/kGj/hwF+2P"
            "/wBFK+Gf/g51D/5Br9fKKP8Aianxa/5+0f8AwUv8w/1IyL+WX/gR+Qf/AA4C/bH/AOilfDP/AMHO"
            "of8AyDR/w4C/bH/6KV8M/wDwc6h/8g1+vlFH/E1Pi1/z9o/+Cl/mH+pGRfyy/wDAj8g/+HAX7Y//"
            "AEUr4Z/+DnUP/kGj/hwF+2P/ANFK+Gf/AIOdQ/8AkGv18oo/4mp8Wv8An7R/8FL/ADD/AFIyL+WX"
            "/gR+KXx//wCCN/7Tn7OPwe1z42eN/HXgO60rQLdJry30rU717h1aVIwEWS0RScuOrDjP0r5Mr93v"
            "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"
            "iP8A7AN5/wCiXrdrC+KX/JMvEf8A2Abz/wBEvXz+A/36l/ij+aOur/Cl6M/m8ooor/b0/m4KKKKA"
            "CiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKAP3s/4Jnf8mG/"
            "DH/sW1/9GSV7pX4NfDP/AIKd/tx/B3wFpfwx+HHxv/s7Q9Gthb6bY/8ACNaZN5MeSdu+W2Z25J5Z"
            "ia3f+Hw3/BRn/o4n/wAtHSP/AJEr/P3ib6KXiHnPEmNzChisKoVqtSpFSnWulOcpJO1Bq9nrZtX6"
            "s/U8FxxlOHwdOlKE7xik7KPRJfzH7kVhfFL/AJJl4j/7AN5/6JevxU/4fDf8FGf+jif/AC0dI/8A"
            "kSoNV/4K5/8ABQvWtMudG1P9oLzba7geG4j/AOET0ld6MpVhkWgIyCeRzXl4X6IviTRxMKksXhLR"
            "af8AErdHf/nwbz49yeUGlTqa+Uf/AJI+bqKKK/0WPyUKKKKACiiigAooooAKKKKACiiigAooooAK"
            "KKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoo"
            "ooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiii"
            "gAooooAKKKKACiiigD//2Q=="
        ),
    },
}

TTS_PROFILES = {
    "ventura": {
        "display": "Ventura (PT-PT)",
        "flag": ":flag_pt:",
        "thumbnail_asset": "ventura",
        "provider": "elevenlabs",
        "voice": "pt",
    },
    "costa": {
        "display": "Costa (PT-PT)",
        "flag": ":flag_pt:",
        "thumbnail_asset": "costa",
        "provider": "elevenlabs",
        "voice": "costa",
    },
    "tyson": {
        "display": "Tyson (EN)",
        "flag": ":flag_us:",
        "thumbnail_asset": "tyson",
        "provider": "elevenlabs",
        "voice": "en",
    },
    "en": {
        "display": "English (Google)",
        "flag": ":flag_gb:",
        "provider": "gtts",
        "lang": "en",
    },
    "pt": {
        "display": "Portuguese (PT - Google)",
        "flag": ":flag_pt:",
        "provider": "gtts",
        "lang": "pt",
    },
    "br": {
        "display": "Portuguese (BR - Google)",
        "flag": ":flag_br:",
        "provider": "gtts",
        "lang": "pt",
        "region": "com.br",
    },
    "es": {
        "display": "Spanish",
        "flag": ":flag_es:",
        "provider": "gtts",
        "lang": "es",
    },
    "fr": {
        "display": "French",
        "flag": ":flag_fr:",
        "provider": "gtts",
        "lang": "fr",
    },
    "de": {
        "display": "German",
        "flag": ":flag_de:",
        "provider": "gtts",
        "lang": "de",
    },
    "ru": {
        "display": "Russian",
        "flag": ":flag_ru:",
        "provider": "gtts",
        "lang": "ru",
    },
    "ar": {
        "display": "Arabic",
        "flag": ":flag_sa:",
        "provider": "gtts",
        "lang": "ar",
    },
    "ch": {
        "display": "Chinese (Mandarin)",
        "flag": ":flag_cn:",
        "provider": "gtts",
        "lang": "zh-CN",
    },
    "ir": {
        "display": "Irish English",
        "flag": ":flag_ie:",
        "provider": "gtts",
        "lang": "en",
        "region": "ie",
    },
}

CHARACTER_CHOICES = [choice for choice, profile in TTS_PROFILES.items() if profile.get("provider") == "elevenlabs"]

# Path to the bot's log file for command history
COMMAND_LOG_FILE = '/var/log/personalgreeter.log'


def resolve_profile_thumbnail(profile, user=None):
    """Return a tuple of (thumbnail_url, discord.File or None) for the given profile."""
    asset_key = profile.get("thumbnail_asset")
    if asset_key:
        asset = EMBEDDED_PROFILE_THUMBNAILS.get(asset_key)
        if asset:
            data = asset.get("data", "").replace("\n", "")
            if data:
                try:
                    image_bytes = base64.b64decode(data)
                    buffer = io.BytesIO(image_bytes)
                    buffer.seek(0)
                    filename = asset.get("filename", f"{asset_key}.jpg")
                    return f"attachment://{filename}", discord.File(buffer, filename=filename)
                except Exception:
                    pass

    thumbnail = profile.get("thumbnail")
    if thumbnail:
        if thumbnail.startswith("http"):
            return thumbnail, None

        absolute_path = os.path.join(os.path.dirname(__file__), thumbnail)
        if os.path.exists(absolute_path):
            filename = os.path.basename(absolute_path)
            return f"attachment://{filename}", discord.File(absolute_path, filename=filename)

    if user:
        if user.avatar:
            return user.avatar.url, None
        return user.default_avatar.url, None

    return None, None


def tail_command_logs(lines=10, log_path=COMMAND_LOG_FILE):
    """Return the last `lines` lines from the bot's log file."""
    try:
        output = subprocess.check_output(
            ['tail', '-n', str(lines), log_path],
            stderr=subprocess.STDOUT,
            text=True,
        )
        return output.strip().splitlines()
    except Exception as e:
        print(f"Error reading command log: {e}")
        return None

def get_service_logs(lines=10, service_name=None):
    """Return the last `lines` lines from service logs using journalctl."""
    try:
        # First try to get logs for a specific service if provided
        if service_name:
            output = subprocess.check_output(
                ['journalctl', '-u', service_name, '-n', str(lines), '--no-pager'],
                stderr=subprocess.STDOUT,
                text=True,
            )
            return output.strip().splitlines()
        
        # If no service name, try to get logs for current user or system
        commands_to_try = [
            ['journalctl', '--user', '-n', str(lines), '--no-pager'],  # User logs
            ['journalctl', '-n', str(lines), '--no-pager'],  # System logs
        ]
        
        for cmd in commands_to_try:
            try:
                output = subprocess.check_output(
                    cmd,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                return output.strip().splitlines()
            except subprocess.CalledProcessError:
                continue
                
        # If journalctl fails, try to read from the bot's log file
        if os.path.exists(COMMAND_LOG_FILE):
            return tail_command_logs(lines, COMMAND_LOG_FILE)
        
        return None
        
    except Exception as e:
        print(f"Error reading service logs: {e}")
        return None

# Flag to enable/disable voice recognition
voice_recognition_enabled = True

# Keywords to detect in voice chat
voice_keywords = [ "chapada", "diogo"]

# Initialize speech recognizer
vosk_model_path = os.path.join(os.path.dirname(__file__), "vosk-model-pt/vosk-model-small-pt-0.3")
speech_recognizer = SpeechRecognizer(
    model_path=vosk_model_path,
    keywords=voice_keywords,
    temp_dir=os.path.join(os.path.dirname(__file__), "temp_audio")
)

# Keyword detection callback
async def handle_keyword_detection(guild, voice_channel, member, text, keywords):
    """Handle keyword detection events from the voice listener"""
    try:
        # Special action for "chapada" keyword
        if "chapada" in keywords:
            # Get a random slap sound from the database
            slap_sounds = Database().get_sounds(slap=True)
            if slap_sounds:
                random_slap = random.choice(slap_sounds)
                # Play the sound in the voice channel
                await behavior.play_audio(voice_channel, random_slap[2], member.name, is_entrance=False)
                # Send notification message
                await behavior.send_message(title=f"👋 {member.name} requested slap 👋", delete_time=5, send_controls=False)
                # Log the action
                Database().insert_action(member.name, "voice_activated_slap", random_slap[0])
            else:
                print("No slap sounds found in the database!")
                
        # Action for "black" keyword
        elif "diogo" in keywords:
            await behavior.send_message(title=f"🧑🏿 {member.name} requested black sound 🧑🏿", delete_time=5, send_controls=False)
            # Get top 25 sounds similar to "black"
            similar_sounds = Database().get_sounds_by_similarity_optimized("nigga", 25)
            if similar_sounds:
                # Choose one randomly
                chosen_sound = random.choice(similar_sounds)
                sound_id = chosen_sound[0]
                sound_filename = chosen_sound[1] # Assuming index 1 is filename based on play_request
                
                # Play the sound
                await behavior.play_audio(voice_channel, sound_filename, member.name, is_entrance=False)
                # Send notification message
                # Log the action
                Database().insert_action(member.name, "voice_activated_black", sound_id)
            else:
                print("No sounds similar to 'black' found in the database!")
                await behavior.send_message(title=f"Couldn't find sounds similar to 'black' for {member.name}", delete_time=10, send_controls=False)
                
    except Exception as e:
        print(f"Error handling keyword detection: {e}")

# Initialize voice listener
voice_listener = DiscordVoiceListener(bot, speech_recognizer, handle_keyword_detection)

# Initialize Minecraft log monitor
minecraft_monitor = MinecraftLogMonitor(bot, "minecraft")

# --- Background Task to Handle Web Playback Requests ---
@tasks.loop(seconds=5.0)
async def check_playback_queue():
    """Process queued playback requests from the web interface."""
    conn = None
    try:
        conn = sqlite3.connect(db.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id, guild_id, sound_filename
            FROM playback_queue
            WHERE played_at IS NULL
            ORDER BY requested_at ASC
        """
        )
        pending_requests = cursor.fetchall()

        if not pending_requests:
            return

        print(f"[Playback Queue] Found {len(pending_requests)} pending requests.")

        for request in pending_requests:
            req_id = request["id"]
            guild_id = request["guild_id"]
            sound_filename = request["sound_filename"]

            print(
                f"[Playback Queue] Processing request ID {req_id}: Play '{sound_filename}' in guild {guild_id}"
            )

            guild = bot.get_guild(guild_id)
            if not guild:
                print(
                    f"[Playback Queue] Error: Bot is not in guild {guild_id}. Skipping request {req_id}."
                )
                cursor.execute(
                    "UPDATE playback_queue SET played_at = ? WHERE id = ?",
                    (datetime.datetime.now(), req_id),
                )
                conn.commit()
                continue

            sound_data = db.get_sound(sound_filename)
            if not sound_data:
                print(
                    f"[Playback Queue] Error: Sound '{sound_filename}' not found in database. Skipping request {req_id}."
                )
                cursor.execute(
                    "UPDATE playback_queue SET played_at = ? WHERE id = ?",
                    (datetime.datetime.now(), req_id),
                )
                conn.commit()
                continue

            sound_folder = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "Sounds")
            )
            sound_path = os.path.join(sound_folder, sound_filename)

            if not os.path.exists(sound_path):
                print(
                    f"[Playback Queue] Error: Sound file not found at '{sound_path}'. Skipping request {req_id}."
                )
                cursor.execute(
                    "UPDATE playback_queue SET played_at = ? WHERE id = ?",
                    (datetime.datetime.now(), req_id),
                )
                conn.commit()
                continue

            try:
                channel = behavior.get_largest_voice_channel(guild)
                if channel is not None:
                    await behavior.play_audio(channel, sound_filename, "webpage")
                    Database().insert_action("admin", "play_sound_periodically", sound_filename)

                cursor.execute(
                    "UPDATE playback_queue SET played_at = ? WHERE id = ?",
                    (datetime.datetime.now(), req_id),
                )
                conn.commit()

                await asyncio.sleep(1)

            except Exception as e:
                print(f"[Playback Queue] Error playing sound for request {req_id}: {e}")
                cursor.execute(
                    "UPDATE playback_queue SET played_at = ? WHERE id = ?",
                    (datetime.datetime.now(), req_id),
                )
                conn.commit()
    except sqlite3.Error as db_err:
        print(f"[Playback Queue] Database error: {db_err}")
    except Exception as e:
        print(f"[Playback Queue] Unexpected error in background task: {e}")
    finally:
        if conn:
            conn.close()


@default_permissions(manage_messages=True)
@bot.event
async def on_ready():
    print(f"We have logged in as {bot.user}")
    # Debug: print voice stack versions (opus / sodium) to help diagnose decode errors
    try:
        import discord.opus as _opus
        v = _opus._OpusStruct.get_opus_version()
        print(f"Opus loaded: {_opus.is_loaded()} - version: {v}")
    except Exception as e:
        print(f"Opus not loaded or version unknown: {e}")
    try:
        import nacl, nacl.bindings
        sv = getattr(nacl.bindings, 'sodium_version_string', lambda: b'unknown')()
        print(f"PyNaCl: {getattr(nacl, '__version__', 'unknown')} - libsodium: {sv.decode() if isinstance(sv, (bytes, bytearray)) else sv}")
    except Exception as e:
        print(f"PyNaCl/libsodium check failed: {e}")
    #bot.loop.create_task(behavior.check_if_in_game())
    await behavior.delete_controls_message()
    await behavior.clean_buttons()
    await behavior.send_controls(force=True)
    
    
    bot.loop.create_task(behavior.play_sound_periodically())
    bot.loop.create_task(behavior.update_bot_status())
    bot.loop.create_task(SoundDownloader(behavior, behavior.db, os.getenv("CHROMEDRIVER_PATH")).move_sounds())
    check_playback_queue.start()
    #bot.loop.create_task(voice_listener.listen_to_voice_channels())  # Start voice recognition
    
    # Start Minecraft log monitoring
    if minecraft_monitor.start_monitoring():
        print("Minecraft log monitoring started successfully")
        # Test channel access and send initial message
       # await minecraft_monitor.test_channel_access()
    else:
        print("Failed to start Minecraft log monitoring - check if /opt/minecraft/logs exists")

    # --- Auto-join most populated voice channel --- 
    print("Attempting to join the most populated voice channel in each guild...")
    for guild in bot.guilds:
        print(f"Checking guild: {guild.name} ({guild.id})")
        channel_to_join = behavior.get_largest_voice_channel(guild)
        
        if channel_to_join:
            print(f"Found most populated channel in {guild.name}: {channel_to_join.name} ({len(channel_to_join.members)} members)")
            try:
                # Disconnect if already connected in this guild
                if guild.voice_client and guild.voice_client.is_connected():
                    print(f"Disconnecting from current channel in {guild.name}...")
                    await behavior.send_message(title=f"Disconnecting from current channel in {guild.name}...", send_controls=False)
                    await guild.voice_client.disconnect(force=True)
                    await asyncio.sleep(1) # Short delay after disconnecting

                # Attempt to connect
                print(f"Attempting to connect to {channel_to_join.name} in {guild.name}...")
                await channel_to_join.connect()
                print(f"Successfully connected to {channel_to_join.name} in {guild.name}.")
                try:
                    vc = guild.voice_client
                    if vc is not None:
                        print(f"Voice encryption mode: {getattr(vc, 'mode', 'unknown')}")
                except Exception as e:
                    print(f"Could not read voice mode: {e}")
                if not bot.startup_sound_played:
                    try:
                        random_sound = Database().get_random_sounds()[0][2]
                        await behavior.play_audio(channel_to_join, random_sound, "startup")
                    except Exception as e:
                        print(f"Error playing startup sound: {e}")
                    bot.startup_sound_played = True
            except discord.ClientException as e:
                print(f"Error connecting to {channel_to_join.name} in {guild.name}: {e}. Already connected elsewhere or connection issue.")
            except asyncio.TimeoutError:
                print(f"Timeout trying to connect to {channel_to_join.name} in {guild.name}.")
            except Exception as e:
                print(f"An unexpected error occurred while trying to connect to {channel_to_join.name} in {guild.name}: {e}")
        else:
            print(f"No suitable voice channel found in {guild.name} (or all are empty).")
    print("Finished auto-join process.")
    # --- End Auto-join ---

@bot.slash_command(name="voicerecognition", description="Enable or disable real-time voice conversation logging")
async def voice_recognition_cmd(ctx, enabled: Option(bool, "Enable or disable voice recognition", required=True)):
    global voice_recognition_enabled
    
    # Check if user has admin permission
    if not behavior.is_admin_or_mod(ctx.author):
        await ctx.respond("You don't have permission to use this command.", ephemeral=True)
        return
    
    voice_recognition_enabled = enabled
    voice_listener.set_enabled(enabled)
    
    if enabled:
        await ctx.respond("Real-time voice conversation logging has been **enabled**. The bot will now print conversations it hears to the console.", ephemeral=False)
        print("Voice recognition ENABLED by", ctx.author.name)
    else:
        await ctx.respond("Real-time voice conversation logging has been **disabled**.", ephemeral=False)
        print("Voice recognition DISABLED by", ctx.author.name)
    
    Database().insert_action(ctx.author.name, "voice_recognition", "enabled" if enabled else "disabled")

@bot.slash_command(name="keywords", description="Manage keywords for voice recognition")
async def manage_keywords(ctx, 
                         action: Option(str, "Action to perform", choices=["add", "remove", "list"], required=True),
                         keyword: Option(str, "Keyword to add or remove", required=False)):
    global voice_keywords, speech_recognizer
    
    # Check if user has admin permission
    if not behavior.is_admin_or_mod(ctx.author):
        await ctx.respond("You don't have permission to use this command.", ephemeral=True)
        return
                                
    if action == "list":
        if not voice_keywords:
            await ctx.respond("No keywords are currently being monitored.", ephemeral=False)
        else:
            formatted_keywords = ", ".join(f"`{kw}`" for kw in voice_keywords)
            await ctx.respond(f"**Currently monitoring these keywords:**\n{formatted_keywords}", ephemeral=False)
    
    elif action == "add" and keyword:
        if keyword.lower() in [k.lower() for k in voice_keywords]:
            await ctx.respond(f"Keyword `{keyword}` is already being monitored.", ephemeral=False)
        else:
            voice_keywords.append(keyword.lower())
            # Update the speech recognizer with the new keywords
            speech_recognizer.keywords = voice_keywords
            await ctx.respond(f"Added keyword `{keyword}` to monitoring list.", ephemeral=False)
            print(f"Keyword '{keyword}' added by {ctx.author.name}")
    
    elif action == "remove" and keyword:
        # Case insensitive removal
        lower_keywords = [k.lower() for k in voice_keywords]
        if keyword.lower() in lower_keywords:
            index = lower_keywords.index(keyword.lower())
            removed = voice_keywords.pop(index)
            # Update the speech recognizer with the updated keywords
            speech_recognizer.keywords = voice_keywords
            await ctx.respond(f"Removed keyword `{removed}` from monitoring list.", ephemeral=False)
            print(f"Keyword '{removed}' removed by {ctx.author.name}")
        else:
            await ctx.respond(f"Keyword `{keyword}` is not in the monitoring list.", ephemeral=False)
    
    else:
        await ctx.respond("Please provide a valid keyword to add or remove.", ephemeral=True)
    
    Database().insert_action(ctx.author.name, f"keyword_{action}", keyword if keyword else "list")

async def get_sound_autocomplete(ctx):
    try:
        # Get the current input value and return immediately if too short
        current = ctx.value.lower() if ctx.value else ""
        if not current or len(current) < 2:
            return []
        
        # Benchmark the query time
        start_time = time.time()
        similar_sounds = Database().get_sounds_by_similarity_optimized(current, 15)
        end_time = time.time()
        query_time = end_time - start_time
        print(f"get_sounds_by_similarity took {query_time:.3f} seconds for query: '{current}'")
        
        # Quick process and return
        return [sound[2].split('/')[-1].replace('.mp3', '') for sound in similar_sounds]
    except Exception as e:
        print(f"Autocomplete error: {e}")
        return []

async def get_list_autocomplete(ctx):
    try:
        # Get the current input value
        current = ctx.value.lower() if ctx.value else ""
        
        # Get all lists
        all_lists = db.get_sound_lists()
        
        # If no input, return all lists (up to 25)
        if not current:
            return [list_name for _, list_name, _, _, _ in all_lists][:25]
        
        # Filter lists based on input
        matching_lists = []
        for list_id, list_name, creator, created_at, sound_count in all_lists:
            if current in list_name.lower():
                # Format as "list_name"
                matching_lists.append(f"{list_name}")
        
        # Sort by relevance (exact matches first, then starts with, then contains)
        exact_matches = [name for name in matching_lists if name.lower() == current]
        starts_with = [name for name in matching_lists if name.lower().startswith(current) and name.lower() != current]
        contains = [name for name in matching_lists if current in name.lower() and not name.lower().startswith(current) and name.lower() != current]
        
        # Combine and limit to 25 results
        sorted_results = exact_matches + starts_with + contains
        return sorted_results[:25]
    except Exception as e:
        print(f"List autocomplete error: {e}")
        return []

@bot.slash_command(name="toca", description="Write a name of something you want to hear")
@discord.option(
    "message",
    description="Sound name ('random' for random)",
    autocomplete=get_sound_autocomplete,
    required=True
)
@discord.option(
    "speed",
    description="Playback speed multiplier (e.g., 1.5 for faster, 0.8 for slower). Default: 1.0",
    required=False,
    type=float, # Specify type for better validation
    default=1.0
)
@discord.option(
    "volume",
    description="Volume multiplier (e.g., 1.5 for 150%, 0.5 for 50%). Default: 1.0",
    required=False,
    type=float, # Specify type for better validation
    default=1.0 # Default multiplier is 1.0 (no change)
)
@discord.option(
    "reverse",
    description="Play the sound in reverse? (True/False). Default: False",
    required=False,
    type=bool, # Specify type for better validation
    default=False
)
async def play_requested(ctx, message: str, speed: float = 1.0, volume: float = 1.0, reverse: bool = False):
    await ctx.respond("Processing your request...", delete_after=0)

    # --- Input Validation/Clamping ---
    try:
        # Clamp speed to a reasonable range (e.g., 0.5x to 3.0x)
        speed = max(0.5, min(speed, 3.0))
        # Clamp volume multiplier (e.g., 0.1x to 5.0x)
        volume = max(0.1, min(volume, 5.0))
        # --------------------------------

        author = ctx.user
        username_with_discriminator = f"{author.name}#{author.discriminator}"

        effects = {
            "speed": speed,
            "volume": volume, # Now a multiplier
            "reverse": reverse
        }

        print(f"Playing '{message}' for {username_with_discriminator} with effects: {effects}")
        try:
            if message == "random":
                # Note: Applying effects to random sounds might need adjustments in play_random_sound
                # For now, let's pass effects=None or handle it inside play_random_sound
                asyncio.run_coroutine_threadsafe(behavior.play_random_sound(username_with_discriminator, effects=effects), bot.loop)
            else:
                # Pass the effects dictionary to play_request
                await behavior.play_request(message, author.name, effects=effects)
        except Exception as e:
            print(f"Error in play_requested: {e}")
            # Fallback to random sound without effects on error? Or just report error?
            # Let's just report the error for now.
            await ctx.followup.send(f"An error occurred while trying to play '{message}'. Please try again later.", ephemeral=True, delete_after=10)
            # asyncio.run_coroutine_threadsafe(behavior.play_random_sound(username_with_discriminator), bot.loop) # Optional fallback
            return
    except Exception as e:
        print(f"Error in play_requested: {e}")
        await ctx.followup.send(f"An error occurred while processing your request. Please try again later.", ephemeral=True, delete_after=10)
        return
    
@bot.slash_command(name='tts', description='Generate TTS with Google or ElevenLabs voices.')
async def tts(ctx, message: Option(str, "What you want to say", required=True), language: Option(str, "Select a voice or language", choices=list(TTS_PROFILES.keys()), required=True)):
    await ctx.respond("Processing your request...", delete_after=0)
    profile = TTS_PROFILES.get(language, TTS_PROFILES["en"])
    flag = profile.get("flag", ":speech_balloon:")
    user = discord.utils.get(bot.get_all_members(), name=ctx.user.name)

    behavior.color = discord.Color.dark_blue()
    thumbnail_url, thumbnail_file = resolve_profile_thumbnail(profile, user)

    await behavior.send_message(
        title=f"TTS • {profile.get('display', language.title())} {flag}",
        description=f"'{message}'",
        thumbnail=thumbnail_url,
        file=thumbnail_file,
    )
    try:
        if profile.get("provider") == "elevenlabs":
            await behavior.tts_EL(user, message, profile.get("voice", "en"))
        else:
            lang = profile.get("lang", "en")
            region = profile.get("region", "")
            await behavior.tts(user, message, lang, region)
    except Exception as e:
        await behavior.send_message(title=e)
        return
    
@bot.slash_command(name='sts', description='Speech-To-Speech. Press tab and enter to select message and write')
async def tts(ctx, sound: Option(str, "Base sound you want to convert", required=True), char: Option(str, "Voice to convert into", choices=CHARACTER_CHOICES, required=True)):
    await ctx.respond("Processing your request...", delete_after=0)

    user = discord.utils.get(bot.get_all_members(), name=ctx.user.name)

    behavior.color = discord.Color.dark_blue()
    profile = TTS_PROFILES.get(char, TTS_PROFILES["tyson"])
    thumbnail_url, thumbnail_file = resolve_profile_thumbnail(profile, user)

    await behavior.send_message(
        title=f"{sound} to {profile.get('display', char.title())}",
        description=f"'{profile.get('display', char.title())}'",
        thumbnail=thumbnail_url,
        file=thumbnail_file,
    )
    try:
        await behavior.sts_EL(user, sound, char)
    except Exception as e:
        await behavior.send_message(title=e)
        return
    
@bot.slash_command(name='isolate', description='Isolate voice from a sound.')
async def isolate(ctx, sound: Option(str, "Base sound you want to isolate", required=True)):
    await ctx.respond("Processing your request...", delete_after=0)

    user = discord.utils.get(bot.get_all_members(), name=ctx.user.name)

    behavior.color = discord.Color.dark_blue()

    try:
        await behavior.isolate_voice(user, sound)
    except Exception as e:
        await behavior.send_message(title=e)
        return

@bot.slash_command(name="change", description="change the name of a sound")
async def change(ctx, current: Option(str, "Current name of the sound", required=True), new: Option(str, "New name of the sound", required=True)):
    await ctx.respond("Processing your request...", delete_after=0)
    await behavior.change_filename(current, new, ctx.user)

@bot.slash_command(name="top", description="Leaderboard of sounds or users")
async def change(ctx, option: Option(str, "users or sounds", required=True), number: Option(str, "number of users", default=5), numberdays: Option(str, "number of days", default=7)):
    await ctx.respond("Processing your request...", delete_after=0)
    if option == "sounds":
        await behavior.player_history_db.write_top_played_sounds(daysFrom=numberdays)
    else:
        await behavior.player_history_db.write_top_users(int(number),daysFrom=numberdays)

@bot.slash_command(name="list", description="returns database of sounds")
async def change(ctx):
    await ctx.respond("Processing your request...", delete_after=0)
    await behavior.list_sounds(ctx.user)    

@bot.slash_command(name="subwaysurfers", description="returns database of sounds")
async def change(ctx):
    await ctx.respond("Processing your request...", delete_after=0)
    await behavior.subway_surfers()    

@bot.slash_command(name="familyguy", description="returns database of sounds")
async def change(ctx):
    await ctx.respond("Processing your request...", delete_after=0)
    await behavior.family_guy()

@bot.slash_command(name="slice", description="returns database of sounds")
async def change(ctx):
    await behavior.slice_all(ctx)

@bot.slash_command(name="lastsounds", description="returns last sounds downloaded")
async def change(ctx, number: Option(str, "number of sounds", default=10)):
    await behavior.list_sounds(ctx, int(number))

# @bot.slash_command(name="userlolstats", description="get your lol stats", channel_ids=["1321095299367833723"])
# async def userlolstats(ctx, username: Option(str, "username", required=True), gamemode: Option(str, "ARAM, CHERRY, CLASSIC, NEXUSBLITZ, ONEFORALL, STRAWBERRY, ULTBOOK, URF", required=True), champion: Option(str, "champion (ignore if you want all)", required=False)):
#     await ctx.respond("Processing your request...", delete_after=0)
#     await behavior.userlolstats(username, gamemode, champion)

# @bot.slash_command(name="user_vs_userlolstats", description="get your lol stats vs another user", channel_ids=["1321095299367833723"])
# async def user_vs_userlolstats(ctx, username1: Option(str, "username1", required=True), username2: Option(str, "username2", required=True), gamemode: Option(str, "ARAM, CHERRY, CLASSIC, NEXUSBLITZ, ONEFORALL, STRAWBERRY, ULTBOOK, URF", required=True), champion: Option(str, "champion name", required=True)):
#     await ctx.respond("Processing your request...", delete_after=0)
#     await behavior.user_vs_userlolstats(username1, username2, gamemode, champion)

# @bot.slash_command(name="loltime", description="get this servers users lol time played this year(ish)", channel_ids=["1321095299367833723"])
# async def loltime(ctx):
#     await ctx.respond("Processing your request...", delete_after=0)
#     await behavior.userloltime()

# @bot.slash_command(name="lolfriends", description="stats of your friends in league of legends when you play with them", channel_ids=["1321095299367833723"])
# async def lolfriends(ctx, username: Option(str, "username", required=True)):
#     await ctx.respond("Processing your request...", delete_after=0)
#     await behavior.userlolfriends(username)

# @bot.slash_command(name="addloluser", description="username#tagline", channel_ids=["1321095299367833723"])
# async def addloluser(ctx, username: Option(str, "username", required=True)):
#     await ctx.respond("Processing your request...", delete_after=0)
#     await behavior.insertLoLUser(username)

# @bot.slash_command(name="refreshgames", description="refresh games")
# async def refreshgames(ctx):
#     await ctx.respond("Processing your request...", delete_after=0)
#     await behavior.refreshgames()

@bot.slash_command(name="addevent", description="Add a join/leave event sound for a user")
async def add_event(ctx, 
    username: Option(str, "Select a user", choices=db.get_all_users(), required=True),
    event: Option(str, "Event type", choices=["join", "leave"], required=True),
    sound: Option(str, "Sound name to play", required=True)):
    
    await ctx.respond("Processing your request...", delete_after=0)
    success = await behavior.add_user_event(username, event, sound)
    if success:
        await ctx.followup.send(f"Successfully added {sound} as {event} sound for {username}!", ephemeral=True, delete_after=5)
    else:
        await ctx.followup.send("Failed to add event sound. Make sure the username and sound are correct!", ephemeral=True, delete_after=5)

@bot.slash_command(name="listevents", description="List your join/leave event sounds")
async def list_events(ctx, 
    username: Option(str, "User to list events for (defaults to you)", choices=db.get_all_users(), required=False)):
    await ctx.respond("Processing your request...", delete_after=0)
    
    if username:
        target_user = username
        target_user_full = username  # Since the database already stores the full username
    else:
        target_user = ctx.user.name
        target_user_full = f"{ctx.user.name}#{ctx.user.discriminator}"
    
    if not await behavior.list_user_events(target_user, target_user_full, requesting_user=ctx.user.name):
        await ctx.followup.send(f"No event sounds found for {target_user}!", ephemeral=True)

# Sound List Commands
@bot.slash_command(name="createlist", description="Create a new sound list")
async def create_list(ctx, list_name: Option(str, "Name for your sound list", required=True)):
    # Check if the user already has a list with this name
    existing_list = db.get_list_by_name(list_name, ctx.author.name)
    if existing_list:
        await ctx.respond(f"You already have a list named '{list_name}'.", ephemeral=True)
        return
        
    # Create the list
    list_id = db.create_sound_list(list_name, ctx.author.name)
    if list_id:
        await ctx.respond(f"Created list '{list_name}'.", ephemeral=True)
        
        # Send a message confirming the creation
        await behavior.send_message(
            title="List Created",
            description=f"Created a new sound list: '{list_name}'\nAdd sounds with `/addtolist`."
        )
    else:
        await ctx.respond("Failed to create list.", ephemeral=True)

@bot.slash_command(name="addtolist", description="Add a sound to a sound list")
async def add_to_list(
    ctx, 
    sound: Option(str, "Sound to add to the list", autocomplete=get_sound_autocomplete, required=True),
    list_name: Option(str, "Name of the list", autocomplete=get_list_autocomplete, required=True)
):
    # Get the list
    sound_list = db.get_list_by_name(list_name)
    if not sound_list:
        await ctx.respond(f"List '{list_name}' not found.", ephemeral=True)
        return
    
    # Get the sound ID
    soundid = db.get_sounds_by_similarity(sound)[0][1]
        
    # Add the sound to the list
    success, message = db.add_sound_to_list(sound_list[0], soundid)
    if success:
        # Get the list creator for the success message
        list_creator = sound_list[2]
        
        # If the user adding the sound is not the creator, include that in the message
        if list_creator != ctx.author.name:
            await ctx.respond(f"Added sound '{sound}' to {list_creator}'s list '{list_name}'.", ephemeral=True)
            
            # Optionally notify in the channel about the addition
            await behavior.send_message(
                title=f"Sound Added to List",
                description=f"{ctx.author.name} added '{sound}' to {list_creator}'s list '{list_name}'."
            )
        else:
            await ctx.respond(f"Added sound '{sound}' to your list '{list_name}'.", ephemeral=True)
    else:
        await ctx.respond(f"Failed to add sound to list: {message}", ephemeral=True)

@bot.slash_command(name="removefromlist", description="Remove a sound from one of your lists")
async def remove_from_list(
    ctx, 
    sound: Option(str, "Sound to remove from the list", required=True),
    list_name: Option(str, "Name of your list", autocomplete=get_list_autocomplete, required=True)
):
    # Get the list
    sound_list = db.get_list_by_name(list_name)
    if not sound_list:
        await ctx.respond(f"List '{list_name}' not found.", ephemeral=True)
        return
    
    # Check if the user is the creator of the list
    if sound_list[2] != ctx.author.name:
        await ctx.respond(f"You don't have permission to modify the list '{list_name}'. Only the creator ({sound_list[2]}) can remove sounds from it.", ephemeral=True)
        return
        
    # Remove the sound from the list
    success = db.remove_sound_from_list(sound_list[0], sound)
    if success:
        await ctx.respond(f"Removed sound '{sound}' from list '{list_name}'.", ephemeral=True)
    else:
        await ctx.respond("Failed to remove sound from list.", ephemeral=True)

@bot.slash_command(name="deletelist", description="Delete one of your sound lists")
async def delete_list(ctx, list_name: Option(str, "Name of your list", autocomplete=get_list_autocomplete, required=True)):
    # Get the list
    sound_list = db.get_list_by_name(list_name)
    if not sound_list:
        await ctx.respond(f"List '{list_name}' not found.", ephemeral=True)
        return
    
    # Check if the user is the creator of the list
    if sound_list[2] != ctx.author.name:
        await ctx.respond(f"You don't have permission to delete the list '{list_name}'. Only the creator ({sound_list[2]}) can delete it.", ephemeral=True)
        return
        
    # Delete the list
    success = db.delete_sound_list(sound_list[0])
    if success:
        await ctx.respond(f"Deleted list '{list_name}'.", ephemeral=True)
        
        # Send a message confirming the deletion
        await behavior.send_message(
            title="List Deleted",
            description=f"The list '{list_name}' has been deleted."
        )
    else:
        await ctx.respond("Failed to delete list.", ephemeral=True)

@bot.slash_command(name="showlist", description="Display a sound list with buttons")
async def show_list(ctx, list_name: Option(str, "Name of the list to display", autocomplete=get_list_autocomplete, required=True)):
    # Get the list
    sound_list = db.get_list_by_name(list_name)
    if not sound_list:
        await ctx.respond(f"List '{list_name}' not found.", ephemeral=True)
        return
        
    list_id = sound_list[0]
    
    # Get the sounds in the list
    sounds = db.get_sounds_in_list(list_id)
    if not sounds:
        await ctx.respond(f"List '{list_name}' is empty.", ephemeral=True)
        return
        
    # Create a paginated view with buttons for each sound
    from Classes.UI import PaginatedSoundListView
    view = PaginatedSoundListView(behavior, list_id, list_name, sounds, ctx.author.name)
    
    # Send a message with the view
    await behavior.send_message(
        title=f"Sound List: {list_name} (Page 1/{len(view.pages)})",
        description=f"Contains {len(sounds)} sounds. Showing sounds 1-{min(8, len(sounds))} of {len(sounds)}",
        view=view
    )
    
    # Remove the redundant confirmation message
    await ctx.respond(delete_after=0)

@bot.slash_command(name="mylists", description="Show your sound lists")
async def my_lists(ctx):
    # Get the user's lists
    lists = db.get_sound_lists(creator=ctx.author.name)
    if not lists:
        await ctx.respond("You don't have any sound lists yet. Create one with `/createlist`.", ephemeral=True)
        return
        
    # Create a view with buttons for each list
    from Classes.UI import UserSoundListsView
    view = UserSoundListsView(behavior, lists, ctx.author.name)
    
    # Send a message with the view
    await behavior.send_message(
        title="Your Sound Lists",
        description=f"You have {len(lists)} sound lists. Click a list to view its sounds.",
        view=view
    )
    
    # Remove the redundant confirmation message
    await ctx.respond(delete_after=0)

@bot.slash_command(name="showlists", description="Show all available sound lists")
async def show_lists(ctx):
    # Get all sound lists
    lists = db.get_sound_lists()
    if not lists:
        await ctx.respond("There are no sound lists available yet. Create one with `/createlist`.", ephemeral=True)
        return
    
    # Create a view with buttons for each list
    from Classes.UI import UserSoundListsView
    view = UserSoundListsView(behavior, lists, None)  # Pass None as creator to indicate showing all lists
    
    # Send a message with the view
    await behavior.send_message(
        title="All Sound Lists",
        description=f"There are {len(lists)} sound lists available. Click a list to view its sounds.",
        view=view
    )
    
    await ctx.respond(delete_after=0)

@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    member_str = f"{member.name}#{member.discriminator}"
    
    if member == bot.user:
        return

    # Determine the event type
    if before.channel is None and after.channel is not None:
        event = "join"
        channel = after.channel
    elif before.channel is not None and after.channel is None:
        event = "leave"
        channel = before.channel
    elif before.channel != after.channel:
        event = "join"
        channel = after.channel
    else:
        return  # No relevant change

    # Handle AFK channel joins
    if event == "join" and channel and channel == channel.guild.afk_channel:
        if before.channel:
            # Treat moving to AFK as leaving the previous channel
            print(
                f"User {member_str} moved to AFK channel {channel}; treating as leave from {before.channel}"
            )
            event = "leave"
            channel = before.channel
        else:
            # Ignore when directly joining the AFK channel
            print(f"Ignoring join event for {member_str} in AFK channel {channel}")
            return
        
    # Log the voice state update
    print(f"Voice state update: {member_str} {event} channel {channel}")

    await play_audio_for_event(member, member_str, event, channel)

async def play_audio_for_event(member, member_str, event, channel):
    try:
        user_events = db.get_user_events(member_str, event)
        if user_events:
            if await behavior.is_channel_empty(channel):
                return
            sound = random.choice(user_events)[2]
            behavior.last_channel[member_str] = channel
            if channel:
                print(f"Playing {sound} for {member_str} on {event}")
                await behavior.play_audio(channel, db.get_sounds_by_similarity(sound)[0][1], member_str)
                db.insert_action(member_str, event, db.get_sounds_by_similarity(sound)[0][0])
        elif event == "join":
            await behavior.play_audio(channel, "gay-echo.mp3", "admin")
            db.insert_action(member_str, event, db.get_sounds_by_similarity("gay-echo.mp3")[0][0])
        elif event == "leave":
            db.insert_action(member_str, event, "-")
            await behavior.is_channel_empty(channel)
    except Exception as e:
        print(f"An error occurred: {e}")

# Add an event handler for bot shutdown
@bot.event
async def on_close():
    print("Bot is closing, cleaning up resources...")
    # Stop voice listeners and shut down the executor
    await voice_listener.stop_all_listeners()
    # Stop Minecraft log monitoring
    if minecraft_monitor.observer and minecraft_monitor.observer.is_alive():
        minecraft_monitor.stop_monitoring()
        print("Minecraft log monitoring stopped")
    check_playback_queue.cancel()
    print("Cleanup complete.")

# --- New DM Video Link Handler ---
@bot.event
async def on_message(message):
    # Ignore messages from the bot itself
    if message.author == bot.user:
        return
    
    # Check if the message is a DM
    if isinstance(message.channel, discord.DMChannel):
        # Refined regex to better match specific video/post URLs, including optional query params/fragments
        url_pattern = re.compile(
            r'(?:'                                             # Start non-capturing group for all patterns
            r'https?://(?:www\.|vm\.)?tiktok\.com/'             # TikTok (www or vm)
            r'(?:@[\w.-]+/video/\d+|[^/?#\s]+/?)'             # Matches /@user/video/id or /shortcode (now ignores ?#)
            r'(?:[?#][^\s]*)?|'                                # Optional query/fragment
            r'https?://(?:www\.)?instagram\.com/'              # Instagram
            r'(?:p|reels|reel|stories)/[\w-]+/?'               # Matches /p/..., /reels/..., /reel/..., /stories/...
            r'(?:[?#][^\s]*)?|'                                # Optional query/fragment
            r'https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)' # YouTube (youtube.com/watch?v= or youtu.be/)
            r'[\w-]+'                                           # Matches the video ID
            r'(?:[?#][^\s]*)?'                                   # Optional query/fragment
            r')(?=\s|$)'                                       # Positive lookahead for space or end of string (instead of word boundary)
        )
        match = url_pattern.search(message.content)

        if match:
            url = match.group(0)
            print(f"Detected video URL in DM from {message.author}: {url}")
            
            # Send processing message
            processing_msg = await message.channel.send("Processing your video... 🤓 This might take a moment.")

            file_path = None  # Initialize file_path to None
            try:
                # Use BotBehavior to download and convert the video
                # Extract potential custom filename or time limit (if user provides them after URL)
                remaining_content = message.content[match.end():].strip()
                time_limit = None
                custom_filename = None

                if remaining_content:
                    # Split the remaining content into parts
                    parts = remaining_content.split(maxsplit=1)
                    
                    # Check if first part is a number (time limit)
                    if len(parts) > 0 and parts[0].isdigit():
                        time_limit = int(parts[0])
                        # If there's more content after the time limit, it's the filename
                        if len(parts) > 1:
                            custom_filename = parts[1].strip()
                    else:
                        # No time limit, everything is the filename
                        custom_filename = remaining_content.strip()

                # Sanitize the custom filename
                if custom_filename:
                    # Remove leading slashes and whitespace
                    custom_filename = custom_filename.lstrip('/ \t')
                    # If stripping leaves an empty string, set to None
                    if not custom_filename:
                        custom_filename = None

                file_path = await behavior.save_sound_from_video(url, custom_filename=custom_filename, time_limit=time_limit)
                if file_path:
                    await processing_msg.edit(content="Check botchannel for your new sound!")

            except ValueError as ve: # Catch specific yt-dlp errors (like duration limit)
                 await processing_msg.edit(content=f"Error: {ve}")
            except Exception as e:
                print(f"Error processing video link in DM: {e}")
                await processing_msg.edit(content="Sorry, an error occurred while processing the video. " + str(e)) # Keep str(e)
            # Note: Don't clean up the file here - SoundDownloader will handle moving it to the Sounds folder

    # Allow other on_message handlers or commands to process the message if needed
    # If you are using commands.Bot, you might need this:
    # await bot.process_commands(message) # Uncomment if you use bot.command decorators

# --- End DM Video Link Handler ---

@bot.slash_command(name="minecraft", description="Control Minecraft server log monitoring")
async def minecraft_logs(ctx, 
                        action: Option(str, "Action to perform", choices=["start", "stop", "status", "test"], required=True),
                        channel: Option(str, "Channel name for monitoring (default: minecraft)", required=False, default="minecraft")):
    """Control Minecraft server log monitoring"""
    global minecraft_monitor
    
    # Check for admin permissions
    if not behavior.is_admin_or_mod(ctx.author):
        await ctx.respond("You don't have permission to use this command.", ephemeral=True)
        return
    
    if action == "start":
        # Stop existing monitor if running
        if minecraft_monitor.observer and minecraft_monitor.observer.is_alive():
            minecraft_monitor.stop_monitoring()
        
        # Create new monitor with specified channel
        minecraft_monitor = MinecraftLogMonitor(bot, channel)
        
        if minecraft_monitor.start_monitoring():
            await ctx.respond(f"✅ Minecraft log monitoring started for channel `#{channel}`")
            # Test channel access
            success = await minecraft_monitor.test_channel_access()
            if not success:
                await ctx.followup.send(f"⚠️ Warning: Could not find or access channel `#{channel}`. Make sure the channel exists and the bot has permissions.")
        else:
            await ctx.respond("❌ Failed to start Minecraft log monitoring. Check if `/opt/minecraft/logs/latest.log` exists.")
    
    elif action == "stop":
        if minecraft_monitor.observer and minecraft_monitor.observer.is_alive():
            minecraft_monitor.stop_monitoring()
            await ctx.respond("✅ Minecraft log monitoring stopped")
        else:
            await ctx.respond("⚠️ Minecraft log monitoring is not currently running")
    
    elif action == "status":
        if minecraft_monitor.observer and minecraft_monitor.observer.is_alive():
            channel_name = minecraft_monitor.channel_name
            log_path = "/opt/minecraft/logs/latest.log"
            log_exists = os.path.exists(log_path)
            
            embed = discord.Embed(
                title="🎮 Minecraft Log Monitor Status",
                color=discord.Color.green(),
                timestamp=datetime.datetime.now()
            )
            embed.add_field(name="Status", value="✅ Running", inline=True)
            embed.add_field(name="Channel", value=f"#{channel_name}", inline=True)
            embed.add_field(name="Log File", value="✅ Exists" if log_exists else "❌ Missing", inline=True)
            
            await ctx.respond(embed=embed)
        else:
            embed = discord.Embed(
                title="🎮 Minecraft Log Monitor Status",
                color=discord.Color.red(),
                timestamp=datetime.datetime.now()
            )
            embed.add_field(name="Status", value="❌ Stopped", inline=True)
            
            await ctx.respond(embed=embed)
    
    elif action == "test":
        if minecraft_monitor.observer and minecraft_monitor.observer.is_alive():
            success = await minecraft_monitor.test_channel_access()
            if success:
                await ctx.respond("✅ Test message sent successfully to minecraft channel")
            else:
                await ctx.respond("❌ Failed to send test message. Check channel permissions.")
        else:
            await ctx.respond("⚠️ Minecraft log monitoring is not running. Start it first with `/minecraft start`")

@bot.slash_command(name="lastlogs", description="Show the last service logs")
async def last_logs(ctx, lines: Option(int, "Number of log lines", required=False, default=10), service: Option(str, "Service name (optional)", required=False)):
    await ctx.respond("Fetching service logs...", delete_after=0)
    
    logs = get_service_logs(lines, service)
    if not logs:
        await ctx.followup.send("No log entries found or unable to access logs.", ephemeral=True)
        return
    
    formatted = "\n".join(logs)
    if len(formatted) > 1900:
        formatted = formatted[-1900:]
    await ctx.followup.send(f"```{formatted}```", ephemeral=True)

@bot.slash_command(name="commands", description="Show recent bot commands from the log")
async def show_commands(ctx, count: Option(int, "Number of entries", required=False, default=10)):
    await ctx.respond("Fetching logs...", delete_after=0)
    lines = tail_command_logs(count)

    if not lines:
        await ctx.followup.send("No command logs found or log file unavailable.", ephemeral=True)
        return

    formatted = "\n".join(lines)
    if len(formatted) > 1900:
        formatted = formatted[-1900:]
    await ctx.followup.send(f"```{formatted}```", ephemeral=True)

@bot.slash_command(name="reboot", description="Reboots the host machine (Admin only).")
async def reboot_command(ctx):
    """Reboots the machine the bot is running on. Requires admin permissions."""
    # Check for admin permissions
    if not behavior.is_admin_or_mod(ctx.author):
        # Use ctx.respond directly for ephemeral permission denial
        await ctx.respond("You don't have permission to use this command.", ephemeral=True)
        return

    # Use behavior.send_message for public confirmation (removed invalid ephemeral argument)
    await behavior.send_message(title="🚨 System Reboot Initiated 🚨", description=f"Rebooting the machine as requested by {ctx.author.mention}...")
    # Still need an initial response to the interaction
    await ctx.respond("Reboot command received...", ephemeral=True, delete_after=1)
    print(f"Reboot initiated by {ctx.author.name} ({ctx.author.id})")

    # Allow Discord to send the message before shutting down
    await asyncio.sleep(2)

    # Determine OS and execute reboot command
    system = platform.system()
    try:
        if system == "Windows":
            os.system("shutdown /r /t 1 /f") # /f forces closing applications, /t 1 gives 1 second delay
        elif system == "Linux" or system == "Darwin": # Darwin is macOS
            # WARNING: Requires passwordless sudo or running as root.
            print("Attempting reboot via 'sudo reboot'...")
            os.system("sudo reboot")
        else:
            # Edit the original interaction response for unsupported OS
            await ctx.edit_original_response(content=f"Reboot command not supported on this operating system ({system}).")
            # Send public error message via behavior.send_message (removed invalid ephemeral argument)
            await behavior.send_message(title="Reboot Failed", description=f"Reboot command not supported on this operating system ({system}).", delete_time=10)
            print(f"Reboot command failed: Unsupported OS ({system})")
            return
        # If the script continues after os.system, the command might have failed silently or is just queued.
        print(f"Reboot command issued successfully for {system}.")

    except Exception as e:
        # Edit the original interaction response for failure
        try:
            await ctx.edit_original_response(content=f"Failed to initiate reboot: {e}")
            # Send public error message via behavior.send_message (removed invalid ephemeral argument)
            await behavior.send_message(title="Reboot Failed", description=f"Failed to initiate reboot: {e}", delete_time=10)
        except discord.NotFound: # Interaction might be gone if reboot was too fast
            pass
        print(f"Error during reboot command execution: {e}")

@bot.slash_command(name="fixvoice", description="Fix voice connection issues by cleaning up all connections (Admin only).")
async def fix_voice_command(ctx):
    """Cleans up all voice connections to fix connection issues. Requires admin permissions."""
    # Check for admin permissions
    if not behavior.is_admin_or_mod(ctx.author):
        await ctx.respond("You don't have permission to use this command.", ephemeral=True)
        return

    await ctx.respond("🔧 Cleaning up voice connections...", ephemeral=False)
    print(f"Voice cleanup initiated by {ctx.author.name} ({ctx.author.id})")

    try:
        # Use the new cleanup method
        await behavior.cleanup_all_voice_connections()
        
        await behavior.send_message(
            title="✅ Voice Cleanup Complete",
            description=f"All voice connections have been cleaned up by {ctx.author.mention}. The bot should now be able to connect properly.",
            delete_time=10
        )
        
        print("Voice cleanup completed successfully")
        
    except Exception as e:
        await behavior.send_message(
            title="❌ Voice Cleanup Failed", 
            description=f"Failed to clean up voice connections: {e}",
            delete_time=10
        )
        print(f"Error during voice cleanup: {e}")

@bot.slash_command(name="backup", description="Backup Discord-Brain-Rot project to USB drive (Admin only)")
async def backup_command(ctx):
    """Backup the entire Discord-Brain-Rot project to USB drive with logging."""
    # Check for admin permissions
    if not behavior.is_admin_or_mod(ctx.author):
        await ctx.respond("You don't have permission to use this command.", ephemeral=True)
        return

    await ctx.respond("🔄 Starting backup process...", ephemeral=False)
    print(f"Backup initiated by {ctx.author.name} ({ctx.author.id})")

    try:
        # Step 1: Check if USB drive is mounted
        usb_path = "/media/usb"
        backup_dir = "/media/usb/brainrotbup"
        source_dir = "/home/gabi/github/Discord-Brain-Rot"

        print(f"DEBUG: USB path: {usb_path}")
        print(f"DEBUG: Backup dir: {backup_dir}")
        print(f"DEBUG: Source dir: {source_dir}")

        # Create empty directory for rsync method if it doesn't exist
        empty_dir = "/tmp/empty_dir"
        if not os.path.exists(empty_dir):
            os.makedirs(empty_dir, exist_ok=True)
            print(f"DEBUG: Created empty dir: {empty_dir}")

        print("DEBUG: Starting Step 1 - USB drive check")
        await behavior.send_message(
            title="📋 Backup Step 1",
            description="Checking USB drive connection...",
            delete_time=5
        )

        if not os.path.exists(usb_path):
            print("DEBUG: USB path does not exist!")
            await behavior.send_message(
                title="❌ Backup Failed",
                description="USB drive not found at /media/usb. Please ensure the USB drive is connected and mounted.",
                delete_time=10
            )
            return

        print("DEBUG: USB path exists, proceeding to Step 2")
        await behavior.send_message(
            title="✅ Step 1 Complete",
            description="USB drive is connected and mounted.",
            delete_time=5
        )

        # Step 2: Clean the backup directory
        print("DEBUG: Starting Step 2 - Directory cleanup")
        await behavior.send_message(
            title="🧹 Backup Step 2",
            description="Cleaning existing backup directory...",
            delete_time=5
        )

        if os.path.exists(backup_dir):
            print(f"DEBUG: Backup directory exists: {backup_dir}")
            try:
                # Show directory size before cleanup
                print("DEBUG: Checking directory size")
                await behavior.send_message(
                    title="📊 Directory Size Check",
                    description="Checking backup directory size...",
                    delete_time=5
                )
                size_result = subprocess.run(['sudo', 'du', '-sh', backup_dir], capture_output=True, text=True, timeout=30)
                print(f"DEBUG: Size check result - Return code: {size_result.returncode}")
                print(f"DEBUG: Size check stdout: {size_result.stdout}")
                print(f"DEBUG: Size check stderr: {size_result.stderr}")
                if size_result.returncode == 0 and size_result.stdout.strip():
                    dir_size = size_result.stdout.split()[0]
                    print(f"DEBUG: Directory size: {dir_size}")
                    await behavior.send_message(
                        title="📊 Directory Size",
                        description=f"Backup directory size: {dir_size} - This may take a while to remove...",
                        delete_time=10
                    )
                else:
                    print("DEBUG: Size check failed or empty output")
                    await behavior.send_message(
                        title="⚠️ Size Check Warning",
                        description="Could not determine directory size, proceeding with cleanup...",
                        delete_time=5
                    )
            except subprocess.TimeoutExpired:
                print("DEBUG: Size check timed out")
                await behavior.send_message(
                    title="⚠️ Size Check Timeout",
                    description="Size check timed out, proceeding with cleanup...",
                    delete_time=5
                )
            except Exception as e:
                print(f"DEBUG: Size check error: {str(e)}")
                await behavior.send_message(
                    title="⚠️ Size Check Error",
                    description=f"Size check failed: {str(e)}, proceeding with cleanup...",
                    delete_time=5
                )

            # Try normal removal first with timeout
            try:
                print("DEBUG: Starting primary cleanup method (rm -rfv)")
                await behavior.send_message(
                    title="🧹 Step 2 Progress",
                    description="Starting directory cleanup (timeout: 5 minutes)...",
                    delete_time=10
                )

                # First check if we can list the directory contents
                print("DEBUG: Checking directory access with ls -la")
                ls_result = subprocess.run(['sudo', 'ls', '-la', backup_dir], capture_output=True, text=True, timeout=30)
                print(f"DEBUG: ls result - Return code: {ls_result.returncode}")
                print(f"DEBUG: ls stdout: {ls_result.stdout}")
                print(f"DEBUG: ls stderr: {ls_result.stderr}")
                if ls_result.returncode != 0:
                    print("DEBUG: Directory access failed")
                    await behavior.send_message(
                        title="⚠️ Directory Access Warning",
                        description="Cannot access directory contents. It may be corrupted or have permission issues.",
                        delete_time=10
                    )

                print("DEBUG: Executing rm -rfv command")
                clean_result = subprocess.run(['sudo', 'rm', '-rfv', backup_dir], capture_output=True, text=True, timeout=300)
                print(f"DEBUG: rm result - Return code: {clean_result.returncode}")
                print(f"DEBUG: rm stdout length: {len(clean_result.stdout) if clean_result.stdout else 0}")
                print(f"DEBUG: rm stderr length: {len(clean_result.stderr) if clean_result.stderr else 0}")
                if clean_result.returncode == 0:
                    await behavior.send_message(
                        title="✅ Step 2 Complete",
                        description="Old backup directory cleaned successfully.",
                        delete_time=5
                    )
                else:
                    # Check if directory still exists after the rm command
                    if not os.path.exists(backup_dir):
                        print("DEBUG: Directory successfully removed despite non-zero exit code")
                        await behavior.send_message(
                            title="✅ Step 2 Complete",
                            description="Old backup directory cleaned (some warnings but successful).",
                            delete_time=5
                        )
                    else:
                        # Directory still exists, but some files may have been removed
                        # Let's check what's left and decide whether to continue or fail
                        print("DEBUG: Directory still exists after rm command")

                        # Get directory size to see if most files were removed
                        try:
                            size_check = subprocess.run(['sudo', 'du', '-sb', backup_dir], capture_output=True, text=True, timeout=30)
                            if size_check.returncode == 0:
                                remaining_size = int(size_check.stdout.split()[0])
                                print(f"DEBUG: Remaining directory size: {remaining_size} bytes")

                                # If less than 100MB remains, consider it mostly cleaned
                                if remaining_size < 100000000:  # 100MB
                                    print("DEBUG: Most files removed, continuing with backup")
                                    await behavior.send_message(
                                        title="⚠️ Partial Cleanup",
                                        description=f"Most files cleaned, but {remaining_size/1000000:.1f}MB remains. Continuing with backup...",
                                        delete_time=10
                                    )
                                    # Continue to Step 3 (create directory)
                                else:
                                    # Too much data remains, try alternative methods
                                    print("DEBUG: Too much data remains, trying alternative cleanup")
                                    raise subprocess.CalledProcessError(clean_result.returncode, clean_result.args, "Too much data remains after cleanup")
                            else:
                                raise subprocess.CalledProcessError(clean_result.returncode, clean_result.args, "Could not determine remaining size")
                        except subprocess.TimeoutExpired:
                            print("DEBUG: Size check timed out, assuming partial cleanup")
                            await behavior.send_message(
                                title="⚠️ Cleanup Check Timeout",
                                description="Could not verify cleanup progress. Continuing with backup...",
                                delete_time=10
                            )
                            # Continue to Step 3
            except subprocess.TimeoutExpired:
                # If normal removal times out, try alternative methods
                print("DEBUG: Primary cleanup timed out, trying alternative methods")
                await behavior.send_message(
                    title="⚠️ Step 2 Timeout",
                    description="Normal cleanup timed out, trying alternative methods...",
                    delete_time=10
                )

                # Method 1: Try find -delete (good for large directories)
                try:
                    print("DEBUG: Starting alternative method 1 (find -delete)")
                    await behavior.send_message(
                        title="🔄 Alternative Method 1",
                        description="Trying find -delete approach...",
                        delete_time=5
                    )
                    alt_clean = subprocess.run(['sudo', 'find', backup_dir, '-delete'], capture_output=True, text=True, timeout=240)
                    print(f"DEBUG: find -delete result - Return code: {alt_clean.returncode}")
                    print(f"DEBUG: find -delete stdout length: {len(alt_clean.stdout) if alt_clean.stdout else 0}")
                    print(f"DEBUG: find -delete stderr length: {len(alt_clean.stderr) if alt_clean.stderr else 0}")
                    if alt_clean.returncode == 0:
                        # Check if directory still exists and remove if empty
                        if os.path.exists(backup_dir):
                            rmdir_result = subprocess.run(['sudo', 'rmdir', backup_dir], capture_output=True, text=True, timeout=30)
                            if rmdir_result.returncode != 0:
                                await behavior.send_message(
                                    title="⚠️ Directory Not Empty",
                                    description="Files removed but directory not empty. This is normal.",
                                    delete_time=10
                                )
                        await behavior.send_message(
                            title="✅ Step 2 Complete",
                            description="Old backup directory cleaned using find -delete method.",
                            delete_time=5
                        )
                        return  # Success, exit the cleanup section
                    else:
                        error_msg = alt_clean.stderr.strip() if alt_clean.stderr else "Find command failed"
                        await behavior.send_message(
                            title="⚠️ Method 1 Failed",
                            description=f"Find -delete failed: {error_msg}",
                            delete_time=10
                        )
                except subprocess.TimeoutExpired:
                    await behavior.send_message(
                        title="⚠️ Method 1 Timeout",
                        description="Find -delete also timed out, trying method 2...",
                        delete_time=10
                    )
                except Exception as e:
                    await behavior.send_message(
                        title="⚠️ Method 1 Failed",
                        description=f"Find -delete failed: {str(e)}",
                        delete_time=10
                    )

                # Method 2: Try rsync with delete (sometimes more reliable)
                try:
                    await behavior.send_message(
                        title="🔄 Alternative Method 2",
                        description="Trying rsync delete approach...",
                        delete_time=5
                    )
                    rsync_clean = subprocess.run(['sudo', 'rsync', '-a', '--delete', '/tmp/empty_dir/', backup_dir], capture_output=True, text=True, timeout=180)
                    if rsync_clean.returncode == 0:
                        await behavior.send_message(
                            title="✅ Step 2 Complete",
                            description="Old backup directory cleaned using rsync method.",
                            delete_time=5
                        )
                        return  # Success
                    else:
                        await behavior.send_message(
                            title="⚠️ Method 2 Failed",
                            description=f"Rsync method failed (exit code: {rsync_clean.returncode})",
                            delete_time=10
                        )
                except subprocess.TimeoutExpired:
                    await behavior.send_message(
                        title="❌ All Methods Failed",
                        description="All cleanup methods timed out. The directory may be too large or have filesystem issues.",
                        delete_time=15
                    )
                    return
                except Exception as e:
                    await behavior.send_message(
                        title="⚠️ Method 2 Failed",
                        description=f"Rsync method failed: {str(e)}",
                        delete_time=10
                    )

                # Method 3: Try chmod + rm as final attempt
                try:
                    print("DEBUG: Starting final method (chmod + rm)")
                    await behavior.send_message(
                        title="🔄 Final Method",
                        description="Trying chmod + rm approach for stubborn files...",
                        delete_time=5
                    )

                    # First try to change permissions on all files
                    chmod_result = subprocess.run(['sudo', 'chmod', '-R', '777', backup_dir], capture_output=True, text=True, timeout=60)
                    print(f"DEBUG: chmod result - Return code: {chmod_result.returncode}")

                    # Then try to remove again
                    final_rm = subprocess.run(['sudo', 'rm', '-rf', backup_dir], capture_output=True, text=True, timeout=180)
                    print(f"DEBUG: final rm result - Return code: {final_rm.returncode}")

                    if final_rm.returncode == 0 or not os.path.exists(backup_dir):
                        await behavior.send_message(
                            title="✅ Step 2 Complete",
                            description="Old backup directory cleaned using final method.",
                            delete_time=5
                        )
                        return  # Success, exit the cleanup section
                    else:
                        await behavior.send_message(
                            title="❌ All Cleanup Methods Failed",
                            description="Could not clean backup directory. Please manually remove /media/usb/brainrotbup and try again.",
                            delete_time=20
                        )
                        return  # Give up
                except Exception as e:
                    await behavior.send_message(
                        title="❌ Final Method Failed",
                        description=f"Final cleanup attempt failed: {str(e)}",
                        delete_time=10
                    )

                # Final failure
                await behavior.send_message(
                    title="❌ Step 2 Failed",
                    description="All cleanup methods failed. You may need to manually remove the directory.",
                    delete_time=15
                )
                return
            except subprocess.CalledProcessError as e:
                error_msg = e.stderr if e.stderr else "Unknown error"
                await behavior.send_message(
                    title="❌ Step 2 Failed",
                    description=f"Failed to clean directory: {error_msg}",
                    delete_time=10
                )
                return
        else:
            await behavior.send_message(
                title="ℹ️ Step 2 Skipped",
                description="No existing backup directory found.",
                delete_time=5
            )

        # Step 3: Create backup directory
        await behavior.send_message(
            title="📁 Backup Step 3",
            description="Creating backup directory...",
            delete_time=5
        )

        mkdir_result = subprocess.run(['sudo', 'mkdir', '-p', backup_dir], capture_output=True, text=True)
        if mkdir_result.returncode == 0:
            await behavior.send_message(
                title="✅ Step 3 Complete",
                description="Backup directory created successfully.",
                delete_time=5
            )
        else:
            await behavior.send_message(
                title="❌ Step 3 Failed",
                description=f"Failed to create directory: {mkdir_result.stderr}",
                delete_time=10
            )
            return

        # Step 4: Copy files with progress logging
        await behavior.send_message(
            title="📂 Backup Step 4",
            description="Copying Discord-Brain-Rot project files... This may take a while.",
            delete_time=10
        )

        # Get source directory size for progress estimation
        size_result = subprocess.run(['du', '-sh', source_dir], capture_output=True, text=True)
        if size_result.returncode == 0:
            source_size = size_result.stdout.split()[0]
            await behavior.send_message(
                title="📊 Backup Info",
                description=f"Source directory size: {source_size}",
                delete_time=5
            )

        # Perform the copy operation using rsync (better for special characters and large files)
        print("DEBUG: Starting file copy with rsync")
        await behavior.send_message(
            title="📂 Step 4 Progress",
            description="Copying files using rsync (better for special characters and large files)...",
            delete_time=10
        )

        # Use rsync instead of cp - it's better for:
        # - Special characters in filenames
        # - Large files
        # - Resuming interrupted transfers
        # - Excluding problematic files
        rsync_cmd = [
            'sudo', 'rsync', '-av',
            '--ignore-existing',  # Skip files that already exist
            '--safe-links',       # Ignore symlinks that point outside the tree
            '--copy-links',       # Copy symlinks as regular files
            '--exclude=.git',
            '--exclude=__pycache__',
            '--exclude=*.pyc',
            '--exclude=venv',     # Exclude Python virtual environment
            '--exclude=actions-runner',  # Exclude GitHub actions runner
            '--exclude=temp_audio',      # Exclude temporary audio files
            '--exclude=.DS_Store',       # Exclude macOS system files
            '--exclude=Thumbs.db',       # Exclude Windows system files
            source_dir + '/',
            os.path.join(backup_dir, "Discord-Brain-Rot")
        ]

        print(f"DEBUG: Running rsync command: {' '.join(rsync_cmd)}")
        await behavior.send_message(
            title="📂 Copy Progress",
            description="Starting file copy (this may take several minutes for large backups)...",
            delete_time=30
        )
        copy_result = subprocess.run(rsync_cmd, capture_output=True, text=True, timeout=1800)  # 30 minute timeout

        print(f"DEBUG: rsync result - Return code: {copy_result.returncode}")
        print(f"DEBUG: rsync stdout length: {len(copy_result.stdout) if copy_result.stdout else 0}")
        print(f"DEBUG: rsync stderr length: {len(copy_result.stderr) if copy_result.stderr else 0}")

        if copy_result.returncode != 0:
            # Check if it's a partial success (rsync returns 23 for some files failing but others succeeding)
            if copy_result.returncode == 23:
                print("DEBUG: rsync completed with some files skipped (exit code 23) - this is usually OK")
                await behavior.send_message(
                    title="⚠️ Copy Completed with Warnings",
                    description="Some files had issues (special characters, symlinks) but most were copied successfully.",
                    delete_time=15
                )
            else:
                error_msg = copy_result.stderr.strip() if copy_result.stderr else "Unknown copy error"
                print(f"DEBUG: Copy failed with error: {error_msg}")
                await behavior.send_message(
                    title="❌ Copy Failed",
                    description=f"Failed to copy files: {error_msg[:500]}",
                    delete_time=15
                )
                return

        # Step 5: Verify backup
        await behavior.send_message(
            title="🔍 Backup Step 5",
            description="Verifying backup integrity...",
            delete_time=5
        )

        if os.path.exists(os.path.join(backup_dir, "Discord-Brain-Rot")):
            # Get backup size
            backup_size_result = subprocess.run(['du', '-sh', backup_dir], capture_output=True, text=True)
            if backup_size_result.returncode == 0:
                backup_size = backup_size_result.stdout.split()[0]
                await behavior.send_message(
                    title="✅ Backup Complete",
                    description=f"Backup created successfully!\n📦 Backup size: {backup_size}\n📍 Location: {backup_dir}",
                    delete_time=15
                )
            else:
                await behavior.send_message(
                    title="✅ Backup Complete",
                    description=f"Backup created successfully!\n📍 Location: {backup_dir}",
                    delete_time=10
                )
        else:
            raise Exception("Backup verification failed - directory not found")

        print("Backup completed successfully")

    except Exception as e:
        await behavior.send_message(
            title="❌ Backup Failed",
            description=f"Backup failed with error: {e}",
            delete_time=15
        )
        print(f"Error during backup: {e}")

bot.run_bot()
