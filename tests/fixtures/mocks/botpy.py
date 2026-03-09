"""botpy 模块 Mock 工具。

提供统一的 botpy 相关模块 mock 设置，避免在测试文件中重复定义。
"""

import sys
from dataclasses import dataclass
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest


class _BotpyIntents:
    def __init__(self, **kwargs) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)


class _BotpyAPI:
    def __init__(self) -> None:
        self.post_group_message = AsyncMock()
        self.post_message = AsyncMock()
        self.post_dms = AsyncMock()
        self._http = SimpleNamespace(request=AsyncMock())


class _BotpyClient:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs
        self.api = _BotpyAPI()

    async def start(self, *args, **kwargs):
        return None

    async def close(self):
        return None


class _BaseIncomingMessage:
    def __init__(self, **kwargs) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)


class _Message(_BaseIncomingMessage):
    pass


class _GroupMessage(_BaseIncomingMessage):
    pass


class _DirectMessage(_BaseIncomingMessage):
    pass


class _C2CMessage(_BaseIncomingMessage):
    pass


class _ServerError(Exception):
    pass


@dataclass
class _MarkdownPayload:
    content: str | None = None


@dataclass
class _Media:
    file_uuid: str
    file_info: str
    ttl: int = 0


class _MessagePayload(dict):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.__dict__.update(kwargs)


@dataclass
class _Route:
    method: str
    path: str
    params: dict

    def __init__(self, method: str, path: str, **params) -> None:
        self.method = method
        self.path = path
        self.params = params


class _FormData:
    pass


def create_mock_botpy_modules():
    """创建 botpy 相关的 mock 模块。"""
    botpy = ModuleType("botpy")
    message_mod = ModuleType("botpy.message")
    errors_mod = ModuleType("botpy.errors")
    http_mod = ModuleType("botpy.http")
    types_mod = ModuleType("botpy.types")
    types_message_mod = ModuleType("botpy.types.message")

    message_mod.Message = _Message
    message_mod.GroupMessage = _GroupMessage
    message_mod.DirectMessage = _DirectMessage
    message_mod.C2CMessage = _C2CMessage

    errors_mod.ServerError = _ServerError

    http_mod.Route = _Route
    http_mod._FormData = _FormData

    types_message_mod.MarkdownPayload = _MarkdownPayload
    types_message_mod.Media = _Media
    types_message_mod.Message = _MessagePayload
    types_message_mod.Embed = type("Embed", (), {})
    types_message_mod.Ark = type("Ark", (), {})
    types_message_mod.Reference = type("Reference", (), {})
    types_message_mod.Keyboard = type("Keyboard", (), {})

    types_mod.message = types_message_mod

    botpy.Intents = _BotpyIntents
    botpy.Client = _BotpyClient
    botpy.message = message_mod
    botpy.errors = errors_mod
    botpy.http = http_mod
    botpy.types = types_mod

    return {
        "botpy": botpy,
        "botpy.message": message_mod,
        "botpy.errors": errors_mod,
        "botpy.http": http_mod,
        "botpy.types": types_mod,
        "botpy.types.message": types_message_mod,
    }


@pytest.fixture(scope="module")
def mock_botpy_modules():
    """Mock botpy 相关模块的 fixture。"""
    modules = create_mock_botpy_modules()
    monkeypatch = pytest.MonkeyPatch()
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    yield modules
    monkeypatch.undo()


class MockBotpyBuilder:
    """构建 botpy 测试 mock 对象的工具类。"""

    @staticmethod
    def create_media(file_uuid: str = "file-uuid", file_info: str = "file-info"):
        return _Media(file_uuid=file_uuid, file_info=file_info, ttl=0)
