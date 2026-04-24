from types import SimpleNamespace

import pytest

from bot.services.web_auth import DiscordOAuthError, WebAuthService


def test_sanitize_next_path_rejects_external_redirects():
    service = WebAuthService()

    assert service.sanitize_next_path("https://evil.example/steal", "/") == "/"
    assert service.sanitize_next_path("dashboard", "/") == "/"
    assert service.sanitize_next_path("/analytics", "/") == "/analytics"


def test_get_current_user_ignores_invalid_session_payload():
    service = WebAuthService()

    assert service.get_current_user(None) is None
    assert service.get_current_user({"id": "", "username": "name"}) is None
    assert service.get_current_user({"id": "123", "username": "name"}).id == "123"


def test_build_authorize_url_requests_guild_scope():
    service = WebAuthService()

    authorize_url = service.build_authorize_url(
        "state",
        "https://example.com/callback",
        env={"DISCORD_OAUTH_CLIENT_ID": "client"},
    )

    assert "scope=identify+guilds" in authorize_url


def test_exchange_code_for_user_stores_admin_guild_permissions():
    class _FakeResponse:
        def __init__(self, payload, ok=True):
            self._payload = payload
            self.ok = ok

        def json(self):
            return self._payload

    class _FakeRequestsSession:
        @staticmethod
        def post(*args, **kwargs):
            return _FakeResponse({"access_token": "token"})

        @staticmethod
        def get(url, *args, **kwargs):
            if url.endswith("/users/@me/guilds"):
                return _FakeResponse(
                    [
                        {"id": "111", "permissions": "8"},
                        {"id": "222", "permissions": "16"},
                        {"id": "333", "permissions": "32"},
                        {"id": "444", "permissions": "0"},
                    ]
                )
            return _FakeResponse(
                {
                    "id": "123",
                    "username": "discord-user",
                    "global_name": "Discord User",
                }
            )

    service = WebAuthService(requests_session=_FakeRequestsSession())

    user = service.exchange_code_for_user(
        "abc",
        redirect_uri="https://example.com/callback",
        api_base_url="https://discord.com/api",
        env={
            "DISCORD_OAUTH_CLIENT_ID": "client",
            "DISCORD_OAUTH_CLIENT_SECRET": "secret",
        },
    )

    assert user.admin_guild_ids == ("111", "222", "333")


def test_exchange_code_for_user_raises_when_token_exchange_fails():
    requests_session = SimpleNamespace(
        post=lambda *args, **kwargs: SimpleNamespace(ok=False),
    )
    service = WebAuthService(requests_session=requests_session)

    with pytest.raises(DiscordOAuthError, match="token exchange"):
        service.exchange_code_for_user(
            "abc",
            redirect_uri="https://example.com/callback",
            api_base_url="https://discord.com/api",
            env={
                "DISCORD_OAUTH_CLIENT_ID": "client",
                "DISCORD_OAUTH_CLIENT_SECRET": "secret",
            },
        )
