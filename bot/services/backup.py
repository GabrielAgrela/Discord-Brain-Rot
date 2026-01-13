import os
import shutil
import subprocess
import asyncio
import logging
from pathlib import Path
from datetime import datetime
from config import PROJECT_ROOT, BACKUP_DIR, BACKUP_EXCLUSIONS

logger = logging.getLogger(__name__)

class BackupService:
    """
    Service for backing up the bot's data and codebase.
    """
    
    def __init__(self, bot, message_service):
        self.bot = bot
        self.message_service = message_service
        self.backup_dir = BACKUP_DIR
        self.project_root = PROJECT_ROOT
        self.exclusions = BACKUP_EXCLUSIONS

    async def perform_backup(self, interaction):
        """
        Performs a full backup of the project.
        """
        await interaction.response.send_message("🚀 Starting backup process...", ephemeral=True)
        
        try:
            # 1. Create backup directory if it doesn't exist
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            
            # 2. Calculate projected size (rough estimate)
            projected_size_bytes = self._get_dir_size(self.project_root, self.exclusions)
            
            # 3. Check disk space
            total, used, free = shutil.disk_usage(self.backup_dir.parent)
            # Need at least projected_size * 1.2 to be safe
            if free < (projected_size_bytes * 1.2):
                free_gb = free / (1024**3)
                needed_gb = (projected_size_bytes * 1.2) / (1024**3)
                await interaction.followup.send(
                    f"❌ **Backup failed:** Not enough disk space. \n"
                    f"Free: {free_gb:.2f} GB, Needed (approx): {needed_gb:.2f} GB", 
                    ephemeral=True
                )
                return

            # 4. Delete old backups (keep only the last one)
            # Find any .tar.gz files in the backup directory and remove them
            existing_backups = list(self.backup_dir.glob("*.tar.gz"))
            for old_backup in existing_backups:
                try:
                    old_backup.unlink()
                    logger.info(f"Deleted old backup: {old_backup}")
                except Exception as e:
                    logger.error(f"Failed to delete old backup {old_backup}: {e}")

            # 5. Execute tar command
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_filename = f"backup_{timestamp}.tar.gz"
            backup_path = self.backup_dir / backup_filename
            
            exclude_args = []
            for exc in self.exclusions:
                exclude_args.extend(["--exclude", exc])
                
            # Run tar in a separate thread to not block the event loop
            command = ["tar", "-czf", str(backup_path)] + exclude_args + ["-C", str(self.project_root.parent), self.project_root.name]
            
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                size_mb = backup_path.stat().st_size / (1024 * 1024)
                success_msg = f"✅ **Backup successful!** \n`{backup_filename}` created ({size_mb:.2f} MB)."
                await interaction.followup.send(success_msg, ephemeral=True)
                logger.info(f"Backup created successfully: {backup_path}")
            else:
                error_msg = f"❌ **Backup failed:** \n```{stderr.decode()}```"
                await interaction.followup.send(error_msg, ephemeral=True)
                logger.error(f"Backup failed with return code {process.returncode}: {stderr.decode()}")
                
        except Exception as e:
            logger.error(f"Unexpected error during backup: {e}")
            await interaction.followup.send(f"❌ **An unexpected error occurred:** {e}", ephemeral=True)

    def _get_dir_size(self, path, exclusions):
        """Calculate directory size excluding specific folders."""
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(path):
            # Prune excluded directories
            dirnames[:] = [d for d in dirnames if d not in exclusions]
            
            for f in filenames:
                fp = os.path.join(dirpath, f)
                # skip if it is symbolic link
                if not os.path.islink(fp):
                    total_size += os.path.getsize(fp)
        return total_size
