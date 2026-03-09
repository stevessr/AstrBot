import copy
from dataclasses import dataclass

from sqlalchemy import func, select

from astrbot.core.backup.constants import MAIN_DB_MODELS
from astrbot.core.backup.exporter import AstrBotExporter
from astrbot.core.backup.importer import AstrBotImporter
from astrbot.core.config.default import DB_PATH
from astrbot.core.db import BaseDatabase, create_main_database, sanitize_database_url


@dataclass
class MigrationValidationResult:
    passed: bool
    details: dict[str, dict[str, int | bool]]


class SQLiteToPostgresMigrationService:
    def __init__(
        self,
        source_db: BaseDatabase,
        current_config,
    ) -> None:
        self.source_db = source_db
        self.current_config = current_config

    async def test_connection(self, target_config: dict) -> str:
        target_db = create_main_database(target_config)
        try:
            async with target_db.engine.begin() as conn:
                await conn.execute(select(1))
            return sanitize_database_url(target_db.DATABASE_URL)
        finally:
            await target_db.engine.dispose()

    async def migrate(self, target_config: dict) -> dict:
        if not self.source_db.is_sqlite:
            raise ValueError(
                "当前运行中的主库不是 SQLite，无法执行 SQLite → Postgres 迁移"
            )

        target_db = create_main_database(target_config)
        if not target_db.is_postgres:
            raise ValueError("目标数据库后端必须是 Postgres")

        backup_zip = None
        try:
            exporter = AstrBotExporter(main_db=self.source_db)
            backup_zip = await exporter.export_all()
            main_data = await exporter.export_main_database()

            await target_db.initialize()
            importer = AstrBotImporter(main_db=target_db)
            imported = await importer.import_main_database(main_data)
            await target_db.sync_sequences()
            validation = await self._validate_migration(self.source_db, target_db)
            if not validation.passed:
                raise ValueError(f"迁移校验失败: {validation.details}")

            new_config = copy.deepcopy(dict(self.current_config))
            new_config.setdefault("database", {})
            new_config["database"] = copy.deepcopy(target_config)
            new_config["database"].setdefault("sqlite_path", DB_PATH)
            self.current_config.save_config(new_config)

            return {
                "backup_zip": backup_zip,
                "database_url": sanitize_database_url(target_db.DATABASE_URL),
                "imported_tables": imported,
                "validation": validation.details,
                "restart_required": True,
            }
        finally:
            await target_db.engine.dispose()

    async def _validate_migration(
        self,
        source_db: BaseDatabase,
        target_db: BaseDatabase,
    ) -> MigrationValidationResult:
        details: dict[str, dict[str, int | bool]] = {}
        required_tables = [
            "conversations",
            "personas",
            "preferences",
            "attachments",
            "platform_sessions",
            "api_keys",
            "command_configs",
            "cron_jobs",
        ]

        for table_name in required_tables:
            model_class = MAIN_DB_MODELS[table_name]
            source_count = await self._count_table(source_db, model_class)
            target_count = await self._count_table(target_db, model_class)
            details[table_name] = {
                "source": source_count,
                "target": target_count,
                "matched": source_count == target_count,
            }

        passed = all(item["matched"] for item in details.values())
        return MigrationValidationResult(passed=passed, details=details)

    async def _count_table(self, database: BaseDatabase, model_class) -> int:
        async with database.get_db() as session:
            result = await session.execute(
                select(func.count()).select_from(model_class)
            )
            return int(result.scalar_one() or 0)
