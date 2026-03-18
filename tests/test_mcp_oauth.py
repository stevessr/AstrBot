from pathlib import Path

import pytest
from mcp.shared.auth import OAuthToken

from astrbot.core.agent.mcp_oauth import (
    MCPFileTokenStorage,
    MCPOAuthAuthorizationRequiredError,
    create_mcp_http_auth,
    get_mcp_oauth_state,
)


@pytest.mark.asyncio
async def test_get_mcp_oauth_state_reports_unauthorized_without_tokens(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "astrbot.core.agent.mcp_oauth.get_astrbot_data_path",
        lambda: str(tmp_path),
    )

    config = {
        "transport": "streamable_http",
        "url": "https://example.com/mcp/no-token",
        "oauth2": {
            "grant_type": "authorization_code",
            "client_name": "AstrBot MCP Client",
        },
    }

    state = await get_mcp_oauth_state(config)

    assert state["oauth2_enabled"] is True
    assert state["oauth2_authorized"] is False
    assert state["oauth2_grant_type"] == "authorization_code"


@pytest.mark.asyncio
async def test_get_mcp_oauth_state_reports_authorized_with_tokens(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "astrbot.core.agent.mcp_oauth.get_astrbot_data_path",
        lambda: str(tmp_path),
    )

    config = {
        "transport": "streamable_http",
        "url": "https://example.com/mcp/with-token",
        "oauth2": {
            "grant_type": "authorization_code",
            "client_name": "AstrBot MCP Client",
        },
    }
    storage = MCPFileTokenStorage.from_mcp_config(config)
    await storage.set_tokens(
        OAuthToken(
            access_token="token-123",
            token_type="Bearer",
            expires_in=3600,
            refresh_token="refresh-123",
        ),
    )

    state = await get_mcp_oauth_state(config)

    assert state["oauth2_enabled"] is True
    assert state["oauth2_authorized"] is True
    assert state["oauth2_grant_type"] == "authorization_code"


@pytest.mark.asyncio
async def test_create_mcp_http_auth_requires_authorization_without_tokens(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "astrbot.core.agent.mcp_oauth.get_astrbot_data_path",
        lambda: str(tmp_path),
    )

    config = {
        "transport": "streamable_http",
        "url": "https://example.com/mcp/login-required",
        "oauth2": {
            "grant_type": "authorization_code",
            "client_name": "AstrBot MCP Client",
        },
    }

    with pytest.raises(MCPOAuthAuthorizationRequiredError):
        await create_mcp_http_auth(config)
