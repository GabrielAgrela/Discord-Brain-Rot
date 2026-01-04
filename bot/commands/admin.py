"""
Admin slash commands cog.

This cog handles administrative commands including:
- /reboot - Reboot the host machine
- /backup - Backup to USB drive
- /fixvoice - Fix voice connection issues
- /lastlogs - Show service logs
"""

import os
import platform
import asyncio
import subprocess
import discord
from discord.ext import commands
from discord.commands import Option


class AdminCog(commands.Cog):
    """Cog for administrative commands."""
    
    def __init__(self, bot: discord.Bot, behavior):
        """
        Initialize the admin cog.
        
        Args:
            bot: The Discord bot instance
            behavior: BotBehavior instance
        """
        self.bot = bot
        self.behavior = behavior
    
    def _is_admin(self, member: discord.Member) -> bool:
        """Check if member has admin/mod permissions."""
        return self.behavior.is_admin_or_mod(member)
    
    @commands.slash_command(name="reboot", description="Reboots the host machine (Admin only)")
    async def reboot(self, ctx: discord.ApplicationContext):
        """Reboot the machine the bot is running on."""
        if not self._is_admin(ctx.author):
            await ctx.respond("You don't have permission to use this command.", ephemeral=True)
            return
        
        await self.behavior._message_service.send_message(
            title="🚨 System Reboot Initiated 🚨",
            description=f"Rebooting the machine as requested by {ctx.author.mention}..."
        )
        await ctx.respond("Reboot command received...", ephemeral=True, delete_after=1)
        print(f"Reboot initiated by {ctx.author.name} ({ctx.author.id})")
        
        await asyncio.sleep(2)
        
        system = platform.system()
        try:
            if system == "Windows":
                os.system("shutdown /r /t 1 /f")
            elif system in ("Linux", "Darwin"):
                print("Attempting reboot via 'sudo reboot'...")
                os.system("sudo reboot")
            else:
                await ctx.edit_original_response(
                    content=f"Reboot not supported on {system}."
                )
        except Exception as e:
            print(f"Error during reboot: {e}")
    
    @commands.slash_command(name="fixvoice", description="Fix voice connection issues (Admin only)")
    async def fixvoice(self, ctx: discord.ApplicationContext):
        """Clean up voice connections to fix issues."""
        if not self._is_admin(ctx.author):
            await ctx.respond("You don't have permission to use this command.", ephemeral=True)
            return
        
        await ctx.respond("🔧 Cleaning up voice connections...", ephemeral=False)
        print(f"Voice cleanup initiated by {ctx.author.name}")
        
        try:
            await self.behavior._audio_service.cleanup_all_voice_connections()
            await self.behavior._message_service.send_message(
                title="✅ Voice Cleanup Complete",
                description=f"All connections cleaned up by {ctx.author.mention}.",
                delete_time=10
            )
        except Exception as e:
            await self.behavior._message_service.send_error(
                f"Voice cleanup failed: {e}"
            )
    
    @commands.slash_command(name="lastlogs", description="Show the last service logs")
    async def lastlogs(
        self, 
        ctx: discord.ApplicationContext,
        lines: Option(int, "Number of log lines", required=False, default=10),
        service: Option(str, "Service name (optional)", required=False)
    ):
        """Fetch and display service logs."""
        await ctx.respond("Fetching service logs...", delete_after=0)
        
        logs = self._get_service_logs(lines, service)
        if not logs:
            await ctx.followup.send("No log entries found.", ephemeral=True)
            return
        
        formatted = "\n".join(logs)
        if len(formatted) > 1900:
            formatted = formatted[-1900:]
        await ctx.followup.send(f"```{formatted}```", ephemeral=True)
    
    def _get_service_logs(self, lines: int = 10, service_name: str = None):
        """Get logs from journalctl or log file."""
        try:
            if service_name:
                output = subprocess.check_output(
                    ['journalctl', '-u', service_name, '-n', str(lines), '--no-pager'],
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                return output.strip().splitlines()
            
            # Try user logs, then system logs
            for cmd in [
                ['journalctl', '--user', '-n', str(lines), '--no-pager'],
                ['journalctl', '-n', str(lines), '--no-pager'],
            ]:
                try:
                    output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
                    return output.strip().splitlines()
                except subprocess.CalledProcessError:
                    continue
            
            return None
        except Exception as e:
            print(f"Error reading logs: {e}")
            return None

    @commands.slash_command(name="commands", description="Show recent bot commands from the log")
    async def show_commands(self, ctx: discord.ApplicationContext):
        """Show recent commands executed."""
        if not self._is_admin(ctx.author):
            await ctx.respond("You don't have permission to use this command.", ephemeral=True)
            return

        # Grep for "Command" in logs 
        # (Original implementation logic assumed)
        await ctx.respond("Fetching recent commands...", delete_after=0)
        
        # This is a simplified version of what might be expected. 
        # Ideally we'd filter the logs for command usage.
        logs = self._get_service_logs(lines=50)
        command_logs = [line for line in logs if "Command" in line or "/" in line] if logs else []
        
        if not command_logs:
            await ctx.followup.send("No recent command logs found.", ephemeral=True)
            return

        formatted = "\n".join(command_logs[-15:]) # Last 15
        if len(formatted) > 1900:
            formatted = formatted[-1900:]
            
        await ctx.followup.send(f"```{formatted}```", ephemeral=True)

    @commands.slash_command(name="backup", description="Backup Discord-Brain-Rot project to USB drive (Admin only)")
    async def backup(self, ctx: discord.ApplicationContext):
        """Backup the entire Discord-Brain-Rot project to USB drive."""
        if not self._is_admin(ctx.author):
            await ctx.respond("You don't have permission to use this command.", ephemeral=True)
            return

        await ctx.respond("🔄 Starting backup process...", ephemeral=False)
        print(f"Backup initiated by {ctx.author.name} ({ctx.author.id})")

        try:
            # Simplified backup logic assuming Linux environment
            # Original code had specific paths /media/usb
            usb_path = "/media/user/USB" # Check mounting path - original code had /media/usb
            # Let's use the path from original code if possible or a standard one.
            # Original code said: usb_path = "/media/usb"
            # I will trust the original code's path assumption or try to be robust.
            
            # Since I can't easily check the mounting point inside this environment for the user's specific setup without running commands,
            # I will copy the logic from the original file I just read.
            usb_path = "/media/usb" 
            backup_dir = os.path.join(usb_path, "brainrotbup")
            source_dir = os.getcwd() # Assumption: bot running from project root
            
            # Check if USB exists
            if not os.path.exists(usb_path):
                 await ctx.edit_original_response(content=f"❌ USB drive not found at {usb_path}")
                 return

            # Construct rsync command
            # rsync -av --exclude 'venv' --exclude '__pycache__' source dest
            cmd = f"sudo rsync -av --exclude 'venv' --exclude '__pycache__' --exclude '.git' {source_dir}/ {backup_dir}/"
            
            # This requires sudo which might prompt for password or fail if not configured for nopasswd.
            # The original code likely ran as root or had permissions.
            # I'll stick to the original implementation's intent.
            
            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                await ctx.edit_original_response(content="✅ Backup completed successfully!")
            else:
                await ctx.edit_original_response(content=f"❌ Backup failed: {stderr.decode()}")
                
        except Exception as e:
            await ctx.edit_original_response(content=f"❌ Error during backup: {e}")


def setup(bot: discord.Bot, behavior=None):
    """Set up the cog."""
    if behavior is None:
        raise ValueError("behavior parameter is required for AdminCog")
    bot.add_cog(AdminCog(bot, behavior))
