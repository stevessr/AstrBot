import json
from pathlib import Path

import pytest
from mcp.shared.auth import OAuthToken

from astrbot.core.agent import mcp_oauth
from astrbot.core.agent.mcp_oauth import (
    MCPConfigTokenStorage,
    MCPOAuthPendingFlow,
)
from astrbot.core.provider.func_tool_manager import FunctionToolManager


@pytest.mark.asyncio
async def test_mcp_oauth_tokens_are_stored_in_matching_mcp_config(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("ASTRBOT_ROOT", str(tmp_path))
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    mcp_config_path = data_dir / "mcp_server.json"
    mcp_config_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "demo": {
                        "transport": "streamable_http",
                        "url": "https://example.com/mcp",
                        "oauth2": {
                            "grant_type": "authorization_code",
                            "client_id": "demo-client",
                        },
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    runtime_config = {
        "transport": "streamable_http",
        "url": "https://example.com/mcp",
        "oauth2": {
            "grant_type": "authorization_code",
            "client_id": "demo-client",
        },
    }
    storage = MCPConfigTokenStorage.from_mcp_config(
        runtime_config,
        server_name="demo",
    )

    await storage.set_tokens(
        OAuthToken(
            access_token="access-token",
            refresh_token="refresh-token",
            expires_in=3600,
        )
    )

    saved_config = json.loads(mcp_config_path.read_text(encoding="utf-8"))
    oauth_config = saved_config["mcpServers"]["demo"]["oauth2"]
    assert oauth_config["access_token"] == "access-token"
    assert oauth_config["refresh_token"] == "refresh-token"
    assert oauth_config["token_type"] == "Bearer"
    assert isinstance(oauth_config["token_expires_at"], float)
    assert not (data_dir / "mcp_oauth").exists()
    assert runtime_config["oauth2"]["access_token"] == "access-token"
    assert runtime_config["oauth2"]["refresh_token"] == "refresh-token"

    tokens = await storage.get_tokens()
    assert tokens is not None
    assert tokens.access_token == "access-token"
    assert tokens.refresh_token == "refresh-token"


@pytest.mark.asyncio
async def test_pending_flow_logs_authorization_url_when_enabled(monkeypatch):
    logged = []

    def fake_log(authorization_url, *, server_name=None):
        logged.append((authorization_url, server_name))

    monkeypatch.setattr(mcp_oauth, "log_mcp_oauth_authorization_url", fake_log)

    flow = MCPOAuthPendingFlow(
        flow_id="flow",
        config={},
        redirect_uri="http://127.0.0.1:6185/mcp/oauth/callback",
        server_name="demo",
        log_authorization=True,
    )

    await flow.handle_redirect("https://auth.example.com/login?state=oauth-state")

    assert logged == [("https://auth.example.com/login?state=oauth-state", "demo")]
    assert flow.oauth_state == "oauth-state"
    assert flow.status == "awaiting_user"


@pytest.mark.asyncio
async def test_function_tool_manager_starts_log_oauth_flow_on_invalid_token(
    monkeypatch,
):
    manager = FunctionToolManager()
    calls = []

    async def fake_connect_to_server(self, config, name):
        raise mcp_oauth.MCPOAuthAuthorizationRequiredError("token expired")

    async def fake_start_authorization(config, **kwargs):
        calls.append({"config": config, **kwargs})

    monkeypatch.setattr(
        "astrbot.core.provider.func_tool_manager.MCPClient.connect_to_server",
        fake_connect_to_server,
    )
    monkeypatch.setattr(
        manager._mcp_oauth_manager,
        "start_authorization",
        fake_start_authorization,
    )

    config = {
        "transport": "streamable_http",
        "url": "https://example.com/mcp",
        "oauth2": {"grant_type": "authorization_code"},
    }

    with pytest.raises(mcp_oauth.MCPOAuthAuthorizationRequiredError):
        await manager._init_mcp_client("demo", config)

    assert calls == [
        {
            "config": config,
            "callback_base_url": "http://127.0.0.1:6185",
            "force": True,
            "server_name": "demo",
            "log_authorization": True,
        }
    ]
