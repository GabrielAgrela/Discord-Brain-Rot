import discord
import os
import re
import asyncio
from bot.database import Database

class UploadSoundModal(discord.ui.Modal):
    def __init__(self, bot_behavior):
        super().__init__(title="Upload Sound")
        self.bot_behavior = bot_behavior
        
        self.url_input = discord.ui.InputText(
            label="URL",
            placeholder="Paste MP3/TikTok/YouTube/Instagram URL here",
            style=discord.InputTextStyle.long,
            min_length=1,
            max_length=500,
            required=True
        )
        self.add_item(self.url_input)
        
        self.custom_name_input = discord.ui.InputText(
            label="Custom Name (Optional)",
            placeholder="Enter a custom name for the sound",
            min_length=0,
            max_length=50,
            required=False
        )
        self.add_item(self.custom_name_input)
        
        self.time_limit_input = discord.ui.InputText(
            label="Time Limit (Optional, for videos)",
            placeholder="Enter time limit in seconds (e.g., 30)",
            min_length=0,
            max_length=3,
            required=False
        )
        self.add_item(self.time_limit_input)
        
    async def callback(self, interaction):
        try:
            if self.bot_behavior.upload_lock.locked():
                await interaction.response.send_message("Another upload is in progress. Wait caralho 😤", ephemeral=True, delete_after=10)
                return
                
            await interaction.response.defer()
            
            async with self.bot_behavior.upload_lock:
                url_content = self.url_input.value.strip()
                custom_filename = self.custom_name_input.value.strip() if self.custom_name_input.value else None
                time_limit = None
                
                if self.time_limit_input.value and self.time_limit_input.value.strip().isdigit():
                    time_limit = int(self.time_limit_input.value.strip())
                
                is_mp3_url = re.match(r'^https?://.*\.mp3$', url_content)
                is_tiktok_url = re.match(r'^https?://.*tiktok\.com/.*$', url_content)
                is_youtube_url = re.match(r'^https?://(www\.)?(youtube\.com|youtu\.be)/.*$', url_content)
                is_instagram_url = re.match(r'^https?://(www\.)?instagram\.com/(p|reels|reel|stories)/.*$', url_content)
                
                if not (is_mp3_url or is_tiktok_url or is_youtube_url or is_instagram_url):
                    await interaction.followup.send("Please provide a valid MP3, TikTok, YouTube, or Instagram URL.", ephemeral=True)
                    return
                
                try:
                    if is_mp3_url:
                        file_path = await self.bot_behavior.save_sound_from_url(url_content, custom_filename)
                    elif is_tiktok_url or is_youtube_url or is_instagram_url:
                        await interaction.followup.send("Downloading video... 🤓", ephemeral=True, delete_after=5)
                        try:
                            print(f"[UploadSoundModal] Calling save_sound_from_video with url='{url_content}', custom_filename='{custom_filename}'")
                            file_path = await self.bot_behavior.save_sound_from_video(url_content, custom_filename, time_limit=time_limit)
                            print(f"[UploadSoundModal] save_sound_from_video returned: '{file_path}'")
                        except ValueError as e:
                            await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)
                            return
                    
                    if not os.path.exists(file_path):
                        print(f"[UploadSoundModal] CRITICAL ERROR: File verification failed. Path '{file_path}' does not exist.")
                        print(f"[UploadSoundModal] Current CWD: {os.getcwd()}")
                        print(f"[UploadSoundModal] File exists check: {os.path.exists(file_path)}")
                        await interaction.followup.send("Upload completed but file verification failed. Please try again.", ephemeral=True)
                        return
                    
                    Database().insert_action(interaction.user.name, "upload_sound", file_path)
                    await interaction.followup.send("Sound uploaded successfully! (may take up to 10s to be available)", ephemeral=True, delete_after=10)
                    
                except Exception as e:
                    print(f"[UploadSoundModal] Exception during upload processing: {e}")
                    import traceback
                    traceback.print_exc()
                    await interaction.followup.send(f"An error occurred during upload: {str(e)}", ephemeral=True)
        except Exception as e:
            print(f"Error in UploadSoundModal.callback: {e}")

