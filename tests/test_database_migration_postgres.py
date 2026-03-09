from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from astrbot.core.backup.constants import MAIN_DB_MODELS
from astrbot.core.db import (
    build_database_url,
    get_database_backend,
    sanitize_database_url,
)
from astrbot.core.db.migration.sqlite_to_postgres import (
    SQLiteToPostgresMigrationService,
)


class _FakeConfig(dict):
    def __init__(self):
        super().__init__(
            {"database": {"backend": "sqlite", "sqlite_path": "/tmp/source.db"}}
        )
        self.saved_config = None

    def save_config(self, config):
        self.saved_config = config
        self.clear()
        self.update(config)


@pytest.mark.parametrize(
    ("config", "expected_backend", "url_fragment"),
    [
        (
            {
                "backend": "sqlite",
                "sqlite_path": "/tmp/astrbot.db",
            },
            "sqlite",
            "sqlite+aiosqlite:///",
        ),
        (
            {
                "backend": "postgres",
                "host": "127.0.0.1",
                "port": 5432,
                "user": "astrbot",
                "password": "secret",
                "database": "astrbot",
                "schema": "app",
                "ssl_mode": "prefer",
            },
            "postgres",
            "postgresql+asyncpg://astrbot:secret@127.0.0.1:5432/astrbot",
        ),
    ],
)
def test_database_url_helpers(config, expected_backend, url_fragment):
    assert get_database_backend(config) == expected_backend
    assert build_database_url(config).startswith(url_fragment)


def test_sanitize_database_url_hides_password():
    masked = sanitize_database_url(
        "postgresql+asyncpg://astrbot:secret@127.0.0.1:5432/astrbot"
    )
    assert "secret" not in masked
    assert "***" in masked


@pytest.mark.asyncio
async def test_validate_migration_checks_required_tables():
    source_db = MagicMock()
    target_db = MagicMock()
    current_config = _FakeConfig()
    service = SQLiteToPostgresMigrationService(source_db, current_config)

    counts = {
        id(source_db): {
            "conversations": 1,
            "personas": 2,
            "preferences": 3,
            "attachments": 4,
            "platform_sessions": 5,
            "api_keys": 6,
            "command_configs": 7,
            "cron_jobs": 8,
        },
        id(target_db): {
            "conversations": 1,
            "personas": 2,
            "preferences": 3,
            "attachments": 4,
            "platform_sessions": 5,
            "api_keys": 6,
            "command_configs": 7,
            "cron_jobs": 8,
        },
    }

    async def fake_count(database, model_class):
        for table_name, mapped_model in MAIN_DB_MODELS.items():
            if mapped_model is model_class:
                return counts[id(database)][table_name]
        raise AssertionError("unexpected model")

    service._count_table = fake_count  # noqa: SLF001
    result = await service._validate_migration(source_db, target_db)  # noqa: SLF001
    assert result.passed is True
    assert all(item["matched"] for item in result.details.values())


@pytest.mark.asyncio
async def test_migrate_rejects_non_sqlite_source():
    source_db = MagicMock()
    source_db.is_sqlite = False
    current_config = _FakeConfig()
    service = SQLiteToPostgresMigrationService(source_db, current_config)

    with pytest.raises(ValueError, match="当前运行中的主库不是 SQLite"):
        await service.migrate({"backend": "postgres", "database": "astrbot"})


@pytest.mark.asyncio
async def test_test_connection_returns_sanitized_url(monkeypatch):
    source_db = MagicMock()
    current_config = _FakeConfig()
    service = SQLiteToPostgresMigrationService(source_db, current_config)

    fake_conn = MagicMock()
    fake_conn.execute = AsyncMock()

    class _FakeBegin:
        async def __aenter__(self):
            return fake_conn

        async def __aexit__(self, exc_type, exc, tb):
            return False

    fake_target_db = MagicMock()
    fake_target_db.engine.begin.return_value = _FakeBegin()
    fake_target_db.engine.dispose = AsyncMock()
    fake_target_db.DATABASE_URL = (
        "postgresql+asyncpg://astrbot:secret@127.0.0.1:5432/astrbot"
    )
    fake_target_db.is_postgres = True

    monkeypatch.setattr(
        "astrbot.core.db.migration.sqlite_to_postgres.create_main_database",
        lambda config: fake_target_db,
    )

    sanitized = await service.test_connection(
        {
            "backend": "postgres",
            "host": "127.0.0.1",
            "port": 5432,
            "user": "astrbot",
            "password": "secret",
            "database": "astrbot",
        }
    )
    assert "secret" not in sanitized
    assert "***" in sanitized


@pytest.mark.asyncio
async def test_migrate_updates_config_after_success(monkeypatch, tmp_path: Path):
    source_db = MagicMock()
    source_db.is_sqlite = True
    current_config = _FakeConfig()
    service = SQLiteToPostgresMigrationService(source_db, current_config)

    exporter_instance = MagicMock()
    exporter_instance.export_all = AsyncMock(return_value=str(tmp_path / "backup.zip"))
    exporter_instance.export_main_database = AsyncMock(
        return_value={"conversations": []}
    )
    importer_instance = MagicMock()
    importer_instance.import_main_database = AsyncMock(
        return_value={"conversations": 0}
    )

    fake_target_db = MagicMock()
    fake_target_db.is_postgres = True
    fake_target_db.initialize = AsyncMock()
    fake_target_db.sync_sequences = AsyncMock()
    fake_target_db.engine.dispose = AsyncMock()
    fake_target_db.DATABASE_URL = (
        "postgresql+asyncpg://astrbot:secret@127.0.0.1:5432/astrbot"
    )

    validation_result = MagicMock()
    validation_result.passed = True
    validation_result.details = {
        "conversations": {"source": 0, "target": 0, "matched": True}
    }

    monkeypatch.setattr(
        "astrbot.core.db.migration.sqlite_to_postgres.AstrBotExporter",
        lambda main_db: exporter_instance,
    )
    monkeypatch.setattr(
        "astrbot.core.db.migration.sqlite_to_postgres.AstrBotImporter",
        lambda main_db: importer_instance,
    )
    monkeypatch.setattr(
        "astrbot.core.db.migration.sqlite_to_postgres.create_main_database",
        lambda config: fake_target_db,
    )

    async def fake_validate(source, target):
        return validation_result

    service._validate_migration = fake_validate  # noqa: SLF001

    result = await service.migrate(
        {
            "backend": "postgres",
            "host": "127.0.0.1",
            "port": 5432,
            "user": "astrbot",
            "password": "secret",
            "database": "astrbot",
            "schema": "app",
            "ssl_mode": "prefer",
        }
    )

    assert result["restart_required"] is True
    assert current_config.saved_config is not None
    assert current_config.saved_config["database"]["backend"] == "postgres"
    assert current_config.saved_config["database"]["schema"] == "app"
