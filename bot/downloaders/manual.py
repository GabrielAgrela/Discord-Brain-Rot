"""
Manual sound downloader using yt-dlp.

This module provides functionality to download audio from various
video platforms (YouTube, TikTok, Instagram, etc.) and convert to MP3.
"""

import os
import uuid
import yt_dlp
from pydub import AudioSegment


class ManualSoundDownloader:
    """
    Utility class for downloading audio from video URLs.
    
    Supports various platforms including YouTube, TikTok, and Instagram.
    Audio is automatically converted to MP3 format.
    """
    
    @staticmethod
    def video_to_mp3(url: str, output_dir: str = '.', 
                     custom_filename: str = None, 
                     time_limit: int = None) -> str:
        """
        Download audio from a video URL and convert to MP3.
        
        Args:
            url: Video URL to download audio from.
            output_dir: Directory to save the output file.
            custom_filename: Custom name for the output file (without extension).
            time_limit: Maximum duration in seconds (trims longer audio).
            
        Returns:
            Filename of the saved MP3 file.
            
        Raises:
            ValueError: If YouTube video exceeds 10 minutes.
        """
        # Replace "photo" with "video" in the URL if present (for TikTok)
        if "photo" in url:
            url = url.replace("photo", "video").replace("reels", "p").replace("stories", "p")

        def sanitize_title(title: str) -> str:
            if len(title) > 30:
                return title[:27] + '...' + str(uuid.uuid4())[:3]
            return title

        # Cookie options for authenticated platforms (e.g. Instagram)
        cookies_file = os.path.join(os.path.dirname(__file__), '..', '..', 'Data', 'cookies.txt')
        
        cookie_opts = {}
        if os.path.exists(cookies_file):
            cookie_opts['cookiefile'] = cookies_file

        # Download the video and extract audio
        print(f"[ManualSoundDownloader] Starting download for url='{url}', custom_filename='{custom_filename}'")
        # Use a copy to prevent yt-dlp from mutating our original options dict with defaults
        with yt_dlp.YoutubeDL(cookie_opts.copy()) as ydl:
            try:
                info_dict = ydl.extract_info(url, download=False)
                # print(f"[ManualSoundDownloader] extract_info info_dict keys: {info_dict.keys()}")
            except Exception as e:
                # Fallback for some TikTok URLs that might fail initial extraction
                print(f"[ManualSoundDownloader] extracting info failed: {e}, trying direct download...")
                info_dict = {'title': f'tiktok_audio_{uuid.uuid4().hex[:8]}'}
            
            # Check if it's a YouTube video and its duration
            if 'youtube.com' in url or 'youtu.be' in url:
                duration = info_dict.get('duration', 0)
                if duration > 600:  # 600 seconds = 10 minutes
                    raise ValueError("YouTube video is longer than 10 minutes. Please choose a shorter video.")

            title = sanitize_title(info_dict.get('title', f'audio_{uuid.uuid4().hex[:8]}'))
            print(f"[ManualSoundDownloader] Raw title from yt-dlp: '{info_dict.get('title')}'")
            print(f"[ManualSoundDownloader] Sanitized title: '{title}'")
            
            # Sanitize title OR custom_filename to match filesystem safe characters
            import re
            
            target_name = custom_filename if custom_filename else title
            
            # Keep spaces in filenames; remove unsupported characters.
            safe_name = re.sub(r'[^\w\-. ]+', '', target_name or "")
            safe_name = re.sub(r'\s+', ' ', safe_name).strip(" .")
            
            if not safe_name:
                safe_name = f"audio_{uuid.uuid4().hex[:8]}"
            
            mp3_filename = f"{safe_name}.mp3"
            mp3_filepath = os.path.join(output_dir, mp3_filename)
            print(f"[ManualSoundDownloader] Determined mp3_filepath: '{mp3_filepath}'")

        ydl_opts = {
            'format': 'bestaudio/best',
            **cookie_opts, # Unpack first so we can override any potential defaults if cookie_opts was dirty
            # Force the output template. Using a dict with 'default' is more explicit for recent yt-dlp versions.
            'outtmpl': {'default': mp3_filepath.replace('.mp3', '')},
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'noconfig': True, # Disable loading config files that might override settings
        }

        print(f"[ManualSoundDownloader] FULL ydl_opts: {ydl_opts}")
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            print(f"[ManualSoundDownloader] Calling download...")
            ydl.download([url])

        # If time_limit is provided, trim the audio
        if time_limit:
            audio = AudioSegment.from_mp3(mp3_filepath)
            trimmed_audio = audio[:time_limit * 1000]  # time_limit is in seconds, pydub uses milliseconds
            trimmed_audio.export(mp3_filepath, format="mp3")
        
        if os.path.exists(mp3_filepath):
             print(f"[ManualSoundDownloader] Success! File exists at {mp3_filepath}")
        else:
             print(f"[ManualSoundDownloader] FAILURE! yt-dlp finished but file NOT found at {mp3_filepath}")
             # Print directory listing to see what *was* created
             try:
                 print(f"[ManualSoundDownloader] Contents of {output_dir}: {os.listdir(output_dir)}")
             except:
                 pass
        
        return mp3_filename

    @staticmethod
    def tiktok_to_mp3(url: str, output_dir: str = '.', 
                      custom_filename: str = None, 
                      time_limit: int = None) -> str:
        """
        Download audio from a TikTok URL.
        
        Backwards compatible alias for video_to_mp3.
        
        Args:
            url: TikTok video URL.
            output_dir: Directory to save the output file.
            custom_filename: Custom name for the output file.
            time_limit: Maximum duration in seconds.
            
        Returns:
            Filename of the saved MP3 file.
        """
        return ManualSoundDownloader.video_to_mp3(url, output_dir, custom_filename, time_limit)
