import asyncio
import importlib
import sys

import pytest

from astrbot.api.event import MessageChain
from astrbot.api.message_components import Image, Plain, Record, Video
from astrbot.core.platform.message_session import MessageSession
from astrbot.core.platform.message_type import MessageType
from tests.fixtures.mocks.botpy import create_mock_botpy_modules


@pytest.fixture()
def qqofficial_modules(monkeypatch):
    modules = create_mock_botpy_modules()
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)

    sys.modules.pop(
        "astrbot.core.platform.sources.qqofficial.qqofficial_message_event",
        None,
    )
    sys.modules.pop(
        "astrbot.core.platform.sources.qqofficial.qqofficial_platform_adapter",
        None,
    )

    message_event_module = importlib.import_module(
        "astrbot.core.platform.sources.qqofficial.qqofficial_message_event"
    )
    platform_module = importlib.import_module(
        "astrbot.core.platform.sources.qqofficial.qqofficial_platform_adapter"
    )
    return message_event_module, platform_module


@pytest.fixture()
def adapter(qqofficial_modules, monkeypatch):
    _message_event_module, platform_module = qqofficial_modules
    monkeypatch.setenv("ASTRBOT_DISABLE_METRICS", "1")
    event_queue = asyncio.Queue()
    adapter = platform_module.QQOfficialPlatformAdapter(
        {
            "appid": "appid",
            "secret": "secret",
            "enable_group_c2c": True,
            "enable_guild_direct_message": True,
            "id": "qq-official-test",
        },
        {},
        event_queue,
    )
    return adapter


@pytest.mark.asyncio
async def test_send_by_session_group_text(adapter):
    adapter.remember_session_message_id("group-1", "msg-1")
    adapter.remember_session_scene("group-1", "group")
    adapter.client.api.post_group_message.return_value = {"id": "msg-2"}

    await adapter.send_by_session(
        MessageSession("qq-official-test", MessageType.GROUP_MESSAGE, "group-1"),
        MessageChain([Plain("hello group")]),
    )

    adapter.client.api.post_group_message.assert_awaited_once()
    kwargs = adapter.client.api.post_group_message.await_args.kwargs
    assert kwargs["group_openid"] == "group-1"
    assert kwargs["content"] == "hello group"
    assert kwargs["msg_id"] == "msg-1"
    assert kwargs["msg_seq"] >= 1
    assert adapter._session_last_message_id["group-1"] == "msg-2"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("component", "scene", "message_type", "file_type"),
    [
        (Image(file="image-data"), "group", MessageType.GROUP_MESSAGE, 1),
        (Record(file="record.wav"), "group", MessageType.GROUP_MESSAGE, 3),
        (Video(file="video.mp4"), "group", MessageType.GROUP_MESSAGE, 2),
        (Image(file="image-data"), "friend", MessageType.FRIEND_MESSAGE, 1),
        (Record(file="record.wav"), "friend", MessageType.FRIEND_MESSAGE, 3),
        (Video(file="video.mp4"), "friend", MessageType.FRIEND_MESSAGE, 2),
    ],
)
async def test_send_by_session_group_and_c2c_media(
    adapter,
    qqofficial_modules,
    monkeypatch,
    component,
    scene,
    message_type,
    file_type,
):
    message_event_module, _platform_module = qqofficial_modules
    session_id = "group-1" if message_type == MessageType.GROUP_MESSAGE else "user-1"
    adapter.remember_session_message_id(session_id, "msg-1")
    adapter.remember_session_scene(session_id, scene)

    parsed = message_event_module.QQOfficialMediaPayload(plain_text="caption")
    if file_type == 1:
        parsed.image_base64 = "image-b64"
    elif file_type == 3:
        parsed.record_file_path = "record.silk"
    else:
        parsed.video_file_path = "video.mp4"

    async def fake_parse(_message_chain):
        return parsed

    uploaded = []
    media = message_event_module.Media(file_uuid="uuid", file_info="info", ttl=0)

    async def fake_upload(self, file_source: str, incoming_file_type: int, **kwargs):
        uploaded.append((file_source, incoming_file_type, kwargs))
        return media

    monkeypatch.setattr(
        message_event_module.QQOfficialMessageEvent,
        "_parse_to_qqofficial",
        staticmethod(fake_parse),
    )
    monkeypatch.setattr(
        message_event_module.QQOfficialMessageEvent,
        "upload_group_and_c2c_media",
        fake_upload,
    )

    if message_type == MessageType.GROUP_MESSAGE:
        adapter.client.api.post_group_message.return_value = {"id": "sent-group"}
        chain = MessageChain([component, Plain("caption")])
        await adapter.send_by_session(
            MessageSession("qq-official-test", message_type, session_id),
            chain,
        )
        kwargs = adapter.client.api.post_group_message.await_args.kwargs
        assert kwargs["msg_type"] == 7
        assert kwargs["content"] == "caption"
        assert "markdown" not in kwargs
        assert kwargs["media"] == media
        assert uploaded == [(uploaded[0][0], file_type, {"group_openid": session_id})]
    else:
        called = {}

        async def fake_post_c2c(self, openid: str, **kwargs):
            called["openid"] = openid
            called["kwargs"] = kwargs
            return {"id": "sent-c2c"}

        monkeypatch.setattr(
            message_event_module.QQOfficialMessageEvent,
            "post_c2c_message",
            fake_post_c2c,
        )
        chain = MessageChain([component, Plain("caption")])
        await adapter.send_by_session(
            MessageSession("qq-official-test", message_type, session_id),
            chain,
        )
        assert called["openid"] == session_id
        assert called["kwargs"]["msg_type"] == 7
        assert called["kwargs"]["content"] == "caption"
        assert "markdown" not in called["kwargs"]
        assert called["kwargs"]["media"] == media
        assert uploaded == [(uploaded[0][0], file_type, {"openid": session_id})]


