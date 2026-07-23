from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from astrbot.api.event import ActiveReplyContext, filter
from astrbot.api.platform import MessageType
from astrbot.builtin_stars.astrbot.group_chat_context import GroupChatContext
from astrbot.core.config.default import CONFIG_METADATA_3
from astrbot.core.pipeline.context_utils import call_active_reply_hook
from astrbot.core.platform.active_reply import refresh_active_reply_method_options
from astrbot.core.star.star import StarMetadata, star_map
from astrbot.core.star.star_handler import star_handlers_registry


def make_group_chat_context(method: str = "custom_method"):
    context = MagicMock()
    context.get_config.return_value = {
        "provider_ltm_settings": {
            "image_caption": False,
            "active_reply": {
                "enable": True,
                "method": method,
                "possibility_reply": 0.0,
                "whitelist": [],
            },
        },
        "provider_settings": {"image_caption_prompt": ""},
    }
    event = MagicMock()
    event.unified_msg_origin = "test:group:1"
    event.get_message_type.return_value = MessageType.GROUP_MESSAGE
    event.is_at_or_wake_command = False
    event.get_group_id.return_value = "group-1"
    event.plugins_name = None
    return GroupChatContext(MagicMock(), context), event


def test_active_reply_hook_is_exported():
    assert callable(filter.on_active_reply)
    assert callable(filter.active_reply_method)
    assert callable(filter.register_active_reply_method)
    assert ActiveReplyContext(method="custom").should_reply is None


def test_active_reply_method_registration_updates_config_options():
    original_handlers = list(star_handlers_registry)
    original_handler_map = dict(star_handlers_registry.star_handlers_map)
    original_star_map = dict(star_map)
    original_options = list(
        CONFIG_METADATA_3["ext_group"]["metadata"]["ltm"]["items"][
            "provider_ltm_settings.active_reply.method"
        ]["options"]
    )
    try:
        star_handlers_registry.clear()
        star_map.clear()

        async def custom_active_reply(_event, _context):
            return True

        module_path = custom_active_reply.__module__
        star_map[module_path] = StarMetadata(
            name="Test Active Reply", module_path=module_path
        )
        filter.active_reply_method("custom_method")(custom_active_reply)
        handler = next(
            handler
            for handler in star_handlers_registry
            if handler.handler is custom_active_reply
        )
        assert handler.extras_configs["active_reply_method"] == "custom_method"

        refresh_active_reply_method_options()

        options = CONFIG_METADATA_3["ext_group"]["metadata"]["ltm"]["items"][
            "provider_ltm_settings.active_reply.method"
        ]["options"]
        assert options == ["possibility_reply", "custom_method"]
    finally:
        star_handlers_registry.clear()
        for handler in original_handlers:
            star_handlers_registry.append(handler)
        star_handlers_registry.star_handlers_map.clear()
        star_handlers_registry.star_handlers_map.update(original_handler_map)
        star_map.clear()
        star_map.update(original_star_map)
        CONFIG_METADATA_3["ext_group"]["metadata"]["ltm"]["items"][
            "provider_ltm_settings.active_reply.method"
        ]["options"] = original_options


@pytest.mark.asyncio
async def test_active_reply_hook_dispatches_registered_handler(monkeypatch):
    _, event = make_group_chat_context()
    active_reply_context = ActiveReplyContext(method="custom_method")

    async def hook(_event, context):
        assert context is active_reply_context
        return True

    handler = SimpleNamespace(
        handler=hook,
        handler_module_path="test_active_reply_plugin",
        handler_name="on_active_reply",
        extras_configs={"active_reply_method": "custom_method"},
    )
    metadata = StarMetadata(
        name="Test Active Reply", module_path=handler.handler_module_path
    )
    monkeypatch.setitem(star_map, handler.handler_module_path, metadata)
    monkeypatch.setattr(
        star_handlers_registry,
        "get_handlers_by_event_type",
        MagicMock(return_value=[handler]),
    )

    result = await call_active_reply_hook(event, active_reply_context)

    assert result is True


@pytest.mark.asyncio
async def test_active_reply_hook_can_enable_custom_method(monkeypatch):
    group_context, event = make_group_chat_context()

    async def hook(_event, active_reply_context):
        assert active_reply_context.method == "custom_method"
        return True

    hook_mock = AsyncMock(side_effect=hook)
    monkeypatch.setattr(
        "astrbot.builtin_stars.astrbot.group_chat_context.call_active_reply_hook",
        hook_mock,
    )

    assert await group_context.need_active_reply(event) is True
    hook_mock.assert_awaited_once()
    assert isinstance(hook_mock.await_args.args[1], ActiveReplyContext)


@pytest.mark.asyncio
async def test_active_reply_hook_can_disable_builtin_method(monkeypatch):
    group_context, event = make_group_chat_context("possibility_reply")

    hook_mock = AsyncMock(return_value=False)
    monkeypatch.setattr(
        "astrbot.builtin_stars.astrbot.group_chat_context.call_active_reply_hook",
        hook_mock,
    )

    assert await group_context.need_active_reply(event) is False
    hook_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_active_reply_hook_none_uses_builtin_method(monkeypatch):
    group_context, event = make_group_chat_context("possibility_reply")

    hook_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "astrbot.builtin_stars.astrbot.group_chat_context.call_active_reply_hook",
        hook_mock,
    )
    monkeypatch.setattr(
        "astrbot.builtin_stars.astrbot.group_chat_context.random.random",
        lambda: 0.0,
    )

    assert await group_context.need_active_reply(event) is False
    hook_mock.assert_awaited_once()
