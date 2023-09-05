import asyncio
import os
import discord
from Classes.Environment import Environment
from Classes.Bot import Bot
from Classes.SoundEventsLoader import SoundEventLoader
from Classes.BotBehaviour import BotBehavior

from collections import defaultdict
from datetime import datetime, timedelta

# Dictionary to store the counts for each user
user_scores = defaultdict(int)
# Dictionary to store the timestamps for each command invocation
user_timestamps = defaultdict(list)

intents = discord.Intents(guilds=True, voice_states=True, messages=True, message_content=True)

env = Environment()
bot = Bot(command_prefix="*", intents=intents, token=env.bot_token, ffmpeg_path=env.ffmpeg_path)

loader = SoundEventLoader(os.path.abspath(__file__))
USERS, SOUNDS = loader.load_sound_events()

behavior = BotBehavior(bot, env.ffmpeg_path)

@bot.event
async def on_ready():
    print(f"We have logged in as {bot.user}")
    bot.loop.create_task(behavior.download_sound_periodically())
    bot.loop.create_task(behavior.update_bot_status())
    await behavior.download_sound_and_play()


@bot.command(name='entra')
async def play_random(ctx):
    print("Command triggered")
    asyncio.create_task(behavior.download_sound_and_play())

    print("test2")

@bot.command(name='score')
async def show_scores(ctx):
    bot_channel = discord.utils.get(ctx.guild.text_channels, name='bot')
    if bot_channel is None:
        await ctx.send("The 'bot' channel was not found.")
        return

    end_time = datetime.now()
    print("end time: ", end_time, " type: ", type(end_time))
    start_time = end_time - timedelta(hours=1)
    
    # Dictionary to keep track of scores
    scores = defaultdict(int)
    await ctx.send("Sou uma puta burra, espera uns 3 minutos que vou contar quantas vezes me chamaram...")
    # Loop through each week
    for _ in range(168):  # for 10 weeks
        async for message in bot_channel.history(after=start_time, before=end_time):
            if message.content.startswith("*entra"):
                user_id = message.author.id
                print("user ----------- ", message.author.name, " at ", message.created_at)
                scores[user_id] += 1
        
        # Shift the timeframe by one week
        end_time = start_time
        start_time = end_time - timedelta(hours=1)
        print("start at --------------------------- ",start_time)

    # Convert the user IDs to names and print the results
    scores_text = ""
    for user_id, count in scores.items():
        user = await ctx.guild.fetch_member(user_id)
        if user is not None:
            scores_text += f'{user.name}: {count}\n'

    if scores_text:
        await ctx.send(f"Numero de vezes que chamaram a puta gertrudes esta semana:\n{scores_text}")
    else:
        await ctx.send("No scores to display.")



@bot.event
async def on_voice_state_update(member, before, after):
    
    member_str = str(member)
    print(member_str)
    if member_str in USERS:
        if before.channel is None or (before.channel != after.channel and after.channel is not None):
            event = "join"
            channel = after.channel
        elif after.channel is None or (before.channel != after.channel and before.channel is not None):
            event = "leave"
            channel = before.channel
        else:
            return
        user_events = USERS[member_str]
        for user_event in user_events:
            if user_event.event == event:
                behavior.last_channel[member_str] = channel
                await asyncio.sleep(1)
                if behavior.last_channel[member_str] == channel:
                    for guild in bot.guilds:
                        #await behavior.disconnect_all_bots(guild)
                        if channel:
                            await behavior.play_audio(channel, user_event.sound)
                        break

bot.run_bot()