@pytest.mark.asyncio
async def test_send_by_session_warns_without_cached_msg_id(adapter, caplog):
    with caplog.at_level("WARNING"):
        await adapter.send_by_session(
            MessageSession("qq-official-test", MessageType.GROUP_MESSAGE, "group-1"),
            MessageChain([Plain("hello")]),
        )

    assert "No cached msg_id for session" in caplog.text
    adapter.client.api.post_group_message.assert_not_called()


@pytest.mark.asyncio
async def test_send_by_session_channel_scene_keeps_compatibility(
    adapter,
    qqofficial_modules,
    monkeypatch,
):
    message_event_module, _platform_module = qqofficial_modules
    adapter.remember_session_message_id("channel-1", "msg-1")
    adapter.remember_session_scene("channel-1", "channel")
    adapter.client.api.post_message.return_value = {"id": "channel-msg"}

    parsed = message_event_module.QQOfficialMediaPayload(
        plain_text="channel",
        image_file_path="/tmp/test.png",
    )

    async def fake_parse(_message_chain):
        return parsed

    monkeypatch.setattr(
        message_event_module.QQOfficialMessageEvent,
        "_parse_to_qqofficial",
        staticmethod(fake_parse),
    )

    await adapter.send_by_session(
        MessageSession("qq-official-test", MessageType.GROUP_MESSAGE, "channel-1"),
        MessageChain([Plain("channel")]),
    )

    adapter.client.api.post_message.assert_awaited_once()
    kwargs = adapter.client.api.post_message.await_args.kwargs
    assert kwargs["channel_id"] == "channel-1"
    assert kwargs["file_image"] == "/tmp/test.png"


@pytest.mark.asyncio
async def test_send_by_session_experimental_file_failure_stops_send(
    adapter,
    qqofficial_modules,
    monkeypatch,
    caplog,
):
    message_event_module, _platform_module = qqofficial_modules
    adapter.remember_session_message_id("group-1", "msg-1")
    adapter.remember_session_scene("group-1", "group")

    parsed = message_event_module.QQOfficialMediaPayload(
        plain_text="caption",
        file_file_path="/tmp/demo.txt",
        experimental_file=True,
    )

    async def fake_parse(_message_chain):
        return parsed

    async def fake_upload(self, file_source: str, file_type: int, **kwargs):
        assert file_type == 4
        return None

    monkeypatch.setattr(
        message_event_module.QQOfficialMessageEvent,
        "_parse_to_qqofficial",
        staticmethod(fake_parse),
    )
    monkeypatch.setattr(
        message_event_module.QQOfficialMessageEvent,
        "upload_group_and_c2c_media",
        fake_upload,
    )

    with caplog.at_level("WARNING"):
        await adapter.send_by_session(
            MessageSession("qq-official-test", MessageType.GROUP_MESSAGE, "group-1"),
            MessageChain([Plain("caption")]),
        )

    assert "实验性文件发送失败" in caplog.text
    adapter.client.api.post_group_message.assert_not_called()
