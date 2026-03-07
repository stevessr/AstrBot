from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from quart import Quart

from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.config.default import DEFAULT_CONFIG
from astrbot.dashboard.routes.config import ConfigRoute
from astrbot.dashboard.routes.route import RouteContext


@pytest.fixture
def line_config_route_app(tmp_path):
    config_path = tmp_path / "cmd_config.json"
    config = AstrBotConfig(config_path=str(config_path), default_config=DEFAULT_CONFIG)
    app = Quart(__name__)
    platform_manager = SimpleNamespace(load_platform=AsyncMock())
    core_lifecycle = SimpleNamespace(
        astrbot_config=config,
        astrbot_config_mgr=SimpleNamespace(
            default_conf=config, confs={"default": config}
        ),
        umop_config_router=SimpleNamespace(),
        platform_manager=platform_manager,
    )
    ConfigRoute(RouteContext(config=config, app=app), core_lifecycle)
    return app, config, platform_manager


@pytest.mark.asyncio
async def test_post_new_platform_rejects_invalid_line_unified_webhook_mode(
    line_config_route_app,
):
    app, config, platform_manager = line_config_route_app
    test_client = app.test_client()

    response = await test_client.post(
        "/api/config/platform/new",
        json={
            "id": "line-test",
            "type": "line",
            "enable": True,
            "channel_access_token": "token",
            "channel_secret": "secret",
            "unified_webhook_mode": False,
        },
    )
    data = await response.get_json()

    assert response.status_code == 200
    assert data["status"] == "error"
    assert "格式校验未通过" in data["message"]
    assert "LINE 仅支持统一 Webhook 模式" in data["message"]
    platform_manager.load_platform.assert_not_awaited()

    reloaded_config = AstrBotConfig(
        config_path=config.config_path,
        default_config=DEFAULT_CONFIG,
    )
    assert reloaded_config["platform"] == []


@pytest.mark.asyncio
async def test_post_new_platform_accepts_valid_line_unified_webhook_mode(
    line_config_route_app,
):
    app, config, platform_manager = line_config_route_app
    test_client = app.test_client()

    response = await test_client.post(
        "/api/config/platform/new",
        json={
            "id": "line-test",
            "type": "line",
            "enable": True,
            "channel_access_token": "token",
            "channel_secret": "secret",
            "unified_webhook_mode": True,
        },
    )
    data = await response.get_json()

    assert response.status_code == 200
    assert data["status"] == "ok"
    platform_manager.load_platform.assert_awaited_once()

    reloaded_config = AstrBotConfig(
        config_path=config.config_path,
        default_config=DEFAULT_CONFIG,
    )
    assert len(reloaded_config["platform"]) == 1
    saved_platform = reloaded_config["platform"][0]
    assert saved_platform["type"] == "line"
    assert saved_platform["unified_webhook_mode"] is True
    assert saved_platform["webhook_uuid"]
