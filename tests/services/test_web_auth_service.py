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
