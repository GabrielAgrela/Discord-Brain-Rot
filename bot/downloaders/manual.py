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
        with yt_dlp.YoutubeDL(cookie_opts) as ydl:
            info_dict = ydl.extract_info(url, download=False)
            
            # Check if it's a YouTube video and its duration
            if 'youtube.com' in url or 'youtu.be' in url:
                duration = info_dict.get('duration', 0)
                if duration > 600:  # 600 seconds = 10 minutes
                    raise ValueError("YouTube video is longer than 10 minutes. Please choose a shorter video.")

            title = sanitize_title(info_dict.get('title', ''))
            mp3_filename = f"{custom_filename}.mp3" if custom_filename else f"{title}.mp3"
            mp3_filepath = os.path.join(output_dir, mp3_filename)

        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': mp3_filepath.replace('.mp3', ''),  # yt-dlp will add .mp3 extension
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            **cookie_opts,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        # If time_limit is provided, trim the audio
        if time_limit:
            audio = AudioSegment.from_mp3(mp3_filepath)
            trimmed_audio = audio[:time_limit * 1000]  # time_limit is in seconds, pydub uses milliseconds
            trimmed_audio.export(mp3_filepath, format="mp3")
        
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