class ChangeSoundNameModal(discord.ui.Modal):
    def __init__(self, bot_behavior, sound_name):
        super().__init__(title="Change Sound Name")
        self.bot_behavior = bot_behavior
        self.sound_name = sound_name
        
        self.new_name = discord.ui.InputText(
            label="New Sound Name",
            placeholder=f"Current: {sound_name.replace('.mp3', '') if sound_name.endswith('.mp3') else sound_name}",
            min_length=1,
            max_length=100
        )
        self.add_item(self.new_name)
        
    async def callback(self, interaction):
        try:
            new_name = self.new_name.value
            if new_name:
                await interaction.response.defer(ephemeral=True)
                try:
                    await self.bot_behavior.change_filename(self.sound_name, new_name, interaction.user)
                    await self.bot_behavior.send_message(
                        title="Sound Name Changed",
                        description=f"Successfully changed sound name from **{self.sound_name}** to **{new_name}**!"
                    )
                except Exception as e:
                    await self.bot_behavior.send_message(
                        title="Failed to Change Sound Name",
                        description=f"Could not change sound name from **{self.sound_name}** to **{new_name}**\n\nError: {str(e)}"
                    )
                    await interaction.followup.send("Failed to change sound name. Check the main channel for details.", ephemeral=True)
            else:
                await interaction.response.send_message("Invalid name provided.", ephemeral=True)
        except Exception as e:
            print(f"ChangeSoundNameModal error: {e}")

class CreateListModalWithSoundAdd(discord.ui.Modal):
    def __init__(self, bot_behavior, sound_filename=None):
        super().__init__(title="Create New Sound List")
        self.bot_behavior = bot_behavior
        self.sound_filename = sound_filename
        
        self.list_name = discord.ui.InputText(
            label="List Name",
            placeholder="Enter a name for your sound list",
            min_length=1,
            max_length=100
        )
        self.add_item(self.list_name)
        
    async def callback(self, interaction):
        try:
            list_name = self.list_name.value
            existing_list = Database().get_list_by_name(list_name, interaction.user.name)
            if existing_list:
                await interaction.response.send_message(f"You already have a list named '{list_name}'.", ephemeral=True)
                return
                
            list_id = Database().create_sound_list(list_name, interaction.user.name)
            if list_id:
                success_message = f"Created list '{list_name}'."
                if self.sound_filename:
                    success, message = Database().add_sound_to_list(list_id, self.sound_filename)
                    if success:
                        success_message += f" Sound added to the list."
                    else:
                        success_message += f" However, failed to add sound: {message}"
                
                await interaction.response.send_message(success_message, ephemeral=True)
                asyncio.create_task(self._send_confirmation_message(list_name))
            else:
                await interaction.response.send_message("Failed to create list.", ephemeral=True)
        except Exception as e:
            print(f"CreateListModalWithSoundAdd error: {e}")
    
    async def _send_confirmation_message(self, list_name):
        try:
            await self.bot_behavior.send_message(
                title="List Created",
                description=f"Created a new sound list: '{list_name}'" + (f"\nSound added to the list." if self.sound_filename else "\nAdd sounds with `/addtolist`.") 
            )
        except Exception as e:
            print(f"CreateListModalWithSoundAdd: Error sending confirmation message: {e}")


