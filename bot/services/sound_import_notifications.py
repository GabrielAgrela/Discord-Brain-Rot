"""
Shared service for sending sound import notifications to Discord.

All import paths (scraper, manual Discord upload, web upload, favorite watcher)
should use this service so they share the same notification code.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bot.behavior import BotBehavior

logger = logging.getLogger(__name__)


class SoundImportNotificationService:
    """
    Centralise sound import notifications into a single code path.

    Default title templates, requester labels, and accent colours are
    derived from the ``source`` parameter:

    ================== ================== =================== ===========
    Source              Title Template      Requester           Accent
    ================== ================== =================== ===========
    ``web_upload``      🌐 Web sound      Web Upload          ``#5865F2``
                        imported:
                        {filename}
    ``favorite_watcher`` 🎵 New favorite    Favorite Watcher    ``#5865F2``
                        sound imported:
                        {filename}
    ``scraper``         🦝 I stole         Sound Thief         ``#ED4245``
                        {filename}
    ``manual_upload``   🎵 New sound       Manual Upload       ``#ED4245``
                        imported:
                        {filename}
    ================== ================== =================== ===========
    """

    SOURCE_ACCENTS: dict[str, str] = {
        "web_upload": "#5865F2",
        "favorite_watcher": "#5865F2",
        "scraper": "#ED4245",
        "manual_upload": "#ED4245",
    }

    SOURCE_REQUESTERS: dict[str, str] = {
        "web_upload": "Web Upload",
        "favorite_watcher": "Favorite Watcher",
        "scraper": "Sound Thief",
        "manual_upload": "Manual Upload",
    }

    SOURCE_TITLE_TEMPLATES: dict[str, str] = {
        "web_upload": "🌐 Web sound imported: {filename}",
        "favorite_watcher": "🎵 New favorite sound imported: {filename}",
        "scraper": "🦝 I stole {filename}",
        "manual_upload": "🎵 New sound imported: {filename}",
    }

    def __init__(self) -> None:
        pass

    async def send_notification(
        self,
        behavior: Any,
        filename: str,
        *,
        guild_id: int | None = None,
        source: str = "manual_upload",
        requester: str | None = None,
        title: str | None = None,
        accent_color: str | None = None,
    ) -> None:
        """
        Send a sound import notification image card to the bot channel.

        Args:
            behavior: BotBehavior instance used to send the message.
            filename: Imported sound filename (e.g. ``funny.mp3``).
            guild_id: Target guild ID. When ``None`` the behavior's default
                bot channel is used.
            source: Origin label for default title/requester/accent lookup.
            requester: Override for the image card requester label. Falls back
                to the source default when ``None``.
            title: Override for the notification title text. Falls back to the
                source default when ``None``.
            accent_color: Hex colour override for the image border. Falls back
                to the source default when ``None``.
        """
        if behavior is None:
            return

        # Resolve defaults from source.
        if title is None:
            template = self.SOURCE_TITLE_TEMPLATES.get(
                source, "🎵 New sound imported: {filename}"
            )
            title = template.format(filename=filename)
        if requester is None:
            requester = self.SOURCE_REQUESTERS.get(source, "Sound Import")
        if accent_color is None:
            accent_color = self.SOURCE_ACCENTS.get(source, "#5865F2")

        # Resolve guild for multi-guild support.
        guild = None
        if guild_id is not None:
            bot = getattr(behavior, "bot", None)
            if bot and hasattr(bot, "get_guild"):
                guild = bot.get_guild(guild_id)

        try:
            from bot.ui.views.controls import DownloadedSoundView

            await behavior.send_message(
                title=title,
                view=DownloadedSoundView(behavior, filename),
                guild=guild,
                message_format="image",
                image_requester=requester,
                image_show_footer=False,
                image_show_sound_icon=False,
                image_border_color=accent_color,
            )
        except Exception as exc:
            logger.error(
                "[SoundImportNotificationService] Failed to send import notification for %s: %s",
                filename,
                exc,
                exc_info=True,
            )
