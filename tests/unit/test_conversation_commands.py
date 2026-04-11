import datetime
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from astrbot.builtin_stars.builtin_commands.commands.conversation import (
    ConversationCommands,
)
from astrbot.core.db.po import Conversation
from astrbot.core.provider.entities import LLMResponse
from astrbot.core.provider.provider import Provider


class DummyEvent:
    def __init__(self) -> None:
        self.unified_msg_origin = "test_platform:FriendMessage:test-session"
        self.role = "member"
        self._result = None
        self._extras: dict[str, object] = {}

    def get_group_id(self):
        return None

    def get_sender_id(self):
        return "tester"

    def get_platform_id(self):
        return "test_platform"

    def set_result(self, result) -> None:
        self._result = result

    def get_result_text(self) -> str:
        return self._result.get_plain_text()

    def set_extra(self, key: str, value) -> None:
        self._extras[key] = value

    def get_extra(self, key: str, default=None):
        return self._extras.get(key, default)


@pytest.mark.asyncio
async def test_compact_requires_current_conversation(mock_context, mock_provider):
    mock_context.get_using_provider = MagicMock(return_value=mock_provider)
    mock_context.get_config = MagicMock(
        return_value={
            "provider_settings": {
                "context_limit_reached_strategy": "truncate_by_turns",
                "max_context_length": 20,
                "dequeue_context_length": 1,
            }
        }
    )
    mock_context.conversation_manager.get_curr_conversation_id = AsyncMock(
        return_value=None
    )

    commands = ConversationCommands(mock_context)
    event = DummyEvent()

    await commands.compact(event)

    assert "当前未处于对话状态" in event.get_result_text()


@pytest.mark.asyncio
async def test_compact_saves_snapshot_and_updates_conversation(
    mock_context,
    mock_provider,
):
    history = [
        {"role": "user", "content": "first user"},
        {"role": "assistant", "content": "first assistant"},
        {"role": "user", "content": "second user"},
        {"role": "assistant", "content": "second assistant"},
    ]
    mock_context.get_using_provider = MagicMock(return_value=mock_provider)
    mock_context.get_config = MagicMock(
        return_value={
            "provider_settings": {
                "context_limit_reached_strategy": "truncate_by_turns",
                "max_context_length": 20,
                "dequeue_context_length": 1,
            }
        }
    )
    mock_context.conversation_manager.get_curr_conversation_id = AsyncMock(
        return_value="conv-1"
    )
    mock_context.conversation_manager.get_conversation = AsyncMock(
        return_value=Conversation(
            platform_id="test_platform",
            user_id="test-user",
            cid="conv-1",
            history=json.dumps(history),
            token_usage=128,
        )
    )
    mock_context.conversation_manager.save_compression_snapshot = AsyncMock()
    mock_context.conversation_manager.update_conversation = AsyncMock()

    commands = ConversationCommands(mock_context)
    event = DummyEvent()

    await commands.compact(event)

    assert mock_context.conversation_manager.save_compression_snapshot.await_count == 1
    assert mock_context.conversation_manager.update_conversation.await_count == 1
    update_args = mock_context.conversation_manager.update_conversation.await_args
    assert update_args.args[0] == event.unified_msg_origin
    assert update_args.args[1] == "conv-1"
    assert len(update_args.args[2]) < len(history)
    assert update_args.kwargs["token_usage"] > 0
    assert event.get_extra("_clean_ltm_session") is True
    assert "/history snapshot 1" in event.get_result_text()


@pytest.mark.asyncio
async def test_compact_uses_current_chat_provider_for_llm_summary_when_unset(
    mock_context,
    mock_provider,
):
    history = [
        {"role": "user", "content": "first user"},
        {"role": "assistant", "content": "first assistant"},
        {"role": "user", "content": "second user"},
        {"role": "assistant", "content": "second assistant"},
        {"role": "user", "content": "third user"},
        {"role": "assistant", "content": "third assistant"},
    ]
    mock_provider.text_chat = AsyncMock(
        return_value=LLMResponse(
            role="assistant",
            completion_text="compressed summary",
        )
    )
    mock_context.get_using_provider = MagicMock(return_value=mock_provider)
    mock_context.get_config = MagicMock(
        return_value={
            "provider_settings": {
                "context_limit_reached_strategy": "llm_compress",
                "max_context_length": -1,
                "dequeue_context_length": 1,
                "llm_compress_keep_recent": 2,
                "llm_compress_provider_id": "",
            }
        }
    )
    mock_context.conversation_manager.get_curr_conversation_id = AsyncMock(
        return_value="conv-1"
    )
    mock_context.conversation_manager.get_conversation = AsyncMock(
        return_value=Conversation(
            platform_id="test_platform",
            user_id="test-user",
            cid="conv-1",
            history=json.dumps(history),
            token_usage=128,
        )
    )
    mock_context.conversation_manager.save_compression_snapshot = AsyncMock()
    mock_context.conversation_manager.update_conversation = AsyncMock()

    commands = ConversationCommands(mock_context)
    event = DummyEvent()

    await commands.compact(event)

    mock_provider.text_chat.assert_awaited_once()
    update_args = mock_context.conversation_manager.update_conversation.await_args
    compressed_history = update_args.args[2]
    assert any(
        item["role"] == "user"
        and "Our previous history conversation summary: compressed summary"
        in item["content"]
        for item in compressed_history
    )
    assert "LLM 摘要压缩" in event.get_result_text()


