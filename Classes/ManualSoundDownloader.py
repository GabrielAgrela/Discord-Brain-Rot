import yt_dlp
from pydub import AudioSegment
import os
import uuid

class ManualSoundDownloader:
    def tiktok_to_mp3(url, output_dir='.', custom_filename=None, time_limit=None):
        # Set up yt-dlp options
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(output_dir, '%(title)s.%(ext)s'),
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        }

        # Download the video and extract audio
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=True)
            title = info_dict.get('title', None)
            
            # Ensure the filename is 30 chars or less
            if len(title) > 30:
                title = title[:27] + '...' + str(uuid.uuid4())[:3]
            
            mp3_filename = f"{title}.mp3"
            mp3_filepath = os.path.join(output_dir, mp3_filename)
        
        # Rename the file to the new truncated name
        original_mp3_filepath = os.path.join(output_dir, f"{info_dict.get('title', None)}.mp3")
        if os.path.exists(original_mp3_filepath):
            os.rename(original_mp3_filepath, mp3_filepath)
        
        # If time_limit is provided, trim the audio
        if time_limit:
            audio = AudioSegment.from_mp3(mp3_filepath)
            trimmed_audio = audio[:time_limit * 1000]  # time_limit is in seconds, pydub uses milliseconds
            trimmed_audio.export(mp3_filepath, format="mp3")
        
        return mp3_filename