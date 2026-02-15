"""
Tests for bot/services/message.py - MessageService.
"""

import os
import sys
from unittest.mock import AsyncMock, Mock

import pytest
import discord

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class TestMessageService:
    """Tests for MessageService default view behavior."""

    @pytest.fixture
    def message_service(self):
        """Create a MessageService with mocked bot."""
        from bot.services.message import MessageService

        bot = Mock()
        service = MessageService(bot=bot)
        service._bot_behavior = Mock()
        return service

    @pytest.mark.asyncio
    async def test_send_message_image_attaches_default_inline_controls_view(self, message_service):
        """Image messages should include inline controls when no custom view is supplied."""
        channel = Mock()
        channel.send = AsyncMock(return_value=Mock())

        default_view = Mock()
        message_service._build_default_inline_controls_view = Mock(return_value=default_view)
        message_service._generate_message_image = AsyncMock(return_value=b"fake-image")

        await message_service.send_message(
            title="hello",
            channel=channel,
            message_format="image",
            image_border_color="#ED4245",
        )

        kwargs = channel.send.await_args.kwargs
        assert kwargs["view"] is default_view
        message_service._build_default_inline_controls_view.assert_called_once_with(style=discord.ButtonStyle.danger)

    @pytest.mark.asyncio
    async def test_send_message_image_keeps_custom_view(self, message_service):
        """Custom view should not be replaced by default inline controls."""
        channel = Mock()
        channel.send = AsyncMock(return_value=Mock())

        custom_view = Mock()
        message_service._build_default_inline_controls_view = Mock(return_value=Mock())
        message_service._generate_message_image = AsyncMock(return_value=b"fake-image")

        await message_service.send_message(
            title="hello",
            channel=channel,
            message_format="image",
            view=custom_view,
        )

        kwargs = channel.send.await_args.kwargs
        assert kwargs["view"] is custom_view
        message_service._build_default_inline_controls_view.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_message_embed_attaches_default_inline_controls_view(self, message_service):
        """Embed messages should also include inline controls when no custom view is supplied."""
        channel = Mock()
        channel.send = AsyncMock(return_value=Mock())

        default_view = Mock()
        message_service._build_default_inline_controls_view = Mock(return_value=default_view)

        await message_service.send_message(
            title="hello",
            channel=channel,
            message_format="embed",
            color=discord.Color.green(),
        )

        kwargs = channel.send.await_args.kwargs
        assert kwargs["view"] is default_view
        message_service._build_default_inline_controls_view.assert_called_once_with(style=discord.ButtonStyle.success)