@pytest.mark.asyncio
async def test_compact_prefers_configured_llm_compress_provider(mock_context):
    class SummaryProvider(Provider):
        def __init__(self, provider_id: str, summary_text: str) -> None:
            super().__init__(
                {
                    "id": provider_id,
                    "type": "openai_chat_completion",
                    "model": "gpt-4o-mini",
                    "max_context_tokens": 128000,
                },
                {},
            )
            self.set_model("gpt-4o-mini")
            self.summary_text = summary_text
            self.calls = 0

        def get_current_key(self) -> str:
            return "test-key"

        def set_key(self, key: str) -> None:  # noqa: ARG002
            return None

        async def get_models(self) -> list[str]:
            return ["gpt-4o-mini"]

        async def text_chat(self, **kwargs) -> LLMResponse:  # noqa: ARG002
            self.calls += 1
            return LLMResponse(
                role="assistant",
                completion_text=self.summary_text,
            )

    current_provider = SummaryProvider("chat-provider", "chat provider summary")
    compress_provider = SummaryProvider(
        "compress-provider",
        "configured provider summary",
    )
    history = [
        {"role": "user", "content": "first user"},
        {"role": "assistant", "content": "first assistant"},
        {"role": "user", "content": "second user"},
        {"role": "assistant", "content": "second assistant"},
        {"role": "user", "content": "third user"},
        {"role": "assistant", "content": "third assistant"},
    ]

    mock_context.get_using_provider = MagicMock(return_value=current_provider)
    mock_context.get_provider_by_id = MagicMock(return_value=compress_provider)
    mock_context.get_config = MagicMock(
        return_value={
            "provider_settings": {
                "context_limit_reached_strategy": "llm_compress",
                "max_context_length": -1,
                "dequeue_context_length": 1,
                "llm_compress_keep_recent": 2,
                "llm_compress_provider_id": "compress-provider",
            }
        }
    )
    mock_context.conversation_manager.get_curr_conversation_id = AsyncMock(
        return_value="conv-1"
    )
    mock_context.conversation_manager.get_conversation = AsyncMock(
        return_value=Conversation(
            platform_id="test_platform",
            user_id="test-user",
            cid="conv-1",
            history=json.dumps(history),
            token_usage=128,
        )
    )
    mock_context.conversation_manager.save_compression_snapshot = AsyncMock()
    mock_context.conversation_manager.update_conversation = AsyncMock()

    commands = ConversationCommands(mock_context)
    event = DummyEvent()

    await commands.compact(event)

    assert current_provider.calls == 0
    assert compress_provider.calls == 1
    update_args = mock_context.conversation_manager.update_conversation.await_args
    compressed_history = update_args.args[2]
    assert any(
        item["role"] == "user"
        and "Our previous history conversation summary: configured provider summary"
        in item["content"]
        for item in compressed_history
    )
    assert "LLM 摘要压缩" in event.get_result_text()


@pytest.mark.asyncio
async def test_history_snapshot_missing(mock_context, mock_provider):
    mock_context.get_using_provider = MagicMock(return_value=mock_provider)
    mock_context.conversation_manager.get_curr_conversation_id = AsyncMock(
        return_value="conv-1"
    )
    mock_context.conversation_manager.get_human_readable_snapshot_context = AsyncMock(
        return_value=([], 0, None)
    )

    commands = ConversationCommands(mock_context)
    event = DummyEvent()

    await commands.his(event, "snapshot", 2, 1)

    assert "未找到第 2 个压缩快照" in event.get_result_text()


@pytest.mark.asyncio
async def test_history_snapshot_displays_snapshot_page(mock_context, mock_provider):
    mock_context.get_using_provider = MagicMock(return_value=mock_provider)
    mock_context.conversation_manager.get_curr_conversation_id = AsyncMock(
        return_value="conv-1"
    )
    snapshot = MagicMock()
    snapshot.created_at = datetime.datetime(
        2026,
        4,
        9,
        tzinfo=datetime.timezone.utc,
    )
    mock_context.conversation_manager.get_human_readable_snapshot_context = AsyncMock(
        return_value=(["User: hello", "Assistant: hi"], 3, snapshot)
    )

    commands = ConversationCommands(mock_context)
    event = DummyEvent()

    await commands.his(event, "snapshot", 1, 2)

    result_text = event.get_result_text()
    assert "压缩前快照 #1" in result_text
    assert "第 2 页 | 共 3 页" in result_text
    assert "/history snapshot 1 2" in result_text


@pytest.mark.asyncio
async def test_history_page_argument_remains_compatible(mock_context, mock_provider):
    mock_context.get_using_provider = MagicMock(return_value=mock_provider)
    mock_context.conversation_manager.get_curr_conversation_id = AsyncMock(
        return_value="conv-1"
    )
    mock_context.conversation_manager.get_human_readable_context = AsyncMock(
        return_value=(["User: page-two"], 4)
    )

    commands = ConversationCommands(mock_context)
    event = DummyEvent()

    await commands.his(event, 2)

    mock_context.conversation_manager.get_human_readable_context.assert_awaited_once_with(
        event.unified_msg_origin,
        "conv-1",
        2,
        6,
    )
    assert "第 2 页 | 共 4 页" in event.get_result_text()
