"""
Tests for bot/services/image_generator.py - ImageGeneratorService.
"""

import io
import os
import sys
from unittest.mock import patch

from PIL import Image

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _create_png_bytes(width: int, height: int) -> bytes:
    """Create in-memory PNG bytes for testing."""
    image = Image.new("RGBA", (width, height), (255, 0, 0, 255))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _image_size(image_bytes: bytes) -> tuple[int, int]:
    """Read PNG dimensions from bytes."""
    with Image.open(io.BytesIO(image_bytes)) as image:
        return image.size


class TestImageGeneratorService:
    """Tests for image scaling behavior in ImageGeneratorService."""

    def test_scale_png_bytes_halves_dimensions(self):
        """Scaling helper should reduce dimensions by 50%."""
        from bot.services.image_generator import ImageGeneratorService

        service = ImageGeneratorService()
        original = _create_png_bytes(200, 100)

        scaled = service._scale_png_bytes(original, 0.5)

        assert scaled is not None
        assert _image_size(scaled) == (100, 50)

    def test_generate_sound_card_sync_outputs_scaled_image(self):
        """Sound cards should be scaled down using the configured default scale."""
        from bot.services.image_generator import ImageGeneratorService

        service = ImageGeneratorService()
        rendered = _create_png_bytes(580, 180)

        with patch.object(service, "_render_html_to_png", return_value=rendered):
            result = service._generate_sound_card_sync(
                sound_name="test.mp3",
                requester="tester",
                show_footer=False,
                show_sound_icon=False,
            )

        assert result is not None
        assert _image_size(result) == (435, 135)

    def test_generate_sound_card_sync_renders_event_data_summary(self):
        """Notification summaries should be rendered when event_data is provided."""
        from bot.services.image_generator import ImageGeneratorService

        service = ImageGeneratorService()
        rendered = _create_png_bytes(580, 180)
        captured: dict[str, str] = {}

        def _capture_render(html_content, size, selector):
            captured["html"] = html_content
            return rendered

        with patch.object(service, "_render_html_to_png", side_effect=_capture_render):
            result = service._generate_sound_card_sync(
                sound_name="Done",
                requester="tester",
                event_data="3 sites checked | 0 new sounds found (0 downloaded) | 0 skipped/invalid | 1.2s",
                show_footer=False,
                show_sound_icon=False,
                accent_color="#ED4245",
            )

        assert result is not None
        assert "summary-pill" in captured["html"]
        assert "summary-grid" in captured["html"]
        assert "summary-item" in captured["html"]
        assert "margin-bottom: 24px;" in captured["html"]
        assert "justify-content: center;" in captured["html"]
        assert "align-items: center;" in captured["html"]
        assert "summary-notification" in captured["html"]
        assert "--accent-rgb: 237, 66, 69;" in captured["html"]
        assert "3 sites checked" in captured["html"]
        assert "0 new sounds found (0 downloaded)" in captured["html"]
        assert "0 downloaded" in captured["html"]
        assert "0 skipped/invalid" in captured["html"]
        assert "1.2s" in captured["html"]

    def test_generate_rl_store_card_sync_renders_item_images(self):
        """RL store cards should include every item tile image in the rendered HTML."""
        from bot.services.image_generator import ImageGeneratorService

        service = ImageGeneratorService()
        rendered = _create_png_bytes(1500, 760)
        captured: dict[str, str] = {}

        def _capture_render(html_content, size, selector):
            captured["html"] = html_content
            captured["selector"] = selector
            captured["size"] = size
            return rendered

        card_data = {
            "shop_name": "Featured Shop",
            "shop_subtitle": None,
            "shop_type": "Featured",
            "updated_text": "March 17, 2026 19:00 UTC",
            "ends_text": "Ends Mar 18 19:00 UTC",
            "page_text": "Page 1/2",
            "summary_text": "Shop 1/1 | Shop Page 1/2",
            "source_label": "Source rlshop.gg",
            "accent_color": "#F59E0B",
            "grid_columns": 5,
            "tiles": [
                {
                    "label": "Cyclone",
                    "category": "Body",
                    "group_label": "Miku Bundle",
                    "paint_badge": "Orange",
                    "paint_badge_background": "#F97316",
                    "paint_badge_color": "#FFF7ED",
                    "paint_badge_border": "rgba(254, 215, 170, 0.36)",
                    "time_badge": "23h 4m",
                    "price_text": "1500 credits",
                    "image_url": "https://rlshop.gg/cyclone.png",
                    "placeholder": "CYC",
                },
                {
                    "label": "Miku Wheels",
                    "category": "Wheels",
                    "group_label": "Miku Bundle",
                    "paint_badge": None,
                    "paint_badge_background": None,
                    "paint_badge_color": None,
                    "paint_badge_border": None,
                    "time_badge": "23h 4m",
                    "price_text": None,
                    "image_url": "https://rlshop.gg/wheels.png",
                    "placeholder": "MIK",
                }
            ],
        }

        with patch.object(
            service,
            "_download_many_images",
            return_value={
                "https://rlshop.gg/cyclone.png": "abc123",
                "https://rlshop.gg/wheels.png": "def456",
            },
        ), patch.object(service, "_render_html_to_png", side_effect=_capture_render):
            result = service._generate_rl_store_card_sync(card_data)

        assert result is not None
        assert _image_size(result) == (1125, 570)
        assert captured["selector"] == ".store-board"
        assert "tile-grid" in captured["html"]
        assert "Cyclone" in captured["html"]
        assert "Miku Wheels" in captured["html"]
        assert "Miku Bundle" in captured["html"]
        assert "23h 4m" in captured["html"]
        assert "data:image/png;base64,abc123" in captured["html"]
        assert "data:image/png;base64,def456" in captured["html"]
        assert "--accent-rgb: 245, 158, 11;" in captured["html"]
        assert "width: 1320px;" in captured["html"]
        assert "border-radius: 40px;" in captured["html"]
        assert "border: 12px solid var(--accent-color);" in captured["html"]
        assert "background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #1a1a2e 100%);" in captured["html"]
        assert "tile-art-inner" in captured["html"]
        assert "border: 4px solid var(--accent-color);" in captured["html"]
        assert "border-radius: 28px;" in captured["html"]
        assert "background: #F97316;" in captured["html"]
        assert "color: #FFF7ED;" in captured["html"]
        assert captured["size"] == (1500, 760)

    def test_generate_sound_card_sync_renders_request_note_in_footer(self):
        """request_note appears as a TTS pill in the footer, not as a standalone row."""
        from bot.services.image_generator import ImageGeneratorService

        service = ImageGeneratorService()
        rendered = _create_png_bytes(580, 180)
        captured: dict[str, str] = {}

        def _capture_render(html_content, size, selector):
            captured["html"] = html_content
            captured["size"] = size
            return rendered

        with patch.object(service, "_render_html_to_png", side_effect=_capture_render):
            result = service._generate_sound_card_sync(
                sound_name="test.mp3",
                requester="tester",
                duration="0:15",
                play_count=42,
                request_note="play jimmy neutron",
                download_date="Aug 12, 2025",
                show_footer=True,
                show_sound_icon=True,
            )

        assert result is not None
        html = captured["html"]

        # Verify TTS: pill in footer, not Voice:/Heard: standalone row
        assert "TTS:" in html, "Should use TTS label, not Voice or Heard"
        assert "Voice:" not in html, "Should not contain old Voice label"
        assert "Heard:" not in html, "Should not contain old Heard label"
        assert "play jimmy neutron" in html, "Should contain the request note text"

        # The request note should live inside the footer row
        assert "footer-note-pill" in html, "Should use footer-note-pill class"
        assert "footer-note-text" in html, "Should use footer-note-text class"

        # Footer should appear with space-between layout
        assert "justify-content: space-between" in html, "Footer should use space-between"

        # Old standalone request-note-pill should be gone
        assert "request-note-pill" not in html, "Old standalone pill class should not appear"

        # Canvas height should NOT include the old +60 bump for request_note
        # Stats + footer → 900; request_note should not inflate it further
        assert captured["size"] == (900, 900), (
            f"Expected canvas 900x900 (no +60 for request_note), got {captured['size']}"
        )

    def test_generate_sound_card_sync_renders_request_note_without_download_date(self):
        """request_note should still appear in footer even when download_date is missing."""
        from bot.services.image_generator import ImageGeneratorService

        service = ImageGeneratorService()
        rendered = _create_png_bytes(580, 180)
        captured: dict[str, str] = {}

        def _capture_render(html_content, size, selector):
            captured["html"] = html_content
            return rendered

        with patch.object(service, "_render_html_to_png", side_effect=_capture_render):
            result = service._generate_sound_card_sync(
                sound_name="no-date.mp3",
                requester="tester",
                request_note="play something",
                download_date=None,
                show_footer=True,
                show_sound_icon=True,
            )

        assert result is not None
        html = captured["html"]
        assert "TTS:" in html
        assert "footer-note-pill" in html
        assert "play something" in html
        # Footer should still render (triggered by request_note even when footer is conceptually "on")
        assert "row-footer" in html

    def test_generate_sound_card_sync_renders_speaker_icon_with_request_note(self):
        """The request note footer pill should reuse speaker_icon when in TTS/voice mode."""
        from bot.services.image_generator import ImageGeneratorService

        service = ImageGeneratorService()
        rendered = _create_png_bytes(580, 180)
        captured: dict[str, str] = {}

        def _capture_render(html_content, size, selector):
            captured["html"] = html_content
            return rendered

        with patch.object(service, "_render_html_to_png", side_effect=_capture_render):
            result = service._generate_sound_card_sync(
                sound_name="tts-sound",
                requester="tester",
                request_note="play despacito",
                is_tts=True,
                show_footer=True,
            )

        assert result is not None
        html = captured["html"]
        # voice icon (for TTS mode) should be in the footer-note-icon
        assert "footer-note-icon" in html
        assert "TTS:" in html
        assert "play despacito" in html

    def test_estimate_rl_store_canvas_height_scales_by_row_count(self):
        """RL store canvas estimates should leave extra headroom for multi-line tile text."""
        from bot.services.image_generator import ImageGeneratorService

        service = ImageGeneratorService()

        assert service._estimate_rl_store_canvas_height(0, 5) == 520
        assert service._estimate_rl_store_canvas_height(5, 5) == 760
        assert service._estimate_rl_store_canvas_height(10, 5) == 1120
