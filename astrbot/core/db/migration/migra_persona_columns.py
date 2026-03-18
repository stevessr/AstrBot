"""Migration script to ensure persona columns exist across backends.

Adds missing columns to personas table for older databases.
"""

from sqlalchemy import text

from astrbot.api import logger, sp
from astrbot.core.db import BaseDatabase


async def migrate_persona_columns(db_helper: BaseDatabase) -> None:
    """Ensure personas table has folder_id/sort_order/skills/custom_error_message."""
    migration_done = await db_helper.get_preference(
        "global", "global", "migration_done_persona_columns_1"
    )
    if migration_done:
        return

    logger.info("开始执行数据库迁移（补齐 personas 列）...")

    if not db_helper.is_sqlite and not db_helper.is_postgres:
        logger.info("当前数据库后端不支持 persona 列迁移，跳过")
        await sp.put_async("global", "global", "migration_done_persona_columns_1", True)
        return

    try:
        async with db_helper.get_db() as session:
            if db_helper.is_sqlite:
                # SQLite 迁移已在初始化时处理，这里仅做标记。
                await sp.put_async(
                    "global", "global", "migration_done_persona_columns_1", True
                )
                logger.info("SQLite 已处理 personas 列补齐，跳过执行")
                return

            await session.execute(
                text(
                    "ALTER TABLE personas ADD COLUMN IF NOT EXISTS folder_id VARCHAR(36) DEFAULT NULL"
                )
            )
            await session.execute(
                text(
                    "ALTER TABLE personas ADD COLUMN IF NOT EXISTS sort_order INTEGER DEFAULT 0"
                )
            )
            await session.execute(
                text("ALTER TABLE personas ADD COLUMN IF NOT EXISTS skills JSON")
            )
            await session.execute(
                text(
                    "ALTER TABLE personas ADD COLUMN IF NOT EXISTS custom_error_message TEXT"
                )
            )
            await session.commit()

            logger.info("personas 列补齐完成")

        await sp.put_async("global", "global", "migration_done_persona_columns_1", True)
    except Exception as e:
        logger.error(f"迁移 personas 列过程中发生错误: {e}", exc_info=True)
        raise
