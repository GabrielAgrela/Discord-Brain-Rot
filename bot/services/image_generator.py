"""
Service for generating images from HTML templates.

Uses html2image to render HTML to PNG for Discord messages.
"""
import base64
import io
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Optional, Tuple

import requests


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

        self._template_content = self._load_template(self.template_path)
        self._jinja_template_class = None
        self._sound_card_template = None

        self._render_lock = threading.Lock()
        self._driver = None
        self._driver_init_attempted = False
        self._request_headers = {"User-Agent": "Mozilla/5.0 (compatible; DiscordBot/1.0)"}
        self._avatar_cache: Dict[str, Tuple[float, str]] = {}
        self._avatar_cache_lock = threading.Lock()
        self._avatar_cache_ttl_seconds = 300
        self._avatar_cache_max_entries = 256
        self._download_pool = ThreadPoolExecutor(max_workers=4)
        self._card_image_scale = 0.75

        self._icons = self._build_encoded_icons()

    def _load_template(self, path: str) -> str:
        """Load template text from disk."""
        with open(path, "r", encoding="utf-8") as template_file:
            return template_file.read()

    def _build_encoded_icons(self) -> Dict[str, str]:
        """Pre-encode static SVG icons once for reuse."""
        svg_map = {
            "volume": '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="#5865F2"><path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/></svg>',
            "voice": '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="#5865F2"><path d="M9 9c1.66 0 3-1.34 3-3s-1.34-3-3-3-3 1.34-3 3 1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V16h9v-2.5h-2.1c.07-.15.1-.32.1-.5 0-1.83 2.53-3 4-3 .5 0 .97.14 1.4.37l1.52-1.52C14.49 11.23 12.03 11 9 11zm10.77 5.76-2.6-2.63-.88.88 2.62 2.63-2.6 2.63.88.88 2.6-2.62 2.62 2.62.88-.88-2.62-2.63 2.6-2.62-.88-.88z"/></svg>',
            "face": '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="#5865F2"><path d="M9 11.75c-.69 0-1.25.56-1.25 1.25s.56 1.25 1.25 1.25 1.25-.56 1.25-1.25-.56-1.25-1.25-1.25zm6 0c-.69 0-1.25.56-1.25 1.25s.56 1.25 1.25 1.25 1.25-.56 1.25-1.25-.56-1.25-1.25-1.25zM12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8 0-.29.02-.58.05-.86 2.36-1.05 4.23-2.98 5.21-5.37C11.07 8.33 14.05 10 17.42 10c.78 0 1.53-.09 2.25-.26.21 7.17-5.3 12.26-7.67 12.26z"/></svg>',
            "timer": '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="#5865F2"><path d="M15 1H9v2h6V1zm-4 13h2V8h-2v6zm8.03-6.61l1.42-1.42c-.43-.51-.9-.99-1.41-1.41l-1.42 1.42C16.07 4.74 14.12 4 12 4c-4.97 0-9 4.03-9 9s4.02 9 9 9 9-4.03 9-9c0-2.12-.74-4.07-1.97-5.61zM12 20c-3.87 0-7-3.13-7-7s3.13-7 7-7 7 3.13 7 7-3.13 7-7 7z"/></svg>',
            "chart": '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="#6366f1"><path d="M5 9.2h3V19H5zM10.6 5h2.8v14h-2.8zm5.6 8H19v6h-2.8z"/></svg>',
            "calendar": '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="#6366f1"><path d="M19 3h-1V1h-2v2H8V1H6v2H5c-1.11 0-1.99.9-1.99 2L3 19c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm0 16H5V8h14v11zM7 10h5v5H7z"/></svg>',
            "folder": '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="#6366f1"><path d="M10 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z"/></svg>',
            "heart": '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="#6366f1"><path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/></svg>',
            "event": '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="#6366f1"><path d="M18 16v-5c0-3.07-1.63-5.64-4.5-6.32V4c0-.83-.67-1.5-1.5-1.5s-1.5.67-1.5 1.5v.68C7.64 5.36 6 7.92 6 11v5l-2 2v1h16v-1l-2-2zm-2 0H8v-5c0-2.48 1.51-4.5 4-4.5s4 2.02 4 4.5v5zm-4 5c1.1 0 2-.9 2-2h-4c0 1.1.9 2 2 2z"/></svg>',
        }
        return {name: self._encode_svg(svg) for name, svg in svg_map.items()}

    def _encode_svg(self, svg_data: str) -> str:
        """Encode SVG text to a base64 string."""
        return base64.b64encode(svg_data.encode("utf-8")).decode("utf-8")

    def _hex_to_rgb(self, color: str) -> str:
        """Convert a hex color string to an ``R, G, B`` string for CSS rgba()."""
        fallback = "88, 101, 242"
        if not color:
            return fallback

        value = color.strip().lstrip("#")
        if len(value) == 3:
            value = "".join(ch * 2 for ch in value)
        if len(value) != 6:
            return fallback

        try:
            red = int(value[0:2], 16)
            green = int(value[2:4], 16)
            blue = int(value[4:6], 16)
            return f"{red}, {green}, {blue}"
        except ValueError:
            return fallback

    def _download_image_as_base64(self, url: str) -> Optional[str]:
        """Download an image from URL and return base64, with short-lived cache."""
        if not url:
            return None

        now = time.time()
        with self._avatar_cache_lock:
            cached = self._avatar_cache.get(url)
            if cached and cached[0] > now:
                return cached[1]
            if cached and cached[0] <= now:
                del self._avatar_cache[url]

        try:
            response = requests.get(
                url,
                timeout=(1.0, 2.0),
                headers=self._request_headers,
            )
            if response.status_code != 200 or not response.content:
                print(f"[ImageGeneratorService] Download failed ({response.status_code}) from {url}")
                return None

            image_b64 = base64.b64encode(response.content).decode("utf-8")
            with self._avatar_cache_lock:
                if len(self._avatar_cache) >= self._avatar_cache_max_entries:
                    oldest_key = next(iter(self._avatar_cache))
                    del self._avatar_cache[oldest_key]
                self._avatar_cache[url] = (now + self._avatar_cache_ttl_seconds, image_b64)
            return image_b64
        except Exception as e:
            print(f"[ImageGeneratorService] Error downloading image from {url}: {e}")
            return None

    def _download_images_parallel(
        self,
        requester_avatar_url: Optional[str],
        sts_thumbnail_url: Optional[str],
    ) -> Tuple[Optional[str], Optional[str]]:
        """Download requester avatar and STS thumbnail concurrently."""
        futures = {}
        if requester_avatar_url:
            futures["requester"] = self._download_pool.submit(
                self._download_image_as_base64,
                requester_avatar_url,
            )
        if sts_thumbnail_url:
            futures["thumbnail"] = self._download_pool.submit(
                self._download_image_as_base64,
                sts_thumbnail_url,
            )

        requester_avatar_b64 = None
        sts_thumbnail_b64 = None

        for key, future in futures.items():
            try:
                if key == "requester":
                    requester_avatar_b64 = future.result()
                else:
                    sts_thumbnail_b64 = future.result()
            except Exception as e:
                print(f"[ImageGeneratorService] Error resolving image future ({key}): {e}")

        return requester_avatar_b64, sts_thumbnail_b64

    def _get_driver(self):
        """Get a persistent Selenium driver for fast repeated screenshots."""
        if self._driver is not None:
            return self._driver
        if self._driver_init_attempted:
            return None

        with self._render_lock:
            if self._driver is not None:
                return self._driver
            if self._driver_init_attempted:
                return None

            self._driver_init_attempted = True
            try:
                from selenium import webdriver
                from selenium.webdriver.chrome.options import Options

                options = Options()
                options.add_argument("--headless=new")
                options.add_argument("--no-sandbox")
                options.add_argument("--disable-gpu")
                options.add_argument("--disable-dev-shm-usage")
                options.add_argument("--disable-background-networking")
                options.add_argument("--disable-features=Translate,BackForwardCache")
                options.add_argument("--hide-scrollbars")
                options.add_argument("--window-size=1200,1000")

                self._driver = webdriver.Chrome(options=options)
                self._driver.set_page_load_timeout(5)
                # Keep compositor background transparent so rounded corners preserve alpha.
                self._driver.execute_cdp_cmd("Page.enable", {})
                self._driver.execute_cdp_cmd(
                    "Emulation.setDefaultBackgroundColorOverride",
                    {"color": {"r": 0, "g": 0, "b": 0, "a": 0}},
                )
            except Exception as e:
                print(f"[ImageGeneratorService] Selenium renderer unavailable: {e}")
                self._driver = None

        return self._driver

    def _invalidate_driver(self):
        """Dispose the current Selenium driver after a renderer failure."""
        with self._render_lock:
            if self._driver is not None:
                try:
                    self._driver.quit()
                except Exception:
                    pass
            self._driver = None
            self._driver_init_attempted = False

    def _get_hti(self):
        """Lazy-load html2image instance."""
        if self._hti is None:
            try:
                from html2image import Html2Image

                self._hti = Html2Image(
                    output_path=self._temp_dir,
                    custom_flags=[
                        "--no-sandbox",
                        "--disable-gpu",
                        "--disable-dev-shm-usage",
                        "--headless=new",
                        "--default-background-color=00000000",
                        "--hide-scrollbars",
                        "--force-device-scale-factor=1.0",
                    ],
                )
            except ImportError:
                print("[ImageGeneratorService] html2image not installed")
                return None
        return self._hti

    def _render_template(self, template_str: str, data: Dict[str, Any]) -> str:
        """Render template using Jinja2."""
        try:
            if self._jinja_template_class is None:
                from jinja2 import Template

                self._jinja_template_class = Template

            if template_str == self._template_content:
                if self._sound_card_template is None:
                    self._sound_card_template = self._jinja_template_class(template_str)
                template = self._sound_card_template
            else:
                template = self._jinja_template_class(template_str)

            return template.render(**data)
        except Exception as e:
            print(f"[ImageGeneratorService] Jinja2 render error: {e}")
            return template_str

    def _render_with_selenium(
        self,
        html_content: str,
        size: Tuple[int, int],
        selector: Optional[str] = ".card",
    ) -> Optional[bytes]:
        """Render HTML to PNG using a persistent Selenium browser session."""
        driver = self._get_driver()
        if driver is None:
            return None

        try:
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.webdriver.support.ui import WebDriverWait

            with self._render_lock:
                width, height = size
                driver.set_window_size(max(900, width), max(640, height))
                driver.get("about:blank")
                driver.execute_script(
                    "document.open();document.write(arguments[0]);document.close();",
                    html_content,
                )
                driver.execute_script(
                    "document.documentElement.style.background='transparent';"
                    "document.body.style.background='transparent';"
                )
                WebDriverWait(driver, 2.0).until(
                    lambda d: d.execute_script("return document.readyState") == "complete"
                )
                if selector:
                    WebDriverWait(driver, 2.0).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                    )
                    clip = driver.execute_script(
                        """
                        const el = document.querySelector(arguments[0]);
                        if (!el) return null;
                        const rect = el.getBoundingClientRect();
                        return {
                            x: Math.max(0, rect.x),
                            y: Math.max(0, rect.y),
                            width: Math.max(1, rect.width),
                            height: Math.max(1, rect.height),
                            scale: window.devicePixelRatio || 1
                        };
                        """,
                        selector,
                    )
                    if not clip:
                        return None
                    result = driver.execute_cdp_cmd(
                        "Page.captureScreenshot",
                        {
                            "format": "png",
                            "omitBackground": True,
                            "fromSurface": True,
                            "clip": clip,
                        },
                    )
                else:
                    result = driver.execute_cdp_cmd(
                        "Page.captureScreenshot",
                        {"format": "png", "omitBackground": True, "fromSurface": True},
                    )
                return base64.b64decode(result["data"])
        except Exception as e:
            print(f"[ImageGeneratorService] Selenium render failed: {e}")
            self._invalidate_driver()
            return None

    def _screenshot_with_html2image(
        self,
        html_content: str,
        size: Tuple[int, int] = (900, 900),
    ) -> Optional[bytes]:
        """Fallback renderer using html2image."""
        hti = self._get_hti()
        if not hti:
            return None

        filename = f"sound_card_{int(time.time() * 1000)}.png"
        hti.screenshot(
            html_str=html_content,
            save_as=filename,
            size=size,
        )

        image_path = os.path.join(self._temp_dir, filename)
        image_bytes = None
        try:
            from PIL import Image

            with Image.open(image_path) as image:
                bbox = image.getbbox()
                cropped = image.crop(bbox) if bbox else image.copy()
                output_buffer = io.BytesIO()
                cropped.save(output_buffer, format="PNG", optimize=False, compress_level=3)
                image_bytes = output_buffer.getvalue()
        except Exception as e:
            print(f"[ImageGeneratorService] Error cropping image: {e}")
            try:
                with open(image_path, "rb") as image_file:
                    image_bytes = image_file.read()
            except Exception as read_error:
                print(f"[ImageGeneratorService] Error reading image bytes: {read_error}")
                image_bytes = None
        finally:
            try:
                os.remove(image_path)
            except Exception:
                pass

        return image_bytes

    def _render_html_to_png(
        self,
        html_content: str,
        size: Tuple[int, int] = (900, 900),
        selector: Optional[str] = ".card",
    ) -> Optional[bytes]:
        """Render HTML to PNG using Selenium first and html2image as fallback."""
        selenium_bytes = self._render_with_selenium(html_content, size=size, selector=selector)
        if selenium_bytes is not None:
            return selenium_bytes
        return self._screenshot_with_html2image(html_content, size=size)

    def _scale_png_bytes(self, image_bytes: Optional[bytes], scale: float) -> Optional[bytes]:
        """Scale PNG bytes while preserving transparency."""
        if not image_bytes:
            return image_bytes
        if scale <= 0 or scale == 1.0:
            return image_bytes

        try:
            from PIL import Image

            with Image.open(io.BytesIO(image_bytes)) as image:
                width, height = image.size
                target_width = max(1, int(width * scale))
                target_height = max(1, int(height * scale))
                if target_width == width and target_height == height:
                    return image_bytes

                resample_filter = (
                    Image.Resampling.LANCZOS
                    if hasattr(Image, "Resampling")
                    else Image.LANCZOS
                )
                resized = image.resize((target_width, target_height), resample=resample_filter)
                output_buffer = io.BytesIO()
                resized.save(output_buffer, format="PNG", optimize=False, compress_level=3)
                return output_buffer.getvalue()
        except Exception as e:
            print(f"[ImageGeneratorService] Error scaling image: {e}")
            return image_bytes

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
        accent_color: Optional[str] = None,
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
            sound_name,
            requester,
            play_count,
            duration,
            download_date,
            lists,
            favorited_by,
            similarity,
            quote,
            is_tts,
            sts_char,
            requester_avatar_url,
            sts_thumbnail_url,
            event_data,
            show_footer,
            show_sound_icon,
            accent_color,
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
        accent_color: Optional[str] = None,
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
            accent_color: Optional hex color for card border (default Discord blurple)

        Returns:
            PNG image bytes or None if generation failed
        """
        try:
            requester_avatar_b64, sts_thumbnail_b64 = self._download_images_parallel(
                requester_avatar_url,
                sts_thumbnail_url,
            )

            if not show_sound_icon:
                speaker_icon = None
                card_class = "sts-mode" if (sts_char or is_tts) else ""
            elif sts_char:
                speaker_icon = self._icons["face"]
                card_class = "sts-mode"
            elif is_tts:
                speaker_icon = self._icons["voice"]
                card_class = "sts-mode"
            else:
                speaker_icon = self._icons["volume"]
                card_class = ""

            display_name = sound_name.replace(".mp3", "")
            if sts_char or is_tts:
                cleaned = re.sub(r"^\d{2}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}-", "", display_name)
                if cleaned:
                    display_name = cleaned

                if quote:
                    display_name = f"says: {quote}"
                else:
                    display_name = f"says: {display_name}"

                if quote:
                    print(f"[ImageGeneratorService] Generating card with quote length: {len(quote)}")

            name_len = len(display_name)
            if name_len > 45:
                title_font_size = 16
            elif name_len > 35:
                title_font_size = 18
            elif name_len > 25:
                title_font_size = 22
            else:
                title_font_size = 26

            has_core_stats = any([
                duration,
                play_count is not None,
                lists,
                favorited_by,
            ])
            has_stats = has_core_stats or bool(event_data)
            summary_only = bool(event_data) and not has_core_stats
            if summary_only:
                card_class = f"{card_class} summary-notification".strip()
            has_leading_icon = bool(sts_thumbnail_b64 or speaker_icon)
            notification_only = (not has_stats) and (not show_footer)
            resolved_accent_color = accent_color or "#5865F2"
            accent_rgb = self._hex_to_rgb(resolved_accent_color)

            data = {
                "sound_name": display_name,
                "title_font_size": title_font_size,
                "requester": requester,
                "speaker_icon": speaker_icon,
                "icon_timer": self._icons["timer"],
                "icon_chart": self._icons["chart"],
                "icon_calendar": self._icons["calendar"],
                "icon_folder": self._icons["folder"],
                "icon_heart": self._icons["heart"],
                "icon_event": self._icons["event"],
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
                "accent_color": resolved_accent_color,
                "accent_rgb": accent_rgb,
            }

            html_content = self._render_template(self._template_content, data)

            canvas_height = 640
            if has_stats:
                canvas_height = 820
            if has_stats and show_footer:
                canvas_height = 900

            rendered = self._render_html_to_png(
                html_content,
                size=(900, canvas_height),
                selector=".card",
            )
            return self._scale_png_bytes(rendered, scale=self._card_image_scale)

        except Exception as e:
            print(f"[ImageGeneratorService] Error generating sound card: {e}")
            import traceback

            traceback.print_exc()
            return None

    def generate_loading_gif(self) -> Optional[bytes]:
        """Generate (or load cached) animated loading GIF.

        Returns:
            GIF image bytes or None if generation failed
        """
        cache_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "Data", "loading.gif")
        )

        if os.path.exists(cache_path):
            with open(cache_path, "rb") as gif_file:
                return gif_file.read()

        print("[ImageGeneratorService] Generating loading.gif (one-time process)...")

        try:
            from PIL import Image

            frames = []
            template_content = self._get_loading_html()

            for angle in range(0, 360, 30):
                data = {
                    "title": "Processing...",
                    "subtitle": "Generating audio, please wait",
                    "rotation": angle,
                }
                html_content = self._render_template(template_content, data)
                frame_bytes = self._render_html_to_png(
                    html_content,
                    size=(320, 220),
                    selector=".card",
                )
                if not frame_bytes:
                    continue
                with Image.open(io.BytesIO(frame_bytes)) as image:
                    frames.append(image.copy())

            if not frames:
                return None

            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            frames[0].save(
                cache_path,
                save_all=True,
                append_images=frames[1:],
                optimize=False,
                duration=80,
                loop=0,
            )

            print(f"[ImageGeneratorService] Saved loading.gif to {cache_path}")

            with open(cache_path, "rb") as gif_file:
                return gif_file.read()

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
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
        }
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
            font-size: 12px;
            font-weight: 700;
            color: #ffffff;
            text-align: center;
            white-space: nowrap;
        }
        .subtitle {
            font-size: 8px;
            color: #6b7280;
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
