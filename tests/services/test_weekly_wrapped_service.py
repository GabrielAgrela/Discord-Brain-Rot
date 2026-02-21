"""
Tests for bot/services/weekly_wrapped.py - WeeklyWrappedService.
"""

import os
import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock, patch

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class TestWeeklyWrappedService:
    """Tests for weekly wrapped generation and delivery."""

    @pytest.fixture
    def service_bundle(self):
        """Create service with mocked repositories/message service."""
        with patch("bot.services.weekly_wrapped.ActionRepository") as mock_action_repo_cls, patch(
            "bot.services.weekly_wrapped.StatsRepository"
        ) as mock_stats_repo_cls:
            from bot.services.weekly_wrapped import WeeklyWrappedService

            action_repo = Mock()
            stats_repo = Mock()
            mock_action_repo_cls.return_value = action_repo
            mock_stats_repo_cls.return_value = stats_repo

            bot = Mock()
            message_service = Mock()
            message_service.send_message = AsyncMock(return_value=Mock())

            service = WeeklyWrappedService(bot=bot, message_service=message_service)
            yield service, action_repo, stats_repo, message_service

    def test_week_key_from_utc(self):
        """Week key should be anchored to Monday in UTC."""
        from bot.services.weekly_wrapped import WeeklyWrappedService

        now_utc = datetime(2026, 2, 18, 12, 0, tzinfo=timezone.utc)  # Wednesday
        assert WeeklyWrappedService.week_key_from_utc(now_utc) == "week:2026-02-16"

    @pytest.mark.asyncio
    async def test_send_weekly_wrapped_skips_when_already_sent(self, service_bundle):
        """No message should be sent when this week was already delivered."""
        service, action_repo, _stats_repo, message_service = service_bundle
        action_repo.has_action_for_target.return_value = True

        guild = Mock(id=777, name="Test Guild")

        sent = await service.send_weekly_wrapped(guild=guild)

        assert sent is False
        message_service.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_send_weekly_wrapped_sends_and_records_delivery(self, service_bundle):
        """Service should send digest and persist a weekly delivery marker."""
        service, action_repo, stats_repo, message_service = service_bundle
        action_repo.has_action_for_target.return_value = False
        action_repo.get_top_sounds.return_value = ([('airhorn.mp3', 9)], 9)
        action_repo.get_top_users.return_value = [('gabi', 12)]

        stats_repo.get_top_voice_users.return_value = [
            {'username': 'gabi', 'total_hours': 4.25, 'session_count': 8}
        ]
        stats_repo.get_top_voice_channels.return_value = [
            {'channel_id': '123', 'total_hours': 7.5, 'session_count': 10}
        ]
        stats_repo.get_summary_stats.return_value = {
            'total_plays': 20,
            'sounds_this_week': 3,
        }
        stats_repo.get_activity_heatmap.return_value = [
            {'day': 5, 'hour': 22, 'count': 6}
        ]

        channel = Mock(name='General')
        guild = Mock(id=42, name='Chaos', get_channel=Mock(return_value=channel))

        sent = await service.send_weekly_wrapped(
            guild=guild,
            days=7,
            force=False,
            record_delivery=True,
            now_utc=datetime(2026, 2, 21, 12, 0, tzinfo=timezone.utc),
        )

        assert sent is True
        message_service.send_message.assert_awaited_once()
        action_repo.insert.assert_called_once_with(
            'admin',
            service.DELIVERY_ACTION,
            'week:2026-02-16',
            guild_id=42,
        )

    @pytest.mark.asyncio
    async def test_send_weekly_wrapped_force_manual_does_not_mark_delivery(self, service_bundle):
        """Manual force sends should audit manual trigger without weekly dedupe marker."""
        service, action_repo, stats_repo, _message_service = service_bundle
        action_repo.has_action_for_target.return_value = False
        action_repo.get_top_sounds.return_value = ([], 0)
        action_repo.get_top_users.return_value = []
        stats_repo.get_top_voice_users.return_value = []
        stats_repo.get_top_voice_channels.return_value = []
        stats_repo.get_summary_stats.return_value = {
            'total_plays': 0,
            'sounds_this_week': 0,
        }
        stats_repo.get_activity_heatmap.return_value = []

        guild = Mock(id=55, name='Manual Guild', get_channel=Mock(return_value=None))

        sent = await service.send_weekly_wrapped(
            guild=guild,
            days=10,
            force=True,
            record_delivery=False,
            requested_by='moderator',
            now_utc=datetime(2026, 2, 21, 12, 0, tzinfo=timezone.utc),
        )

        assert sent is True
        action_repo.insert.assert_called_once_with(
            'moderator',
            service.MANUAL_ACTION,
            '10d',
            guild_id=55,
        )
