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
