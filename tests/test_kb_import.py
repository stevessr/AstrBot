import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from quart import Quart

from astrbot.core import LogBroker
from astrbot.core.core_lifecycle import AstrBotCoreLifecycle
from astrbot.core.db.sqlite import SQLiteDatabase
from astrbot.core.exceptions import KnowledgeBaseUploadError
from astrbot.core.knowledge_base.kb_helper import KBHelper
from astrbot.core.knowledge_base.models import KBDocument
from astrbot.dashboard.routes.knowledge_base import KnowledgeBaseRoute
from astrbot.core.provider.provider import EmbeddingProvider
from astrbot.core.provider.provider import EmbeddingProvider, RemoteBatchFailedError
from astrbot.dashboard.server import AstrBotDashboard


@pytest_asyncio.fixture(scope="module")
async def core_lifecycle_td(tmp_path_factory):
    """Creates and initializes a core lifecycle instance with a temporary database."""
    tmp_db_path = tmp_path_factory.mktemp("data") / "test_data_kb.db"
    db = SQLiteDatabase(str(tmp_db_path))
    log_broker = LogBroker()
    core_lifecycle = AstrBotCoreLifecycle(log_broker, db)
    await core_lifecycle.initialize()

    # Mock kb_manager and kb_helper
    kb_manager = MagicMock()
    kb_helper = AsyncMock(spec=KBHelper)

    # Configure get_kb to be an async mock that returns kb_helper
    kb_manager.get_kb = AsyncMock(return_value=kb_helper)

    # Mock upload_document return value
    mock_doc = KBDocument(
        doc_id="test_doc_id",
        kb_id="test_kb_id",
        doc_name="test_file.txt",
        file_type="txt",
        file_size=100,
        file_path="",
        chunk_count=2,
        media_count=0,
    )
    kb_helper.upload_document.return_value = mock_doc

    # kb_manager.get_kb.return_value = kb_helper # Removed this line as it's handled above
    core_lifecycle.kb_manager = kb_manager

    try:
        yield core_lifecycle
    finally:
        try:
            _stop_res = core_lifecycle.stop()
            if asyncio.iscoroutine(_stop_res):
                await _stop_res
        except Exception:
            pass


@pytest.fixture(scope="module")
def app(core_lifecycle_td: AstrBotCoreLifecycle):
    """Creates a Quart app instance for testing."""
    shutdown_event = asyncio.Event()
    server = AstrBotDashboard(core_lifecycle_td, core_lifecycle_td.db, shutdown_event)
    return server.app


@pytest_asyncio.fixture(scope="module")
async def authenticated_header(app: Quart, core_lifecycle_td: AstrBotCoreLifecycle):
    """Handles login and returns an authenticated header."""
    test_client = app.test_client()
    response = await test_client.post(
        "/api/auth/login",
        json={
            "username": core_lifecycle_td.astrbot_config["dashboard"]["username"],
            "password": core_lifecycle_td.astrbot_config["dashboard"]["password"],
        },
    )
    data = await response.get_json()
    assert data["status"] == "ok"
    token = data["data"]["token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_import_documents(
    app: Quart, authenticated_header: dict, core_lifecycle_td: AstrBotCoreLifecycle
):
    """Tests the import documents functionality."""
    test_client = app.test_client()
    kb_helper = await core_lifecycle_td.kb_manager.get_kb("test_kb_id")
    kb_helper.upload_document.reset_mock()
    kb_helper.upload_document.side_effect = None

    # Test data
    import_data = {
        "kb_id": "test_kb_id",
        "documents": [
            {"file_name": "test_file_1.txt", "chunks": ["chunk1", "chunk2"]},
            {"file_name": "test_file_2.md", "chunks": ["chunk3", "chunk4", "chunk5"]},
        ],
    }

    # Send request
    response = await test_client.post(
        "/api/kb/document/import", json=import_data, headers=authenticated_header
    )

    # Verify response
    assert response.status_code == 200
    data = await response.get_json()
    assert data["status"] == "ok"
    assert "task_id" in data["data"]
    assert data["data"]["doc_count"] == 2

    task_id = data["data"]["task_id"]

    # Wait for background task to complete (mocked)
    # Since we mocked upload_document, it should be fast, but we might need to poll progress
    for _ in range(10):
        progress_response = await test_client.get(
            f"/api/kb/document/upload/progress?task_id={task_id}",
            headers=authenticated_header,
        )
        progress_data = await progress_response.get_json()
        if progress_data["data"]["status"] == "completed":
            break
        await asyncio.sleep(0.1)

    assert progress_data["data"]["status"] == "completed"
    result = progress_data["data"]["result"]
    assert result["success_count"] == 2
    assert result["failed_count"] == 0

    # Verify kb_helper.upload_document was called correctly
    assert kb_helper.upload_document.call_count == 2

    # Check first call arguments
    call_args_list = kb_helper.upload_document.call_args_list

    # First document
    args1, kwargs1 = call_args_list[0]
    assert kwargs1["file_name"] == "test_file_1.txt"
    assert kwargs1["pre_chunked_text"] == ["chunk1", "chunk2"]

    # Second document
    args2, kwargs2 = call_args_list[1]
    assert kwargs2["file_name"] == "test_file_2.md"
    assert kwargs2["pre_chunked_text"] == ["chunk3", "chunk4", "chunk5"]


