import asyncio

import pytest

from astrbot.core.platform.sources.line.line_adapter import LinePlatformAdapter


@pytest.mark.platform
class TestLinePlatformAdapter:
    def test_init_accepts_unified_webhook_mode_true(
        self,
        event_queue: asyncio.Queue,
        platform_settings: dict,
    ):
        config = {
            "id": "line-test",
            "type": "line",
            "enable": True,
            "channel_access_token": "token",
            "channel_secret": "secret",
            "unified_webhook_mode": True,
            "webhook_uuid": "abc123",
        }
        original_config = dict(config)

        adapter = LinePlatformAdapter(config, platform_settings, event_queue)

        assert adapter.config["unified_webhook_mode"] is True
        assert config == original_config

    def test_init_rejects_unified_webhook_mode_false_without_mutating_config(
        self,
        event_queue: asyncio.Queue,
        platform_settings: dict,
    ):
        config = {
            "id": "line-test",
            "type": "line",
            "enable": True,
            "channel_access_token": "token",
            "channel_secret": "secret",
            "unified_webhook_mode": False,
            "webhook_uuid": "abc123",
        }
        original_config = dict(config)

        with pytest.raises(
            ValueError,
            match="LINE 仅支持统一 Webhook 模式",
        ):
            LinePlatformAdapter(config, platform_settings, event_queue)

        assert config == original_config
