"""
Admin slash commands cog.

This cog handles administrative commands including:
- /reboot - Reboot the host machine
- /lastlogs - Show service logs
- /commands - Show recent bot commands from logs
"""

import os
import sys
import platform
import asyncio
import subprocess
from datetime import datetime
import discord
from discord.ext import commands
from discord.commands import Option
from config import LOGS_DIR


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
    
    @commands.slash_command(name="reboot", description="Restart the bot process (Admin only)")
    async def reboot(self, ctx: discord.ApplicationContext):
        """Restart the bot process."""
        if not self._is_admin(ctx.author):
            await ctx.respond("You don't have permission to use this command.", ephemeral=True)
            return
        
        await self.behavior._message_service.send_message(
            title="🚨 System Reboot Initiated 🚨",
            description=f"Rebooting the host machine as requested by {ctx.author.mention}..."
        )
        await ctx.respond("Rebooting host machine...", ephemeral=True, delete_after=5)
        print(f"Restart initiated by {ctx.author.name} ({ctx.author.id})")
        
        await asyncio.sleep(2)
        
        system = platform.system()
        try:
            # We are running in a container with pid:host and privileged:true
            # so we can use nsenter to escape to the host namespace and run reboot
            print("Attempting host reboot via nsenter...")
            # -t 1: Target PID 1 (systemd/init on host)
            # -m: Mount namespace
            # -u: UTS namespace
            # -n: Network namespace
            # -i: IPC namespace
            # Note: We don't change PID namespace with -p because we want to execute in the context of the target process namespaces
            subprocess.run(["nsenter", "-t", "1", "-m", "-u", "-n", "-i", "reboot"], check=True)
            
        except Exception as e:
            print(f"Error during reboot: {e}")
            await ctx.followup.send(f"Failed to reboot host: {e}", ephemeral=True)
    
    
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
        """Get logs from the current day's log file or journalctl if specified."""
        try:
            if service_name:
                output = subprocess.check_output(
                    ['journalctl', '-u', service_name, '-n', str(lines), '--no-pager'],
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                return output.strip().splitlines()
            
            # Use the new date-based log file
            log_filename = LOGS_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.log"
            
            if os.path.exists(log_filename):
                try:
                    # Use tail command to efficiently get the last N lines
                    output = subprocess.check_output(
                        ['tail', '-n', str(lines), str(log_filename)],
                        stderr=subprocess.STDOUT,
                        text=True
                    )
                    return output.strip().splitlines()
                except subprocess.CalledProcessError:
                    pass

            # Fallback to journalctl if file doesn't exist or error occurs
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

    @commands.slash_command(name="ventura", description="Enable or disable the Ventura AI routine (Admin only)")
    async def ventura(
        self,
        ctx: discord.ApplicationContext,
        state: Option(str, "State", choices=["Enable", "Disable"], required=True)
    ):
        """Toggle the Ventura AI commentary routine."""
        if not self._is_admin(ctx.author):
            await ctx.respond("You don't have permission to use this command.", ephemeral=True)
            return

        enabled = (state == "Enable")
        
        # Access the service via the private attribute in BotBehavior
        if hasattr(self.behavior, '_ai_commentary_service'):
            self.behavior._ai_commentary_service.set_enabled(enabled)
            status_text = "enabled" if enabled else "disabled"
            await ctx.respond(f"✅ Ventura AI routine has been **{status_text}**.", ephemeral=True)
        else:
            await ctx.respond("❌ AI Commentary service not found.", ephemeral=True)

    @commands.slash_command(name="backup", description="Backup the entire project (Admin only)")
    async def backup(self, ctx: discord.ApplicationContext):
        """Backup the project folder."""
        if not self._is_admin(ctx.author):
            await ctx.respond("You don't have permission to use this command.", ephemeral=True)
            return

        await self.behavior.perform_backup(ctx)

    config = discord.SlashCommandGroup("config", "Bot configuration commands (Admin only)")

    @config.command(name="image_cards", description="Enable or disable image sound cards")
    async def config_image_cards(
        self,
        ctx: discord.ApplicationContext,
        state: Option(str, "State", choices=["Enabled", "Disabled"], required=True)
    ):
        """Toggle the use of image cards for sounds."""
        if not self._is_admin(ctx.author):
            await ctx.respond("You don't have permission to use this command.", ephemeral=True)
            return

        enabled = (state == "Enabled")
        self.behavior._audio_service.settings_repo.set_setting('use_image_cards', enabled)
        
        status_text = "enabled" if enabled else "disabled"
        await ctx.respond(f"✅ Image sound cards have been **{status_text}**.", ephemeral=True)



def setup(bot: discord.Bot, behavior=None):
    """Set up the cog."""
    if behavior is None:
        raise ValueError("behavior parameter is required for AdminCog")
    bot.add_cog(AdminCog(bot, behavior))
