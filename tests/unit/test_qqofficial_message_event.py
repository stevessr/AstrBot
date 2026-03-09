import asyncio
import base64
import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from astrbot.api.event import MessageChain
from astrbot.api.message_components import File, Image, Plain, Record, Video
from tests.fixtures.mocks.botpy import create_mock_botpy_modules


@pytest.fixture()
def qqofficial_message_event_module(monkeypatch):
    modules = create_mock_botpy_modules()
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)

    sys.modules.pop(
        "astrbot.core.platform.sources.qqofficial.qqofficial_message_event",
        None,
    )
    return importlib.import_module(
        "astrbot.core.platform.sources.qqofficial.qqofficial_message_event"
    )


@pytest.mark.asyncio
async def test_parse_to_qqofficial_keeps_image_and_record_capability(
    qqofficial_message_event_module,
    monkeypatch,
    tmp_path,
):
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"image-bytes")
    record_path = tmp_path / "record.wav"
    record_path.write_bytes(b"record-bytes")

    async def fake_wav_to_tencent_silk(_wav_path: str, silk_path: str) -> int:
        await asyncio.to_thread(Path(silk_path).write_bytes, b"silk")
        return 1

    monkeypatch.setattr(
        qqofficial_message_event_module,
        "wav_to_tencent_silk",
        fake_wav_to_tencent_silk,
    )

    chain = MessageChain(
        [
            Plain("hello"),
            Image(file=str(image_path)),
            Record(file=str(record_path)),
        ]
    )

    parsed = await qqofficial_message_event_module.QQOfficialMessageEvent._parse_to_qqofficial(
        chain
    )

    assert parsed.plain_text == "hello"
    assert base64.b64decode(parsed.image_base64) == b"image-bytes"
    assert parsed.record_file_path is not None
    assert await asyncio.to_thread(os.path.exists, parsed.record_file_path)


@pytest.mark.asyncio
async def test_parse_to_qqofficial_supports_video_and_file_experimental(
    qqofficial_message_event_module,
    tmp_path,
):
    video_path = tmp_path / "demo.mp4"
    video_path.write_bytes(b"video")
    file_path = tmp_path / "demo.txt"
    file_path.write_text("payload", encoding="utf-8")

    chain = MessageChain(
        [
            Plain("caption"),
            Video(file=str(video_path)),
            File(name="demo.txt", file=str(file_path)),
        ]
    )

    parsed = await qqofficial_message_event_module.QQOfficialMessageEvent._parse_to_qqofficial(
        chain
    )

    assert parsed.plain_text == "caption"
    assert parsed.video_file_path == str(video_path.resolve())
    assert parsed.file_file_path == str(file_path.resolve())
    assert parsed.experimental_file is True


@pytest.mark.asyncio
async def test_prepare_group_or_c2c_payload_uses_media_msg_type_and_content(
    qqofficial_message_event_module,
):
    media = qqofficial_message_event_module.Media(
        file_uuid="uuid", file_info="info", ttl=0
    )

    async def fake_upload(self, file_source: str, file_type: int, **kwargs):
        assert file_source == "video.mp4"
        assert file_type == 2
        assert kwargs == {"group_openid": "group-1"}
        return media

    helper = SimpleNamespace(bot=SimpleNamespace())
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        qqofficial_message_event_module.QQOfficialMessageEvent,
        "upload_group_and_c2c_media",
        fake_upload,
    )
    try:
        parsed = qqofficial_message_event_module.QQOfficialMediaPayload(
            plain_text="说明文本",
            video_file_path="video.mp4",
        )
        payload = {
            "markdown": qqofficial_message_event_module.MarkdownPayload(
                content="说明文本"
            ),
            "msg_type": 2,
            "msg_id": "msg-1",
        }

        updated = await qqofficial_message_event_module.QQOfficialMessageEvent._prepare_group_or_c2c_payload(
            helper,
            payload,
            parsed,
            group_openid="group-1",
        )
    finally:
        monkeypatch.undo()

    assert updated is not None
    assert updated["msg_type"] == 7
    assert updated["content"] == "说明文本"
    assert updated["media"] == media
    assert "markdown" not in updated


@pytest.mark.asyncio
async def test_upload_group_and_c2c_media_logs_experimental_file_failure(
    qqofficial_message_event_module,
    caplog,
):
    helper = SimpleNamespace(
        bot=SimpleNamespace(
            api=SimpleNamespace(
                _http=SimpleNamespace(request=_async_return({"unexpected": True}))
            )
        )
    )

    with caplog.at_level("WARNING"):
        media = await qqofficial_message_event_module.QQOfficialMessageEvent.upload_group_and_c2c_media(
            helper,
            "https://example.com/demo.txt",
            4,
            openid="user-1",
        )

    assert media is None
    assert "实验性文件上传缺少必要字段" in caplog.text


def _async_return(value):
    async def _inner(*args, **kwargs):
        return value

    return _inner
