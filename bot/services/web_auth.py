"""
Service layer for Discord web authentication.
"""

from __future__ import annotations

from collections.abc import Mapping
import os
from typing import Any
from urllib.parse import urlencode, urlparse

import requests

from bot.models.web import DiscordWebUser


DISCORD_PERMISSION_ADMINISTRATOR = 0x8
DISCORD_PERMISSION_MANAGE_CHANNELS = 0x10
DISCORD_PERMISSION_MANAGE_GUILD = 0x20


class DiscordOAuthError(Exception):
    """
    Raised when Discord OAuth interactions fail.
    """

    def __init__(self, message: str, status_code: int) -> None:
        """
        Initialize the error.

        Args:
            message: User-facing error message.
            status_code: HTTP status code the route should return.
        """
        super().__init__(message)
        self.status_code = status_code


class WebAuthService:
    """
    Service for Discord OAuth configuration and session user parsing.
    """

    def __init__(self, requests_session: Any = requests) -> None:
        """
        Initialize the service.

        Args:
            requests_session: HTTP client compatible with ``requests``.
        """
        self._requests_session = requests_session

    def get_oauth_config(self, env: Mapping[str, str] | None = None) -> dict[str, str]:
        """
        Return Discord OAuth configuration from the environment.

        Args:
            env: Optional environment mapping for tests.

        Returns:
            OAuth configuration values.
        """
        env_map = env if env is not None else os.environ
        return {
            "client_id": env_map.get("DISCORD_OAUTH_CLIENT_ID", "").strip(),
            "client_secret": env_map.get("DISCORD_OAUTH_CLIENT_SECRET", "").strip(),
            "redirect_uri": env_map.get("DISCORD_OAUTH_REDIRECT_URI", "").strip(),
        }

    def oauth_is_configured(self, env: Mapping[str, str] | None = None) -> bool:
        """
        Return whether Discord OAuth is configured.

        Args:
            env: Optional environment mapping for tests.

        Returns:
            ``True`` when client id and secret are configured.
        """
        config = self.get_oauth_config(env)
        return bool(config["client_id"] and config["client_secret"])

    def sanitize_next_path(self, next_path: str | None, default_path: str) -> str:
        """
        Restrict redirects to local relative paths.

        Args:
            next_path: Requested redirect target.
            default_path: Fallback route when the target is unsafe.

        Returns:
            Safe redirect path.
        """
        if not next_path:
            return default_path

        parsed = urlparse(next_path)
        if parsed.scheme or parsed.netloc:
            return default_path
        if not next_path.startswith("/"):
            return default_path
        return next_path

    def get_current_user(self, session_payload: Any) -> DiscordWebUser | None:
        """
        Parse the current authenticated user from session data.

        Args:
            session_payload: Raw session payload.

        Returns:
            Authenticated user when the payload is valid, otherwise ``None``.
        """
        return DiscordWebUser.from_session_payload(session_payload)

    def build_authorize_url(
        self,
        state: str,
        redirect_uri: str,
        env: Mapping[str, str] | None = None,
    ) -> str:
        """
        Build the Discord authorization URL.

        Args:
            state: CSRF state value.
            redirect_uri: Callback URL.
            env: Optional environment mapping for tests.

        Returns:
            Fully qualified Discord OAuth authorize URL.
        """
        config = self.get_oauth_config(env)
        query = urlencode(
            {
                "client_id": config["client_id"],
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": "identify guilds",
                "state": state,
            }
        )
        return f"https://discord.com/oauth2/authorize?{query}"

    def exchange_code_for_user(
        self,
        code: str,
        *,
        redirect_uri: str,
        api_base_url: str,
        env: Mapping[str, str] | None = None,
    ) -> DiscordWebUser:
        """
        Exchange an OAuth code for the current Discord user.

        Args:
            code: Authorization code from Discord.
            redirect_uri: Callback URL used for the exchange.
            api_base_url: Base Discord API URL.
            env: Optional environment mapping for tests.

        Returns:
            Authenticated Discord user.

        Raises:
            DiscordOAuthError: If token exchange or user lookup fails.
        """
        config = self.get_oauth_config(env)

        token_response = self._requests_session.post(
            f"{api_base_url}/oauth2/token",
            data={
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        if not token_response.ok:
            raise DiscordOAuthError("Discord login failed during token exchange", 502)

        access_token = str(token_response.json().get("access_token") or "").strip()
        if not access_token:
            raise DiscordOAuthError("Discord login failed: missing access token", 502)

        user_response = self._requests_session.get(
            f"{api_base_url}/users/@me",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        if not user_response.ok:
            raise DiscordOAuthError(
                "Discord login failed while loading user profile",
                502,
            )

        admin_guild_ids = self._load_admin_guild_ids(access_token, api_base_url)
        return DiscordWebUser.from_discord_payload(
            user_response.json(),
            admin_guild_ids=admin_guild_ids,
        )

    def _load_admin_guild_ids(self, access_token: str, api_base_url: str) -> tuple[str, ...]:
        """
        Return guild IDs where the OAuth user matches bot admin/mod permissions.

        This mirrors ``BotBehavior.is_admin_or_mod`` for web sessions by using
        Discord's OAuth guild permission bitset: administrator, manage guild,
        or manage channels.
        """
        guilds_response = self._requests_session.get(
            f"{api_base_url}/users/@me/guilds",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        if not guilds_response.ok:
            return ()

        admin_guild_ids: list[str] = []
        for guild in guilds_response.json():
            guild_id = str(guild.get("id") or "").strip()
            if not guild_id:
                continue
            try:
                permissions = int(str(guild.get("permissions") or "0"))
            except ValueError:
                permissions = 0
            if permissions & (
                DISCORD_PERMISSION_ADMINISTRATOR
                | DISCORD_PERMISSION_MANAGE_GUILD
                | DISCORD_PERMISSION_MANAGE_CHANNELS
            ):
                admin_guild_ids.append(guild_id)
        return tuple(admin_guild_ids)