@pytest.mark.asyncio
async def test_import_documents_returns_friendly_failure_message(
    core_lifecycle_td: AstrBotCoreLifecycle,
):
    kb_helper = await core_lifecycle_td.kb_manager.get_kb("test_kb_id")
    kb_helper.upload_document.reset_mock()
    kb_helper.upload_document.side_effect = KnowledgeBaseUploadError(
        stage="embedding",
        user_message=(
            "向量化失败：嵌入模型返回的向量数量与文本分块数量不一致（期望 2，实际 1）。"
        ),
        details={"expected_contents": 2, "actual_vectors": 1},
    )

    route = KnowledgeBaseRoute.__new__(KnowledgeBaseRoute)
    route.upload_progress = {}
    route.upload_tasks = {}

    await KnowledgeBaseRoute._background_import_task(
        route,
        task_id="task-1",
        kb_helper=kb_helper,
        documents=[{"file_name": "broken.txt", "chunks": ["chunk1", "chunk2"]}],
        batch_size=32,
        tasks_limit=3,
        max_retries=3,
    )

    assert route.upload_tasks["task-1"]["status"] == "completed"
    result = route.upload_tasks["task-1"]["result"]
    assert result["success_count"] == 0
    assert result["failed_count"] == 1
    assert result["failed"][0]["file_name"] == "broken.txt"
    assert result["failed"][0]["error"].startswith("broken.txt:")
    assert "向量化失败" in result["failed"][0]["error"]
    assert "期望 2，实际 1" in result["failed"][0]["error"]
    assert "not same nb of vectors as ids" not in result["failed"][0]["error"]
    assert kb_helper.upload_document.await_count == 1

    kb_helper.upload_document.side_effect = None


@pytest.mark.asyncio
async def test_import_documents_invalid_input(app: Quart, authenticated_header: dict):
    """Tests import documents with invalid input."""
    test_client = app.test_client()

    # Missing kb_id
    response = await test_client.post(
        "/api/kb/document/import", json={"documents": []}, headers=authenticated_header
    )
    data = await response.get_json()
    assert data["status"] == "error"
    assert "缺少参数 kb_id" in data["message"]

    # Missing documents
    response = await test_client.post(
        "/api/kb/document/import",
        json={"kb_id": "test_kb"},
        headers=authenticated_header,
    )
    data = await response.get_json()
    assert data["status"] == "error"
    assert "缺少参数 documents" in data["message"]

    # Invalid document format
    response = await test_client.post(
        "/api/kb/document/import",
        json={
            "kb_id": "test_kb",
            "documents": [{"file_name": "test"}],  # Missing chunks
        },
        headers=authenticated_header,
    )
    data = await response.get_json()
    assert data["status"] == "error"
    assert "文档格式错误" in data["message"]

    # Invalid chunks type
    response = await test_client.post(
        "/api/kb/document/import",
        json={
            "kb_id": "test_kb",
            "documents": [{"file_name": "test", "chunks": "not-a-list"}],
        },
        headers=authenticated_header,
    )
    data = await response.get_json()
    assert data["status"] == "error"
    assert "chunks 必须是列表" in data["message"]

    # Invalid chunks content
    response = await test_client.post(
        "/api/kb/document/import",
        json={
            "kb_id": "test_kb",
            "documents": [{"file_name": "test", "chunks": ["valid", ""]}],
        },
        headers=authenticated_header,
    )
    data = await response.get_json()
    assert data["status"] == "error"
    assert "chunks 必须是非空字符串列表" in data["message"]


