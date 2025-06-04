import asyncio
import os
import re
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import discord


class MinecraftLogHandler(FileSystemEventHandler):
    def __init__(self, discord_bot, channel_name="minecraft"):
        self.discord_bot = discord_bot
        self.channel_name = channel_name
        self.log_file_path = "/opt/minecraft/logs/latest.log"
        self.last_position = 0
        
        # Store reference to the main event loop
        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError:
            self.loop = None
        
        # Initialize position to end of file to avoid sending old logs
        if os.path.exists(self.log_file_path):
            with open(self.log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                f.seek(0, 2)  # Seek to end
                self.last_position = f.tell()
    
    def on_modified(self, event):
        if event.src_path == self.log_file_path and not event.is_directory:
            # Schedule the coroutine to run in the main event loop
            if self.loop and not self.loop.is_closed():
                asyncio.run_coroutine_threadsafe(self.process_new_logs(), self.loop)
            else:
                print("Warning: No event loop available for processing Minecraft logs")
    
    async def process_new_logs(self):
        """Process new log entries and send them to Discord"""
        try:
            if not os.path.exists(self.log_file_path):
                return
                
            with open(self.log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                f.seek(self.last_position)
                new_lines = f.readlines()
                self.last_position = f.tell()
                
            if not new_lines:
                return
                
            # Find the minecraft channel
            channel = await self.get_minecraft_channel()
            if not channel:
                print(f"Could not find channel '{self.channel_name}'")
                return
                
            # Process each new line
            for line in new_lines:
                line = line.strip()
                if line:
                    await self.send_log_message(channel, line)
                    
        except Exception as e:
            print(f"Error processing Minecraft logs: {e}")
    
    async def get_minecraft_channel(self):
        """Find the minecraft channel in any guild the bot is in"""
        for guild in self.discord_bot.guilds:
            for channel in guild.text_channels:
                if channel.name.lower() == self.channel_name.lower():
                    return channel
        return None
    
    async def send_log_message(self, channel, log_line):
        """Send a formatted log message to Discord"""
        try:
            # Parse the log line for important events
            formatted_message = self.format_log_message(log_line)
            
            if formatted_message:
                # Create an embed for better formatting
                embed = discord.Embed(
                    description=formatted_message,
                    color=self.get_log_color(log_line),
                    timestamp=datetime.now()
                )
                
                await channel.send(embed=embed)
                
        except Exception as e:
            print(f"Error sending log message: {e}")
    
    def format_log_message(self, log_line):
        """Format and filter log messages"""
        # Skip empty lines
        if not log_line.strip():
            return None
        
        # Censor IP addresses before processing
        log_line = self.censor_ip_addresses(log_line)
            
        # Extract timestamp and message parts
        # Minecraft log format: [HH:MM:SS] [Thread/LEVEL]: Message
        timestamp_match = re.match(r'\[(\d{2}:\d{2}:\d{2})\] \[([^\]]+)\]: (.+)', log_line)
        
        if not timestamp_match:
            return f"🔧 `{log_line}`"
            
        timestamp, thread_level, message = timestamp_match.groups()
        
        # Filter important events
        if any(keyword in message.lower() for keyword in [
            'joined the game', 'left the game', 'logged in', 'logged out',
            'achievement', 'advancement', 'death', 'died', 'was slain',
            'fell', 'drowned', 'burned', 'blew up', 'killed'
        ]):
            return f"🎮 **{timestamp}** | {message}"
            
        # Server events
        elif any(keyword in message.lower() for keyword in [
            'starting', 'started', 'stopping', 'stopped', 'loading', 'loaded',
            'saving', 'saved', 'done', 'preparing'
        ]):
            return f"⚙️ **{timestamp}** | {message}"
            
        # Error/Warning messages
        elif any(keyword in thread_level.lower() for keyword in ['warn', 'error', 'fatal']):
            return f"⚠️ **{timestamp}** | {message}"
            
        # Chat messages
        elif '<' in message and '>' in message:
            return f"💬 **{timestamp}** | {message}"
            
        # Skip other less important messages
        return None
    
    def censor_ip_addresses(self, text):
        """Censor IP addresses in the text"""
        # IPv4 pattern: matches xxx.xxx.xxx.xxx where xxx is 0-255
        ipv4_pattern = r'\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b'
        
        # IPv6 pattern: simplified pattern for common IPv6 formats
        ipv6_pattern = r'\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b|\b::1\b|\b(?:[0-9a-fA-F]{1,4}:)*::[0-9a-fA-F]{1,4}\b'
        
        # Replace IPv4 addresses
        text = re.sub(ipv4_pattern, '<ip censored>', text)
        
        # Replace IPv6 addresses
        text = re.sub(ipv6_pattern, '<ip censored>', text)
        
        return text
    
    def get_log_color(self, log_line):
        """Get appropriate color for different log types"""
        if any(keyword in log_line.lower() for keyword in ['error', 'fatal']):
            return discord.Color.red()
        elif any(keyword in log_line.lower() for keyword in ['warn']):
            return discord.Color.orange()
        elif any(keyword in log_line.lower() for keyword in [
            'joined the game', 'logged in', 'achievement', 'advancement'
        ]):
            return discord.Color.green()
        elif any(keyword in log_line.lower() for keyword in [
            'left the game', 'logged out', 'death', 'died'
        ]):
            return discord.Color.dark_gray()
        else:
            return discord.Color.blue()


class MinecraftLogMonitor:
    def __init__(self, discord_bot, channel_name="minecraft"):
        self.discord_bot = discord_bot
        self.channel_name = channel_name
        self.observer = None
        self.handler = None
        
    def start_monitoring(self):
        """Start monitoring the Minecraft log file"""
        try:
            log_dir = "/opt/minecraft/logs"
            
            if not os.path.exists(log_dir):
                print(f"Minecraft logs directory not found: {log_dir}")
                return False
                
            self.handler = MinecraftLogHandler(self.discord_bot, self.channel_name)
            self.observer = Observer()
            self.observer.schedule(self.handler, log_dir, recursive=False)
            self.observer.start()
            
            print(f"Started monitoring Minecraft logs in {log_dir}")
            print(f"Sending updates to Discord channel: #{self.channel_name}")
            return True
            
        except Exception as e:
            print(f"Error starting Minecraft log monitor: {e}")
            return False
    
    def stop_monitoring(self):
        """Stop monitoring the log file"""
        if self.observer:
            self.observer.stop()
            self.observer.join()
            print("Stopped monitoring Minecraft logs")
    
    async def test_channel_access(self):
        """Test if the bot can access the minecraft channel"""
        channel = await self.handler.get_minecraft_channel() if self.handler else None
        if channel:
            try:
                embed = discord.Embed(
                    title="🎮 Minecraft Log Monitor",
                    description="Log monitoring has been started! I'll send updates about your Minecraft server here.",
                    color=discord.Color.green(),
                    timestamp=datetime.now()
                )
                await channel.send(embed=embed)
                return True
            except Exception as e:
                print(f"Error sending test message: {e}")
                return False
        else:
            print(f"Could not find channel '#{self.channel_name}'")
            return False 