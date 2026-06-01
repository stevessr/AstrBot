from types import SimpleNamespace

import pytest

from astrbot.builtin_stars.builtin_commands.commands.provider import ProviderCommands
from astrbot.core.provider.entities import ProviderMeta, ProviderType


class FakeProvider:
    def __init__(self, provider_id: str, model: str, models: list[str]) -> None:
        self.provider_id = provider_id
        self.model = model
        self.models = models

    def meta(self) -> ProviderMeta:
        return ProviderMeta(
            id=self.provider_id,
            model=self.model,
            type="fake",
            provider_type=ProviderType.CHAT_COMPLETION,
        )

    def get_model(self) -> str:
        return self.model

    def set_model(self, model_name: str) -> None:
        self.model = model_name

    async def get_models(self) -> list[str]:
        return self.models


class FakeEvent:
    unified_msg_origin = "test:FriendMessage:user"

    def __init__(self) -> None:
        self.result = None

    def set_result(self, result) -> None:
        self.result = result

    def result_text(self) -> str:
        assert self.result is not None
        return self.result.get_plain_text()


class FakeProviderManager:
    def __init__(self) -> None:
        self.switches: list[tuple[str, ProviderType, str | None]] = []

    async def set_provider(
        self,
        provider_id: str,
        provider_type: ProviderType,
        umo: str | None = None,
    ) -> None:
        self.switches.append((provider_id, provider_type, umo))


@pytest.mark.asyncio
async def test_model_ls_lists_current_provider_models() -> None:
    provider = FakeProvider("provider-a", "model-b", ["model-a", "model-b"])
    manager = FakeProviderManager()
    context = SimpleNamespace(
        provider_manager=manager,
        get_using_provider=lambda umo=None: provider,
        get_all_providers=lambda: [provider],
    )
    event = FakeEvent()

    await ProviderCommands(context).model_ls(event)

    text = event.result_text()
    assert "1. model-a" in text
    assert "2. model-b 👈" in text
    assert "Current model: model-b" in text
    assert event.result.use_t2i_ is False


@pytest.mark.asyncio
async def test_model_ls_switches_model_by_index() -> None:
    provider = FakeProvider("provider-a", "model-a", ["model-a", "model-b"])
    manager = FakeProviderManager()
    context = SimpleNamespace(
        provider_manager=manager,
        get_using_provider=lambda umo=None: provider,
        get_all_providers=lambda: [provider],
    )
    event = FakeEvent()

    await ProviderCommands(context).model_ls(event, 2)

    assert provider.get_model() == "model-b"
    assert "成功切换模型" in event.result_text()
    assert "当前模型：[model-b]" in event.result_text()


@pytest.mark.asyncio
async def test_model_ls_switches_model_by_name_case_insensitive() -> None:
    provider = FakeProvider("provider-a", "model-a", ["model-a", "OpenAI/GPT-4O"])
    manager = FakeProviderManager()
    context = SimpleNamespace(
        provider_manager=manager,
        get_using_provider=lambda umo=None: provider,
        get_all_providers=lambda: [provider],
    )
    event = FakeEvent()

    await ProviderCommands(context).model_ls(event, "gpt-4o")

    assert provider.get_model() == "OpenAI/GPT-4O"
    assert "当前模型：[OpenAI/GPT-4O]" in event.result_text()


@pytest.mark.asyncio
async def test_model_ls_switches_provider_when_model_belongs_to_another_provider() -> (
    None
):
    provider_a = FakeProvider("provider-a", "model-a", ["model-a"])
    provider_b = FakeProvider("provider-b", "model-b", ["model-b", "model-c"])
    manager = FakeProviderManager()
    context = SimpleNamespace(
        provider_manager=manager,
        get_using_provider=lambda umo=None: provider_a,
        get_all_providers=lambda: [provider_a, provider_b],
    )
    event = FakeEvent()

    await ProviderCommands(context).model_ls(event, "model-c")

    assert provider_b.get_model() == "model-c"
    assert manager.switches == [
        ("provider-b", ProviderType.CHAT_COMPLETION, event.unified_msg_origin)
    ]
    assert "已自动切换提供商并设置模型" in event.result_text()


@pytest.mark.asyncio
async def test_model_ls_replies_when_no_provider_configured() -> None:
    manager = FakeProviderManager()
    context = SimpleNamespace(
        provider_manager=manager,
        get_using_provider=lambda umo=None: None,
        get_all_providers=lambda: [],
    )
    event = FakeEvent()

    await ProviderCommands(context).model_ls(event)

    assert event.result_text() == "未找到任何 LLM 提供商。请先配置。"