class DummyEmbeddingProvider(EmbeddingProvider):
    def __init__(self):
        super().__init__({}, {})
        self.calls = 0
        self.error_message = ""
        self.remote_batch_calls = 0
        self.remote_batch_error: Exception | None = None
        self.remote_batch_result: list[list[float]] | None = None

    def supports_remote_batch(self) -> bool:
        return (
            self.remote_batch_result is not None or self.remote_batch_error is not None
        )

    async def _run_remote_batch_job(
        self, texts: list[str], progress_callback=None
    ) -> list[list[float]]:
        self.remote_batch_calls += 1
        if progress_callback:
            await progress_callback("batching", 1, 1)
            await progress_callback("batch_waiting", len(texts), len(texts))
        if self.remote_batch_error:
            raise self.remote_batch_error
        assert self.remote_batch_result is not None
        return self.remote_batch_result

    async def get_embedding(self, text: str) -> list[float]:
        return [0.0]

    async def get_embeddings(self, text: list[str]) -> list[list[float]]:
        self.calls += 1
        if self.calls == 1:
            raise Exception(self.error_message)
        return [[0.0] for _ in text]

    def get_dim(self) -> int:
        return 1


@pytest.mark.asyncio
async def test_extract_retry_after_seconds():
    provider = DummyEmbeddingProvider()
    assert (
        provider._extract_retry_after_seconds(Exception("Please retry in 25.776s."))
        == 25.776
    )
    assert provider._extract_retry_after_seconds(Exception("Retry-After: 12")) == 12.0
    assert provider._extract_retry_after_seconds(Exception("rate limited")) is None


@pytest.mark.asyncio
async def test_get_embeddings_batch_respects_retry_after(monkeypatch):
    provider = DummyEmbeddingProvider()
    provider.error_message = (
        "Gemini Embedding API 批量请求失败：Please retry in 25.776s."
    )
    sleep_calls = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    embeddings = await provider.get_embeddings_batch(
        ["a", "b"],
        batch_size=2,
        tasks_limit=1,
        max_retries=2,
    )

    assert embeddings == [[0.0], [0.0]]
    assert sleep_calls == [25.776]


@pytest.mark.asyncio
async def test_get_embeddings_batch_falls_back_to_exponential_backoff(monkeypatch):
    provider = DummyEmbeddingProvider()
    provider.error_message = "temporary network error"
    sleep_calls = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    embeddings = await provider.get_embeddings_batch(
        ["a", "b"],
        batch_size=2,
        tasks_limit=1,
        max_retries=2,
    )

    assert embeddings == [[0.0], [0.0]]
    assert sleep_calls == [1]


@pytest.mark.asyncio
async def test_get_embeddings_batch_prefers_remote_batch():
    provider = DummyEmbeddingProvider()
    provider.remote_batch_result = [[1.0], [2.0]]
    progress_calls = []

    async def progress_callback(stage, current, total):
        progress_calls.append((stage, current, total))

    embeddings = await provider.get_embeddings_batch(
        ["a", "b"],
        batch_size=2,
        tasks_limit=1,
        max_retries=2,
        progress_callback=progress_callback,
    )

    assert embeddings == [[1.0], [2.0]]
    assert provider.remote_batch_calls == 1
    assert provider.calls == 0
    assert ("batching", 1, 1) in progress_calls
    assert ("batch_waiting", 2, 2) in progress_calls


@pytest.mark.asyncio
async def test_get_embeddings_batch_falls_back_when_remote_batch_fails():
    provider = DummyEmbeddingProvider()
    provider.remote_batch_error = RemoteBatchFailedError("batch failed")
    progress_calls = []

    async def progress_callback(stage, current, total):
        progress_calls.append((stage, current, total))

    embeddings = await provider.get_embeddings_batch(
        ["a", "b"],
        batch_size=2,
        tasks_limit=1,
        max_retries=2,
        progress_callback=progress_callback,
    )

    assert embeddings == [[0.0], [0.0]]
    assert provider.remote_batch_calls == 1
    assert provider.calls == 2
    assert ("batching", 1, 1) in progress_calls
    assert ("batch_waiting", 2, 2) in progress_calls
    assert ("embedding", 0, 2) in progress_calls
    assert ("embedding", 2, 2) in progress_calls
