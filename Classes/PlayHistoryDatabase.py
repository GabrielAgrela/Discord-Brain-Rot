import asyncio
import csv
from collections import Counter
from datetime import datetime
import discord
from collections import Counter
class PlayHistoryDatabase:
    def __init__(self, csv_filename, db, bot, behavior):
        self.csv_filename = csv_filename
        self.db = db
        self.bot = bot
        self.behavior = behavior

    def add_entry(self, filename, username):
        current_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self.csv_filename, mode='a', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            sound_id = self.db.get_id_by_filename(filename)
            # username without discriminator using try catch
            try:
                username = username.split("#")[0]
            except:
                pass
            writer.writerow([sound_id, username, current_datetime])
        print(f"Entry added: Sound ID:{sound_id}, Username: {username}, Datetime: {current_datetime}")

    async def write_top_played_sounds(self):
        bot_channel = discord.utils.get(self.bot.guilds[0].text_channels, name='bot')
        
        with open(self.csv_filename, mode='r', newline='', encoding='utf-8') as file:
            reader = csv.reader(file)
            data = list(reader)

        sound_ids = [row[0] for row in data]
        sound_id_counts = Counter(sound_ids)
        top_sounds = sound_id_counts.most_common(21)
        total_sounds_played = sum(sound_id_counts.values())
        # Calculate average per day
        dates = [datetime.strptime(row[2], "%Y-%m-%d %H:%M:%S") for row in data if row and len(row) > 2 and len(row[2]) == 19]
        if dates:
            first_date = min(dates)
            last_date = max(dates)
            days_passed = (last_date - first_date).days or 1  # Avoid division by zero
            average_per_day = total_sounds_played / days_passed

        embed = discord.Embed(
            title=f"🎵 **A TOTAL OF {total_sounds_played} SOUNDS PLAYED! AVERAGE OF {average_per_day:.0f} A DAY!** 🎵",
            description="Here are the sounds that got everyone moving!",
            color=discord.Color.yellow()
        )
        embed.set_thumbnail(url="https://i.imgflip.com/1vdris.jpg")
        embed.set_footer(text="Updated as of")
        embed.timestamp = datetime.utcnow()
        
        rank = 1
        for sound_id, count in top_sounds:
            filename = self.db.get_filename_by_id(int(sound_id))
            if filename != "tts.mp3":
                emoji = ["🥇", "🥈", "🥉"][rank-1] if rank <= 3 else "🎶"
                embed.add_field(
                    name=f"{rank}. {emoji} `{filename.upper()}`",
                    value=f"Played **{count}** times",
                    inline=False
                )
                rank += 1

        

        
        message = await bot_channel.send(embed=embed)
        await self.behavior.send_controls()
        await asyncio.sleep(30)
        await message.delete()






    async def write_top_users(self, num_users=5):
        bot_channel = discord.utils.get(self.bot.guilds[0].text_channels, name='bot')
        
        # Read data from CSV
        with open(self.csv_filename, mode='r', newline='', encoding='utf-8') as file:
            reader = csv.reader(file)
            next(reader, None)  # skip the headers
            play_data = [row for row in reader]

        # Count occurrences of each username
        user_counts = Counter(row[1] for row in play_data)
        
        # Exclude specific usernames
        excluded_users = ["admin", "periodic function", "tts"]
        filtered_user_counts = {user: count for user, count in user_counts.items() if user not in excluded_users}
        
        # Convert dictionary back to Counter
        filtered_user_counts = Counter(filtered_user_counts)
        
        # Limit to top 5 users
        top_users = [(u, c) for u, c in filtered_user_counts.most_common(num_users)]

        messages = []
        # Create and send an embed for each top user
        for rank, (username, total_plays) in enumerate(top_users, 1):
            # Initialize embed with dynamic elements
            embed = discord.Embed(
                title=f"🔊 **#{rank} {username.replace('#0', '').upper()}**",
                description=f"🎵 **Total Sounds Played: {total_plays}**",
                color=discord.Color.green()
            )

            # Attempt to get user avatar, set a default if unavailable
            user = discord.utils.get(self.bot.get_all_members(), name=username)
            if user and user.avatar:
                embed.set_thumbnail(url=user.avatar.url)
            elif username == "syzoo":
                embed.set_thumbnail(url="https://media.npr.org/assets/img/2017/09/12/macaca_nigra_self-portrait-3e0070aa19a7fe36e802253048411a38f14a79f8-s800-c85.webp")
            elif user:
                embed.set_thumbnail(url=user.default_avatar.url)

            # Add sounds played by the user as fields in the embed
            sounds_played = Counter(row[0] for row in play_data if row[1] == username)  # Count occurrences of each sound played by the user
            for sound_id, count in sounds_played.most_common(10):  # Only get the top 5 sounds
                if sound_id.isdigit():
                    filename = self.db.get_filename_by_id(int(sound_id))
                else:
                    print(f"Invalid sound_id: {sound_id}")
                embed.add_field(name=f"🎶 `{filename}`", value=f"Played **{count}** times", inline=False)

            # Send the embed to the channel
            
            message = await bot_channel.send(embed=embed)
            messages.append(message)

        await self.behavior.send_controls()
        # Wait for 10 seconds
        await asyncio.sleep(120)

        # Delete all messages
        for message in messages:
            await message.delete()

        



