from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import (
    Integer,
    cast,
    desc,
    func,
    or_,
    text,
)
from sqlalchemy import (
    Text as SAText,
)
from sqlalchemy import (
    inspect as sa_inspect,
)
from sqlmodel import col, select

from astrbot.core.db import BaseDatabase
from astrbot.core.db.po import (
    ConversationV2,
    Persona,
    PlatformStat,
    Preference,
    SQLModel,
)
from astrbot.core.db.sqlite import SQLiteDatabase


class PostgresDatabase(SQLiteDatabase):
    def __init__(
        self,
        database_url: str,
        *,
        connect_args: dict[str, Any] | None = None,
        engine_options: dict[str, Any] | None = None,
        schema: str | None = None,
    ) -> None:
        self.db_path = ""
        self.schema = (schema or "").strip() or None
        self.DATABASE_URL = database_url
        self.CONNECT_ARGS = connect_args or {}
        self.ENGINE_OPTIONS = engine_options or {}
        self.inited = False
        BaseDatabase.__init__(self)

    @staticmethod
    def _quote_identifier(value: str) -> str:
        return '"' + value.replace('"', '""') + '"'

    def _qualified_table_name(self, table_name: str) -> str:
        quoted_table = self._quote_identifier(table_name)
        if not self.schema:
            return quoted_table
        return f"{self._quote_identifier(self.schema)}.{quoted_table}"

    async def _set_search_path(self, executor) -> None:
        if not self.schema:
            return
        await executor.execute(
            text(f"SET search_path TO {self._quote_identifier(self.schema)}")
        )

    async def initialize(self) -> None:
        async with self.engine.begin() as conn:
            if self.schema:
                await conn.execute(
                    text(
                        f"CREATE SCHEMA IF NOT EXISTS {self._quote_identifier(self.schema)}"
                    )
                )
                await self._set_search_path(conn)
            await conn.run_sync(SQLModel.metadata.create_all)

    @asynccontextmanager
    async def get_db(self):
        if not self.inited:
            await self.initialize()
            self.inited = True
        async with self.AsyncSessionLocal() as session:
            await self._set_search_path(session)
            yield session

    async def get_platform_stats(self, offset_sec: int = 86400) -> list[PlatformStat]:
        async with self.get_db() as session:
            now = datetime.now()
            start_time = now - timedelta(seconds=offset_sec)
            result = await session.execute(
                select(PlatformStat)
                .where(PlatformStat.timestamp >= start_time)
                .order_by(col(PlatformStat.platform_id), desc(PlatformStat.timestamp))
                .distinct(col(PlatformStat.platform_id))
            )
            return list(result.scalars().all())

    async def get_filtered_conversations(
        self,
        page=1,
        page_size=20,
        platform_ids=None,
        search_query="",
        **kwargs,
    ):
        async with self.get_db() as session:
            base_query = select(ConversationV2)

            if platform_ids:
                base_query = base_query.where(
                    col(ConversationV2.platform_id).in_(platform_ids),
                )
            if search_query:
                search_query = search_query.encode("unicode_escape").decode("utf-8")
                content_as_text = cast(col(ConversationV2.content), SAText)
                base_query = base_query.where(
                    or_(
                        col(ConversationV2.title).ilike(f"%{search_query}%"),
                        content_as_text.ilike(f"%{search_query}%"),
                        col(ConversationV2.user_id).ilike(f"%{search_query}%"),
                        col(ConversationV2.conversation_id).ilike(f"%{search_query}%"),
                    ),
                )
            if "message_types" in kwargs and len(kwargs["message_types"]) > 0:
                for msg_type in kwargs["message_types"]:
                    base_query = base_query.where(
                        col(ConversationV2.user_id).ilike(f"%:{msg_type}:%"),
                    )
            if "platforms" in kwargs and len(kwargs["platforms"]) > 0:
                base_query = base_query.where(
                    col(ConversationV2.platform_id).in_(kwargs["platforms"]),
                )

            count_query = select(func.count()).select_from(base_query.subquery())
            total_count = await session.execute(count_query)
            total = total_count.scalar_one()

            offset = (page - 1) * page_size
            result_query = (
                base_query.order_by(desc(ConversationV2.created_at))
                .offset(offset)
                .limit(page_size)
            )
            result = await session.execute(result_query)
            conversations = result.scalars().all()

            return conversations, total

    async def get_session_conversations(
        self,
        page=1,
        page_size=20,
        search_query=None,
        platform=None,
    ) -> tuple[list[dict], int]:
        async with self.get_db() as session:
            offset = (page - 1) * page_size
            conversation_id_expr = Preference.value.op("->>")("val")

            base_query = (
                select(
                    col(Preference.scope_id).label("session_id"),
                    conversation_id_expr.label("conversation_id"),
                    col(ConversationV2.persona_id).label("persona_id"),
                    col(ConversationV2.title).label("title"),
                    col(Persona.persona_id).label("persona_name"),
                )
                .select_from(Preference)
                .outerjoin(
                    ConversationV2,
                    conversation_id_expr == ConversationV2.conversation_id,
                )
                .outerjoin(
                    Persona,
                    col(ConversationV2.persona_id) == Persona.persona_id,
                )
                .where(Preference.scope == "umo", Preference.key == "sel_conv_id")
            )

            if search_query:
                search_pattern = f"%{search_query}%"
                base_query = base_query.where(
                    or_(
                        col(Preference.scope_id).ilike(search_pattern),
                        col(ConversationV2.title).ilike(search_pattern),
                        col(Persona.persona_id).ilike(search_pattern),
                    ),
                )

            if platform:
                platform_pattern = f"{platform}:%"
                base_query = base_query.where(
                    col(Preference.scope_id).like(platform_pattern),
                )

            base_query = base_query.order_by(Preference.scope_id)

            result_query = base_query.offset(offset).limit(page_size)
            result = await session.execute(result_query)
            rows = result.fetchall()

            count_base_query = (
                select(func.count(col(Preference.scope_id)))
                .select_from(Preference)
                .outerjoin(
                    ConversationV2,
                    conversation_id_expr == ConversationV2.conversation_id,
                )
                .outerjoin(
                    Persona,
                    col(ConversationV2.persona_id) == Persona.persona_id,
                )
                .where(Preference.scope == "umo", Preference.key == "sel_conv_id")
            )

            if search_query:
                search_pattern = f"%{search_query}%"
                count_base_query = count_base_query.where(
                    or_(
                        col(Preference.scope_id).ilike(search_pattern),
                        col(ConversationV2.title).ilike(search_pattern),
                        col(Persona.persona_id).ilike(search_pattern),
                    ),
                )

            if platform:
                platform_pattern = f"{platform}:%"
                count_base_query = count_base_query.where(
                    col(Preference.scope_id).like(platform_pattern),
                )

            total_result = await session.execute(count_base_query)
            total = total_result.scalar() or 0

            sessions_data = [
                {
                    "session_id": row.session_id,
                    "conversation_id": row.conversation_id,
                    "persona_id": row.persona_id,
                    "title": row.title,
                    "persona_name": row.persona_name,
                }
                for row in rows
            ]
            return sessions_data, total

    async def sync_sequences(self) -> None:
        from astrbot.core.backup.constants import MAIN_DB_MODELS

        async with self.get_db() as session:
            for model_class in MAIN_DB_MODELS.values():
                mapper = sa_inspect(model_class)
                primary_keys = list(mapper.primary_key)
                if len(primary_keys) != 1:
                    continue
                primary_key = primary_keys[0]
                if not isinstance(primary_key.type, Integer):
                    continue

                table_name = mapper.local_table.name
                column_name = primary_key.name
                qualified_table_name = (
                    f"{self.schema}.{table_name}" if self.schema else table_name
                )
                sequence_name_result = await session.execute(
                    text("SELECT pg_get_serial_sequence(:table_name, :column_name)"),
                    {
                        "table_name": qualified_table_name,
                        "column_name": column_name,
                    },
                )
                sequence_name = sequence_name_result.scalar_one_or_none()
                if not sequence_name:
                    continue

                quoted_table = self._qualified_table_name(table_name)
                quoted_column = self._quote_identifier(column_name)
                await session.execute(
                    text(
                        f"""
                        SELECT setval(
                            CAST(:sequence_name AS regclass),
                            COALESCE((SELECT MAX({quoted_column}) FROM {quoted_table}), 1),
                            EXISTS(SELECT 1 FROM {quoted_table})
                        )
                        """
                    ),
                    {"sequence_name": sequence_name},
                )
            await session.commit()
