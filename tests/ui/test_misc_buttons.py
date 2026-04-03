"""
Tests for bot/ui/buttons/misc.py - guild-aware button callbacks.
"""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest


@pytest.mark.asyncio
async def test_stats_button_passes_guild_to_behavior(monkeypatch):
    """Stats button should keep guild context so downstream action logging stays scoped."""
    from bot.ui.buttons.misc import StatsButton

    scheduled_tasks = []

    def _schedule(coro):
        task = asyncio.get_running_loop().create_task(coro)
        scheduled_tasks.append(task)
        return task

    monkeypatch.setattr("bot.ui.buttons.misc.asyncio.create_task", _schedule)

    behavior = Mock()
    behavior.display_top_users = AsyncMock()

    button = StatsButton(behavior, label="Stats")

    interaction = Mock()
    interaction.user = Mock()
    interaction.guild = Mock(id=123)
    interaction.response.defer = AsyncMock()

    await button.callback(interaction)
    await asyncio.gather(*scheduled_tasks)

    behavior.display_top_users.assert_awaited_once_with(
        interaction.user,
        number_users=20,
        number_sounds=5,
        days=700,
        by="plays",
        guild=interaction.guild,
    )


@pytest.mark.asyncio
async def test_brain_rot_button_passes_guild_to_behavior(monkeypatch):
    """Brain rot button should use the centralized service path with guild context."""
    from bot.ui.buttons.misc import BrainRotButton

    scheduled_tasks = []

    def _schedule(coro):
        task = asyncio.get_running_loop().create_task(coro)
        scheduled_tasks.append(task)
        return task

    monkeypatch.setattr("bot.ui.buttons.misc.asyncio.create_task", _schedule)

    behavior = Mock()
    behavior.run_random_brain_rot = AsyncMock()

    button = BrainRotButton(behavior, label="Brain Rot")

    interaction = Mock()
    interaction.user = Mock()
    interaction.guild = Mock(id=456)
    interaction.response.defer = AsyncMock()

    await button.callback(interaction)
    await asyncio.gather(*scheduled_tasks)

    behavior.run_random_brain_rot.assert_awaited_once_with(
        interaction.user,
        guild=interaction.guild,
    )
