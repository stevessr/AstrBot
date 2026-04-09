import pytest

from astrbot.core.conversation_mgr import ConversationManager


class DummySharedPreferences:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    async def session_put(self, umo: str, key: str, value: str) -> None:
        self.values[(umo, key)] = value

    async def session_get(self, umo: str, key: str, default=None):
        return self.values.get((umo, key), default)

    async def session_remove(self, umo: str, key: str) -> None:
        self.values.pop((umo, key), None)


@pytest.mark.asyncio
async def test_conversation_manager_snapshot_pagination(temp_db, monkeypatch):
    import astrbot.core.conversation_mgr as conversation_mgr_module

    monkeypatch.setattr(conversation_mgr_module, "sp", DummySharedPreferences())

    manager = ConversationManager(temp_db)
    umo = "test_platform:FriendMessage:test-session"
    history = [
        {"role": "user", "content": "first user"},
        {"role": "assistant", "content": "first assistant"},
        {"role": "user", "content": "second user"},
        {"role": "assistant", "content": "second assistant"},
    ]
    conversation_id = await manager.new_conversation(
        umo,
        platform_id="test_platform",
        content=history,
    )

    snapshot = await manager.save_compression_snapshot(umo, conversation_id, history)

    page_1, total_pages_1, loaded_snapshot = await manager.get_human_readable_snapshot_context(
        umo,
        conversation_id,
        snapshot_index=1,
        page=1,
        page_size=2,
    )
    page_2, total_pages_2, _ = await manager.get_human_readable_snapshot_context(
        umo,
        conversation_id,
        snapshot_index=1,
        page=2,
        page_size=2,
    )

    assert loaded_snapshot is not None
    assert loaded_snapshot.snapshot_id == snapshot.snapshot_id
    assert total_pages_1 == 2
    assert total_pages_2 == 2
    assert page_1 == ["User: second user", "Assistant: second assistant"]
    assert page_2 == ["User: first user", "Assistant: first assistant"]


@pytest.mark.asyncio
async def test_conversation_manager_snapshot_index_returns_newest_first(
    temp_db,
    monkeypatch,
):
    import astrbot.core.conversation_mgr as conversation_mgr_module

    monkeypatch.setattr(conversation_mgr_module, "sp", DummySharedPreferences())

    manager = ConversationManager(temp_db)
    umo = "test_platform:FriendMessage:test-session"
    conversation_id = await manager.new_conversation(
        umo,
        platform_id="test_platform",
        content=[],
    )

    await manager.save_compression_snapshot(
        umo,
        conversation_id,
        [
            {"role": "user", "content": "older user"},
            {"role": "assistant", "content": "older assistant"},
        ],
    )
    await manager.save_compression_snapshot(
        umo,
        conversation_id,
        [
            {"role": "user", "content": "newer user"},
            {"role": "assistant", "content": "newer assistant"},
        ],
    )

    snapshots = await manager.get_compression_snapshots(umo, conversation_id)
    newest_context, _, newest_snapshot = await manager.get_human_readable_snapshot_context(
        umo,
        conversation_id,
        snapshot_index=1,
        page=1,
        page_size=10,
    )
    older_context, _, older_snapshot = await manager.get_human_readable_snapshot_context(
        umo,
        conversation_id,
        snapshot_index=2,
        page=1,
        page_size=10,
    )

    assert len(snapshots) == 2
    assert newest_snapshot is not None
    assert older_snapshot is not None
    assert newest_snapshot.snapshot_id == snapshots[0].snapshot_id
    assert older_snapshot.snapshot_id == snapshots[1].snapshot_id
    assert newest_context == ["User: newer user", "Assistant: newer assistant"]
    assert older_context == ["User: older user", "Assistant: older assistant"]