class UploadSoundWithFileModal(discord.ui.DesignerModal):
    """
    Unified upload modal supporting both URL and direct MP3 file upload.
    
    Pycord 2.7.0 DesignerModal with FileUpload component.
    Users can either:
    - Paste a URL (MP3, TikTok, YouTube, Instagram)
    - Upload an MP3 file directly
    
    Note: DesignerModal requires ALL items to be wrapped in Label.
    """
    
    def __init__(self, bot_behavior):
        super().__init__(title="Upload Sound")
        self.bot_behavior = bot_behavior
        
        # URL input (optional if file is provided) - wrapped in Label for DesignerModal
        self.url_input = discord.ui.InputText(
            placeholder="Paste URL here, OR upload a file below",
            style=discord.InputTextStyle.long,
            min_length=0,
            max_length=500,
            required=False
        )
        self.add_item(discord.ui.Label("URL (MP3/TikTok/YouTube/Instagram)", self.url_input))
        
        # FileUpload component for MP3 files (Pycord 2.7.0+)
        self.file_upload = discord.ui.FileUpload(
            custom_id="mp3_upload",
            required=False,  # Optional - can use URL instead
            min_values=0,
            max_values=1
        )
        self.add_item(discord.ui.Label("Upload MP3 File (or use URL above)", self.file_upload))
        
        # Optional custom name input - wrapped in Label for DesignerModal
        self.custom_name_input = discord.ui.InputText(
            placeholder="Enter a custom name for the sound",
            min_length=0,
            max_length=50,
            required=False
        )
        self.add_item(discord.ui.Label("Custom Name (Optional)", self.custom_name_input))
        
        # Time limit for video downloads - wrapped in Label for DesignerModal
        self.time_limit_input = discord.ui.InputText(
            placeholder="Enter time limit in seconds (e.g., 30)",
            min_length=0,
            max_length=3,
            required=False
        )
        self.add_item(discord.ui.Label("Time Limit (Optional, for videos)", self.time_limit_input))
        
    async def callback(self, interaction: discord.Interaction):
        try:
            if self.bot_behavior.upload_lock.locked():
                await interaction.response.send_message(
                    "Another upload is in progress. Wait caralho 😤", 
                    ephemeral=True, 
                    delete_after=10
                )
                return
            
            url_content = self.url_input.value.strip() if self.url_input.value else ""
            
            # Debug: print file upload state
            print(f"[UploadModal] url_content: '{url_content}'")
            print(f"[UploadModal] file_upload.values: {self.file_upload.values}")
            print(f"[UploadModal] file_upload type: {type(self.file_upload.values)}")
            
            has_file = self.file_upload.values and len(self.file_upload.values) > 0
            print(f"[UploadModal] has_file: {has_file}")
            
            # Validate: must have either URL or file
            if not url_content and not has_file:
                await interaction.response.send_message(
                    "Please provide a URL or upload an MP3 file.", 
                    ephemeral=True
                )
                return
                
            await interaction.response.defer(ephemeral=True)
            
            async with self.bot_behavior.upload_lock:
                custom_filename = self.custom_name_input.value.strip() if self.custom_name_input.value else None
                time_limit = None
                
                if self.time_limit_input.value and self.time_limit_input.value.strip().isdigit():
                    time_limit = int(self.time_limit_input.value.strip())
                
                try:
                    # Priority: file upload first, then URL
                    if has_file:
                        uploaded_file = self.file_upload.values[0]
                        print(f"[UploadModal] Processing file: {uploaded_file}")
                        print(f"[UploadModal] Filename: {uploaded_file.filename}")
                        
                        # Validate file type
                        if not uploaded_file.filename.lower().endswith('.mp3'):
                            print(f"[UploadModal] File validation failed - not mp3")
                            await interaction.followup.send(
                                "Please upload an MP3 file.", 
                                ephemeral=True
                            )
                            return
                        
                        print(f"[UploadModal] File validation passed, calling save_uploaded_sound_secure...")
                        
                        # Save the uploaded file
                        success, result = await self.bot_behavior._sound_service.save_uploaded_sound_secure(
                            uploaded_file, 
                            custom_filename,
                            guild_id=interaction.guild.id if interaction.guild else None,
                            lock_already_held=True,
                        )
                        
                        print(f"[UploadModal] save result: success={success}, result={result}")
                        
                        if not success:
                            await interaction.followup.send(f"Upload failed: {result}", ephemeral=True)
                            return
                        
                        file_path = result
                        print(f"[UploadModal] File saved to: {file_path}")
                    else:
                        # Handle URL
                        is_mp3_url = re.match(r'^https?://.*\.mp3$', url_content)
                        is_tiktok_url = re.match(r'^https?://.*tiktok\.com/.*$', url_content)
                        is_youtube_url = re.match(r'^https?://(www\.)?(youtube\.com|youtu\.be)/.*$', url_content)
                        is_instagram_url = re.match(r'^https?://(www\.)?instagram\.com/(p|reels|reel|stories)/.*$', url_content)
                        
                        if not (is_mp3_url or is_tiktok_url or is_youtube_url or is_instagram_url):
                            await interaction.followup.send(
                                "Please provide a valid MP3, TikTok, YouTube, or Instagram URL.", 
                                ephemeral=True
                            )
                            return
                        
                        if is_mp3_url:
                            file_path = await self.bot_behavior.save_sound_from_url(url_content, custom_filename)
                        else:
                            await interaction.followup.send("Downloading video... 🤓", ephemeral=True, delete_after=5)
                            try:
                                file_path = await self.bot_behavior.save_sound_from_video(
                                    url_content, custom_filename, time_limit=time_limit
                                )
                            except ValueError as e:
                                await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)
                                return
                    
                    if not os.path.exists(file_path):
                        await interaction.followup.send(
                            "Upload completed but file verification failed. Please try again.", 
                            ephemeral=True
                        )
                        return
                    
                    filename = os.path.basename(file_path)
                    Database().insert_action(interaction.user.name, "upload_sound", filename)
                    await interaction.followup.send(
                        f"Sound `{filename}` uploaded successfully! (may take up to 10s to be available)", 
                        ephemeral=True, 
                        delete_after=10
                    )
                    
                except Exception as e:
                    print(f"Upload error details: {e}")
                    await interaction.followup.send(
                        f"An error occurred during upload: {str(e)}", 
                        ephemeral=True
                    )
        except Exception as e:
            print(f"Error in UploadSoundWithFileModal.callback: {e}")

