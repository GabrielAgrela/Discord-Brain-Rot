"""
Service for generating images from HTML templates.

Uses html2image to render HTML to PNG for Discord messages.
"""
import os
import io
import re
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
        self._hti = None
        self._temp_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "Debug", "sound_cards")
        )
        os.makedirs(self._temp_dir, exist_ok=True)
    
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
                        '--force-device-scale-factor=2'
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
    
    def generate_sound_card(
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
        sts_char: Optional[str] = None
    ) -> Optional[bytes]:
        """
        Generate a sound card image.
        
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

            # Define SVG icons (full SVG content)
            svg_volume = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="#8b5cf6"><path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/></svg>'
            svg_voice = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="#8b5cf6"><path d="M9 9c1.66 0 3-1.34 3-3s-1.34-3-3-3-3 1.34-3 3 1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V16h9v-2.5h-2.1c.07-.15.1-.32.1-.5 0-1.83 2.53-3 4-3 .5 0 .97.14 1.4.37l1.52-1.52C14.49 11.23 12.03 11 9 11zm10.77 5.76-2.6-2.63-.88.88 2.62 2.63-2.6 2.63.88.88 2.6-2.62 2.62 2.62.88-.88-2.62-2.63 2.6-2.62-.88-.88z"/></svg>'
            svg_face = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="#8b5cf6"><path d="M9 11.75c-.69 0-1.25.56-1.25 1.25s.56 1.25 1.25 1.25 1.25-.56 1.25-1.25-.56-1.25-1.25-1.25zm6 0c-.69 0-1.25.56-1.25 1.25s.56 1.25 1.25 1.25 1.25-.56 1.25-1.25-.56-1.25-1.25-1.25zM12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8 0-.29.02-.58.05-.86 2.36-1.05 4.23-2.98 5.21-5.37C11.07 8.33 14.05 10 17.42 10c.78 0 1.53-.09 2.25-.26.21 7.17-5.3 12.26-7.67 12.26z"/></svg>'
            
            # Static icons (Stopwatch, Chart, Calendar, Folder, Heart)
            # Fills are color #8b5cf6 for primary, #6366f1 for meta
            svg_timer = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="#8b5cf6"><path d="M15 1H9v2h6V1zm-4 13h2V8h-2v6zm8.03-6.61l1.42-1.42c-.43-.51-.9-.99-1.41-1.41l-1.42 1.42C16.07 4.74 14.12 4 12 4c-4.97 0-9 4.03-9 9s4.02 9 9 9 9-4.03 9-9c0-2.12-.74-4.07-1.97-5.61zM12 20c-3.87 0-7-3.13-7-7s3.13-7 7-7 7 3.13 7 7-3.13 7-7 7z"/></svg>'
            svg_chart = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="#6366f1"><path d="M5 9.2h3V19H5zM10.6 5h2.8v14h-2.8zm5.6 8H19v6h-2.8z"/></svg>'
            svg_calendar = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="#6366f1"><path d="M19 3h-1V1h-2v2H8V1H6v2H5c-1.11 0-1.99.9-1.99 2L3 19c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm0 16H5V8h14v11zM7 10h5v5H7z"/></svg>'
            svg_folder = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="#6366f1"><path d="M10 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z"/></svg>'
            svg_heart = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="#6366f1"><path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/></svg>'
            
            # Determine speaker icon
            if sts_char:
                speaker_icon = encode_svg(svg_face)
                card_class = "sts-mode"
            elif is_tts:
                speaker_icon = encode_svg(svg_voice)
                card_class = "sts-mode"
            else:
                speaker_icon = encode_svg(svg_volume)
                card_class = ""
            
            # Calculate dynamic font size based on name length
            # Default is 26px
            name_len = len(sound_name)
            if name_len > 45:
                title_font_size = 16
            elif name_len > 35:
                title_font_size = 18
            elif name_len > 25:
                title_font_size = 22
            else:
                title_font_size = 26

            # Build template data with Base64 icons
            data = {
                "sound_name": sound_name.replace('.mp3', ''),
                "title_font_size": title_font_size,
                "requester": requester,
                "speaker_icon": speaker_icon,
                "icon_timer": encode_svg(svg_timer),
                "icon_chart": encode_svg(svg_chart),
                "icon_calendar": encode_svg(svg_calendar),
                "icon_folder": encode_svg(svg_folder),
                "icon_heart": encode_svg(svg_heart),
                "card_class": card_class,
                "play_count": play_count,
                "duration": duration,
                "download_date": download_date,
                "lists": lists,
                "favorited_by": favorited_by,
                "similarity": similarity,
                "quote": quote
            }
            
            # Render template
            html_content = self._render_template(template_content, data)
            
            # Generate unique filename
            import time
            filename = f"sound_card_{int(time.time() * 1000)}.png"
            
            # Generate image
            # Screenshot with ample height (580x500 doubled to 1160x1000 for 2x scale)
            hti.screenshot(
                html_str=html_content,
                save_as=filename,
                size=(1160, 1000)
            )
            
            # Read and process the image
            image_path = os.path.join(self._temp_dir, filename)
            
            try:
                # Dynamic Cropping using Pillow
                from PIL import Image
                with Image.open(image_path) as img:
                    # Get bounding box of non-transparent pixels
                    bbox = img.getbbox()
                    if bbox:
                        # Crop to content
                        cropped = img.crop(bbox)
                        # Overwrite the original file with cropped version
                        cropped.save(image_path)
            except Exception as e:
                print(f"[ImageGeneratorService] Error cropping image: {e}")

            # Read the final image bytes
            with open(image_path, 'rb') as f:
                image_bytes = f.read()
            
            # Clean up
            try:
                os.remove(image_path)
            except:
                pass
            
            return image_bytes
            
        except Exception as e:
            print(f"[ImageGeneratorService] Error generating sound card: {e}")
            import traceback
            traceback.print_exc()
            return None
