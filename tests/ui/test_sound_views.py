"""Tests for sound playback Discord views."""

from bot.ui.buttons.sounds import SendControlsButton, ToggleControlsButton
from bot.ui.views.sounds import SoundBeingPlayedView
import pytest


@pytest.mark.asyncio
async def test_down_arrow_disabled_while_playback_active_but_gear_stays_enabled():
    """Ensure active playback disables only the collapsed controls toggle."""
    view = SoundBeingPlayedView(
        bot_behavior=None,
        audio_file="clip.mp3",
        controls_toggle_disabled=True,
    )

    toggle = next(item for item in view.children if isinstance(item, ToggleControlsButton))
    gear = next(item for item in view.children if isinstance(item, SendControlsButton))

    assert str(toggle.emoji) == "🔽"
    assert toggle.disabled is True
    assert gear.disabled is False


@pytest.mark.asyncio
async def test_down_arrow_enabled_after_playback_finishes():
    """Ensure the collapsed controls toggle re-enables when playback is over."""
    view = SoundBeingPlayedView(
        bot_behavior=None,
        audio_file="clip.mp3",
        controls_toggle_disabled=True,
    )

    view.set_controls_toggle_disabled(False)

    toggle = next(item for item in view.children if isinstance(item, ToggleControlsButton))
    assert str(toggle.emoji) == "🔽"
    assert toggle.disabled is False
