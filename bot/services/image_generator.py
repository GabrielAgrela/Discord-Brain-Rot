"""
Service for generating images from HTML templates.

Uses html2image to render HTML to PNG for Discord messages.
"""
import os
import io
import re
import base64
import requests
from typing import Optional, Dict, Any

class ImageGeneratorService:
    """
    Service to generate images from HTML templates.
    
    Used to create visually rich sound cards for Discord messages.
    """
    
    def __init__(self):
        """Initialize the image generator with template path."""
        self.template_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "templates", "sound_card.html")
        )
        self.loading_template_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "templates", "loading_card.html")
        )
        self._hti = None
        self._temp_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "Debug", "sound_cards")
        )
        os.makedirs(self._temp_dir, exist_ok=True)
    
    def _download_image_as_base64(self, url: str) -> Optional[str]:
        """Download an image from a URL and return it as a base64-encoded string.
        
        Args:
            url: The image URL to download
            
        Returns:
            Base64-encoded string or None if download failed
        """
        if not url:
            return None
        try:
            headers = {"User-Agent": "Mozilla/5.0 (compatible; DiscordBot/1.0)"}
            resp = requests.get(url, timeout=5, headers=headers)
            if resp.status_code == 200:
                return base64.b64encode(resp.content).decode('utf-8')
            else:
                print(f"[ImageGeneratorService] Download failed ({resp.status_code}) from {url}")
        except Exception as e:
            print(f"[ImageGeneratorService] Error downloading image from {url}: {e}")
        return None
    
    def _get_hti(self):
        """Lazy-load html2image instance."""
        if self._hti is None:
            try:
                from html2image import Html2Image
                # Use chromium from system (installed in Docker)
                self._hti = Html2Image(
                    output_path=self._temp_dir,
                    custom_flags=[
                        '--no-sandbox',
                        '--disable-gpu',
                        '--disable-dev-shm-usage',
                        '--headless=new',
                        '--default-background-color=00000000',
                        '--hide-scrollbars',
                        '--force-device-scale-factor=1.5'
                    ]
                )
            except ImportError:
                print("[ImageGeneratorService] html2image not installed")
                return None
        return self._hti
    
    def _render_template(self, template_str: str, data: Dict[str, Any]) -> str:
        """Render template using Jinja2."""
        try:
            from jinja2 import Template
            template = Template(template_str)
            return template.render(**data)
        except Exception as e:
            print(f"[ImageGeneratorService] Jinja2 render error: {e}")
            return template_str
    
    async def generate_sound_card(
        self,
        sound_name: str,
        requester: str,
        play_count: Optional[int] = None,
        duration: Optional[str] = None,
        download_date: Optional[str] = None,
        lists: Optional[str] = None,
        favorited_by: Optional[str] = None,
        similarity: Optional[int] = None,
        quote: Optional[str] = None,
        is_tts: bool = False,
        sts_char: Optional[str] = None,
        requester_avatar_url: Optional[str] = None,
        sts_thumbnail_url: Optional[str] = None,
        event_data: Optional[str] = None,
        show_footer: bool = True,
        show_sound_icon: bool = True,
    ) -> Optional[bytes]:
        """
        Async wrapper for generating sound card image in a separate thread.
        This prevents blocking the main event loop during audio playback.
        """
        import asyncio
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            self._generate_sound_card_sync,
            sound_name, requester, play_count, duration, download_date,
            lists, favorited_by, similarity, quote, is_tts, sts_char,
            requester_avatar_url, sts_thumbnail_url, event_data, show_footer, show_sound_icon
        )

    def _generate_sound_card_sync(
        self,
        sound_name: str,
        requester: str,
        play_count: Optional[int] = None,
        duration: Optional[str] = None,
        download_date: Optional[str] = None,
        lists: Optional[str] = None,
        favorited_by: Optional[str] = None,
        similarity: Optional[int] = None,
        quote: Optional[str] = None,
        is_tts: bool = False,
        sts_char: Optional[str] = None,
        requester_avatar_url: Optional[str] = None,
        sts_thumbnail_url: Optional[str] = None,
        event_data: Optional[str] = None,
        show_footer: bool = True,
        show_sound_icon: bool = True,
    ) -> Optional[bytes]:
        """
        Generate a sound card image (Synchronous implementation).
        
        Args:
            sound_name: Name of the sound being played
            requester: Username who requested the sound
            play_count: Number of times this sound has been played
            duration: Duration string (e.g., "0:15")
            download_date: When the sound was added
            lists: Comma-separated list names containing this sound
            favorited_by: Comma-separated usernames who favorited
            similarity: Similarity percentage (for similar sound plays)
            quote: Quote text for TTS/STS modes
            is_tts: Whether this is a TTS message
            sts_char: STS character name (ventura, tyson, costa)
            event_data: String describing events (e.g. "Join: Gabi | Leave: Someone")
            show_footer: Whether to render the footer row
            show_sound_icon: Whether to render the leading sound/speaker icon
            
        Returns:
            PNG image bytes or None if generation failed
        """
        hti = self._get_hti()
        if not hti:
            return None
        
        try:
            # Read template
            with open(self.template_path, 'r', encoding='utf-8') as f:
                template_content = f.read()
            
            import base64

            # Helper to encode SVG to base64
            def encode_svg(svg_data):
                # Ensure we return a clean base64 string
                return base64.b64encode(svg_data.encode('utf-8')).decode('utf-8')
            
            # Download requester avatar and STS thumbnail
            requester_avatar_b64 = self._download_image_as_base64(requester_avatar_url)
            sts_thumbnail_b64 = self._download_image_as_base64(sts_thumbnail_url)

            # Define SVG icons (full SVG content)
            svg_volume = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="#5865F2"><path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/></svg>'
            svg_voice = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="#5865F2"><path d="M9 9c1.66 0 3-1.34 3-3s-1.34-3-3-3-3 1.34-3 3 1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V16h9v-2.5h-2.1c.07-.15.1-.32.1-.5 0-1.83 2.53-3 4-3 .5 0 .97.14 1.4.37l1.52-1.52C14.49 11.23 12.03 11 9 11zm10.77 5.76-2.6-2.63-.88.88 2.62 2.63-2.6 2.63.88.88 2.6-2.62 2.62 2.62.88-.88-2.62-2.63 2.6-2.62-.88-.88z"/></svg>'
            svg_face = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="#5865F2"><path d="M9 11.75c-.69 0-1.25.56-1.25 1.25s.56 1.25 1.25 1.25 1.25-.56 1.25-1.25-.56-1.25-1.25-1.25zm6 0c-.69 0-1.25.56-1.25 1.25s.56 1.25 1.25 1.25 1.25-.56 1.25-1.25-.56-1.25-1.25-1.25zM12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8 0-.29.02-.58.05-.86 2.36-1.05 4.23-2.98 5.21-5.37C11.07 8.33 14.05 10 17.42 10c.78 0 1.53-.09 2.25-.26.21 7.17-5.3 12.26-7.67 12.26z"/></svg>'
            
            # Static icons (Stopwatch, Chart, Calendar, Folder, Heart)
            # Fills are color #5865F2 for primary, #6366f1 for meta
            svg_timer = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="#5865F2"><path d="M15 1H9v2h6V1zm-4 13h2V8h-2v6zm8.03-6.61l1.42-1.42c-.43-.51-.9-.99-1.41-1.41l-1.42 1.42C16.07 4.74 14.12 4 12 4c-4.97 0-9 4.03-9 9s4.02 9 9 9 9-4.03 9-9c0-2.12-.74-4.07-1.97-5.61zM12 20c-3.87 0-7-3.13-7-7s3.13-7 7-7 7 3.13 7 7-3.13 7-7 7z"/></svg>'
            svg_chart = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="#6366f1"><path d="M5 9.2h3V19H5zM10.6 5h2.8v14h-2.8zm5.6 8H19v6h-2.8z"/></svg>'
            svg_calendar = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="#6366f1"><path d="M19 3h-1V1h-2v2H8V1H6v2H5c-1.11 0-1.99.9-1.99 2L3 19c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm0 16H5V8h14v11zM7 10h5v5H7z"/></svg>'
            svg_folder = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="#6366f1"><path d="M10 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z"/></svg>'
            svg_folder = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="#6366f1"><path d="M10 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z"/></svg>'
            svg_heart = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="#6366f1"><path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/></svg>'
            svg_event = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="#6366f1"><path d="M18 16v-5c0-3.07-1.63-5.64-4.5-6.32V4c0-.83-.67-1.5-1.5-1.5s-1.5.67-1.5 1.5v.68C7.64 5.36 6 7.92 6 11v5l-2 2v1h16v-1l-2-2zm-2 0H8v-5c0-2.48 1.51-4.5 4-4.5s4 2.02 4 4.5v5zm-4 5c1.1 0 2-.9 2-2h-4c0 1.1.9 2 2 2z"/></svg>'
            
            # Determine speaker icon (only used when no character thumbnail)
            if not show_sound_icon:
                speaker_icon = None
                card_class = "sts-mode" if (sts_char or is_tts) else ""
            elif sts_char:
                speaker_icon = encode_svg(svg_face)
                card_class = "sts-mode"
            elif is_tts:
                speaker_icon = encode_svg(svg_voice)
                card_class = "sts-mode"
            else:
                speaker_icon = encode_svg(svg_volume)
                card_class = ""
            
            # Clean up sound name for TTS/STS display
            import re
            display_name = sound_name.replace('.mp3', '')
            
            if sts_char or is_tts:
                # Strip date prefix like "11-02-26-14-25-17-" from TTS filenames
                cleaned = re.sub(r'^\d{2}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}-', '', display_name)
                if cleaned:
                    display_name = cleaned
                
                # Build "says: text" format (character photo provides the identity)
                if sts_char or is_tts:
                    if quote:
                        display_name = f"says: {quote}"
                    else:
                        display_name = f"says: {display_name}"
                
                if quote:
                     print(f"[ImageGeneratorService] Generating card with quote length: {len(quote)}")

            
            # Calculate dynamic font size based on name length
            # Default is 26px
            name_len = len(display_name)
            if name_len > 45:
                title_font_size = 16
            elif name_len > 35:
                title_font_size = 18
            elif name_len > 25:
                title_font_size = 22
            else:
                title_font_size = 26

            has_stats = any([
                duration,
                play_count is not None,
                lists,
                favorited_by,
                event_data,
            ])
            has_leading_icon = bool(sts_thumbnail_b64 or speaker_icon)
            notification_only = (not has_stats) and (not show_footer)

            # Build template data with Base64 icons
            data = {
                "sound_name": display_name,
                "title_font_size": title_font_size,
                "requester": requester,
                "speaker_icon": speaker_icon,
                "icon_timer": encode_svg(svg_timer),
                "icon_chart": encode_svg(svg_chart),
                "icon_calendar": encode_svg(svg_calendar),
                "icon_folder": encode_svg(svg_folder),
                "icon_heart": encode_svg(svg_heart),
                "icon_event": encode_svg(svg_event),
                "card_class": card_class,
                "play_count": play_count,
                "duration": duration,
                "download_date": download_date,
                "lists": lists,
                "favorited_by": favorited_by,
                "similarity": similarity,
                "quote": quote,
                "requester_avatar_b64": requester_avatar_b64,
                "sts_thumbnail_b64": sts_thumbnail_b64,
                "event_data": event_data,
                "show_footer": show_footer,
                "has_stats": has_stats,
                "has_leading_icon": has_leading_icon,
                "notification_only": notification_only,
            }
            
            # Render template
            html_content = self._render_template(template_content, data)
            
            return self._screenshot_and_crop(html_content)
            
        except Exception as e:
            print(f"[ImageGeneratorService] Error generating sound card: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _screenshot_and_crop(self, html_content: str) -> Optional[bytes]:
        """Take a screenshot of HTML content, crop to content, and return PNG bytes."""
        hti = self._get_hti()
        if not hti:
            return None
        
        import time
        filename = f"sound_card_{int(time.time() * 1000)}.png"
        
        hti.screenshot(
            html_str=html_content,
            save_as=filename,
            size=(1160, 2000)
        )
        
        image_path = os.path.join(self._temp_dir, filename)
        
        try:
            from PIL import Image
            with Image.open(image_path) as img:
                bbox = img.getbbox()
                if bbox:
                    cropped = img.crop(bbox)
                    # Optimize PNG to reduce file size
                    cropped.save(image_path, optimize=True, quality=85)
        except Exception as e:
            print(f"[ImageGeneratorService] Error cropping image: {e}")
        
        with open(image_path, 'rb') as f:
            image_bytes = f.read()
        
        try:
            os.remove(image_path)
        except:
            pass
        
        return image_bytes
    
    def generate_loading_gif(self) -> Optional[bytes]:
        """Generate (or load cached) animated loading GIF.
        
        Returns:
            GIF image bytes or None if generation failed
        """
        # Cache path
        cache_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "Data", "loading.gif")
        )
        
        # Return cached if exists
        if os.path.exists(cache_path):
            with open(cache_path, 'rb') as f:
                return f.read()

        print("[ImageGeneratorService] Generating loading.gif (one-time process)...")
        hti = self._get_hti()
        if not hti:
            return None
        
        try:
            from PIL import Image
            frames = []
            
            # Base HTML template for frames
            template_content = self._get_loading_html()
            
            # Generate 12 frames (30 degree steps)
            for angle in range(0, 360, 30):
                # Render frame with rotation
                data = {
                    "title": "Processing...",
                    "subtitle": "Generating audio, please wait",
                    "rotation": angle
                }
                html_content = self._render_template(template_content, data)
                
                # Screenshot
                match = re.search(r'width:\s*(\d+)px', html_content)
                width = int(match.group(1)) if match else 580
                
                # Use a unique temp filename for the frame
                import time
                frame_filename = f"frame_{angle}_{int(time.time()*1000)}.png"
                
                hti.screenshot(
                    html_str=html_content,
                    save_as=frame_filename,
                    size=(800, 800) # Use large canvas to avoid clipping, let crop() handle it
                )
                
                frame_path = os.path.join(self._temp_dir, frame_filename)
                
                # Crop and append
                with Image.open(frame_path) as img:
                    bbox = img.getbbox()
                    if bbox:
                        cropped = img.crop(bbox)
                        frames.append(cropped.copy()) # Copy to keep in memory after file close
                
                # Clean up frame file
                try: 
                    os.remove(frame_path)
                except: pass
            
            if not frames:
                return None
                
            # Save GIF
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            frames[0].save(
                cache_path,
                save_all=True,
                append_images=frames[1:],
                optimize=False,
                duration=80, # 80ms per frame ~ 12.5 fps
                loop=0
            )
            
            print(f"[ImageGeneratorService] Saved loading.gif to {cache_path}")
            
            with open(cache_path, 'rb') as f:
                return f.read()
                
        except Exception as e:
            print(f"[ImageGeneratorService] Error generating loading GIF: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _get_loading_html(self) -> str:
        """Return inline HTML for a loading card."""
        return '''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        html, body {
            background: transparent !important;
            width: 800px;
            height: 800px;
            overflow: hidden;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        ::-webkit-scrollbar { display: none; }
        .card {
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #1a1a2e 100%);
            border-radius: 12px;
            padding: 8px;
            border: 2px solid #5865F2;
            width: 150px;
            height: 80px;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 4px;
        }
        .spinner {
            width: 24px; height: 24px;
            border: 3px solid rgba(88, 101, 242, 0.3);
            border-top: 3px solid #5865F2;
            border-radius: 50%;
            transform: rotate({{rotation|default(0)}}deg);
        }
        .title {
            font-size: 12px; font-weight: 700; color: #ffffff;
            font-family: "Inter", sans-serif;
            text-align: center;
            white-space: nowrap;
        }
        .subtitle {
            font-size: 8px; color: #6b7280;
            font-family: "Inter", sans-serif;
            text-align: center;
            white-space: nowrap;
        }
    </style>
</head>
<body>
    <div class="card">
        <div class="spinner"></div>
        <span class="title">{{title}}</span>
        <span class="subtitle">{{subtitle}}</span>
    </div>
</body>
</html>'''
