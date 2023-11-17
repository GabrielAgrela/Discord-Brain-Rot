import csv
from collections import Counter
from datetime import datetime
import discord
import random
import time

class PlayHistoryDatabase:
    def __init__(self, csv_filename, db, bot):
        self.csv_filename = csv_filename
        self.db = db
        self.bot = bot

    def add_entry(self, filename, username):
        current_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self.csv_filename, mode='a', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            sound_id = self.db.get_id_by_filename(filename)
            writer.writerow([sound_id, username, current_datetime])
        print(f"Entry added: Sound ID:{sound_id}, Username: {username}, Datetime: {current_datetime}")

    async def write_top_played_sounds(self):
        bot_channel = discord.utils.get(self.bot.guilds[0].text_channels, name='bot')
        
        # Read data from CSV
        with open(self.csv_filename, mode='r', newline='', encoding='utf-8') as file:
            reader = csv.reader(file)
            sound_ids = [row[0] for row in reader]
        
        # Count occurrences of each sound ID
        sound_id_counts = Counter(sound_ids)

        # Sort sounds by counts in descending order
        top_sounds = sound_id_counts.most_common(5)
        
        # Create and send an embed for each top sound
        for i, (sound_id, count) in enumerate(top_sounds, 1):
            # Generate a random color
            random_color = discord.Color.from_rgb(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
            
            # Get the filename by sound_id
            filename = self.db.get_filename_by_id(int(sound_id))
            
            # Creating the embed with the random color
            embed = discord.Embed(
                title=f"🎶 **{filename.upper()} PLAYED {count} TIMES** 🎶",
                color=discord.Color.green()
            )
            
            # Adding a field to display the play count
            embed.add_field(name="Play Count:", value=f"{count} times", inline=False)
            
            # Send the embed to the channel
            await bot_channel.send(embed=embed)

    async def write_top_users(self):
        bot_channel = discord.utils.get(self.bot.guilds[0].text_channels, name='bot')
        
        # Read data from CSV
        with open(self.csv_filename, mode='r', newline='', encoding='utf-8') as file:
            reader = csv.reader(file)
            next(reader, None)  # skip the headers
            play_data = [row for row in reader]

        # Count occurrences of each username and each sound per user
        user_counts = Counter(row[1] for row in play_data)
        sound_counts_per_user = {username: Counter() for username in user_counts}

        for sound_id, username, _ in play_data:
            sound_counts_per_user[username][sound_id] += 1

        # Sort users by total play counts in descending order
        top_users = user_counts.most_common()
        # Create and send an embed for each top user
        for i, (username, total_plays) in enumerate(top_users, 1):
            if(username != "admin" and username != "periodic function"):
                # Generate a random color
                random_color = discord.Color.from_rgb(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
                print(username)
                embed = discord.Embed(
                    title=f"🔊 **{username.replace('#0', '').upper()} PLAYED {total_plays} SOUNDS** 🔊",
                    color=discord.Color.dark_blue()
                )

                # Find the discord user by username
                user = discord.utils.get(self.bot.get_all_members(), name=username.split('#')[0], discriminator=username.split('#')[1])
                
                if user and user.avatar:
                    embed.set_thumbnail(url=user.avatar.url)
                elif username.split('#')[0] == "syzoo":
                    embed.set_thumbnail(url="https://media.npr.org/assets/img/2017/09/12/macaca_nigra_self-portrait-3e0070aa19a7fe36e802253048411a38f14a79f8-s800-c85.webp")
                elif user:
                    embed.set_thumbnail(url=user.default_avatar.url)
                    
                
                # Get and sort the sounds played by the user
                top_sounds = sound_counts_per_user[username].most_common()
                for j, (sound_id, count) in enumerate(top_sounds, 1):
                    if count > 2:  # Only include sounds played more than twice
                        filename = self.db.get_filename_by_id(int(sound_id))  # Getting filename by sound_id
                        embed.add_field(name=f"🎶 {filename} - {count} times", value=f"", inline=False)
                
                # Send the embed to the channel
                await bot_channel.send(embed=embed)
