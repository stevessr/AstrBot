import abc
import copy
import datetime
import ssl
import typing as T
from contextlib import asynccontextmanager

from deprecated import deprecated
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from astrbot.core.db.po import (
    ApiKey,
    Attachment,
    ChatUIProject,
    CommandConfig,
    CommandConflict,
    ConversationCompressionSnapshot,
    ConversationV2,
    CronJob,
    Persona,
    PersonaFolder,
    PlatformMessageHistory,
    PlatformSession,
    PlatformStat,
    Preference,
    ProviderStat,
    SessionProjectRelation,
    Stats,
    WebChatThread,
)


class BaseDatabase(abc.ABC):
    """数据库基类"""

    DATABASE_URL = ""
    CONNECT_ARGS: dict[str, T.Any] = {}
    ENGINE_OPTIONS: dict[str, T.Any] = {}

    def __init__(self) -> None:
        engine_options = {
            "echo": False,
            "future": True,
            **copy.deepcopy(self.ENGINE_OPTIONS),
        }
        connect_args = copy.deepcopy(self.CONNECT_ARGS)
        # SQLite only supports a single writer at a time. Without a busy timeout
        # the driver raises "database is locked" instantly when a second write is
        # attempted. Setting timeout=30 tells SQLite to wait up to 30 s for the lock.
        if "sqlite" in self.DATABASE_URL and "timeout" not in connect_args:
            connect_args["timeout"] = 30
        if connect_args:
            engine_options["connect_args"] = connect_args

        self.engine = create_async_engine(
            self.DATABASE_URL,
            **engine_options,
        )
        self.AsyncSessionLocal = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def initialize(self) -> None:
        """初始化数据库连接"""

    @asynccontextmanager
    async def get_db(self) -> T.AsyncGenerator[AsyncSession, None]:
        """Get a database session."""
        if not self.inited:
            await self.initialize()
            self.inited = True
        async with self.AsyncSessionLocal() as session:
            yield session

    async def sync_sequences(self) -> None:
        """校准自增序列，默认无需处理。"""

    @property
    def backend_name(self) -> str:
        return self.engine.url.get_backend_name()

    @property
    def is_sqlite(self) -> bool:
        return self.backend_name == "sqlite"

    @property
    def is_postgres(self) -> bool:
        return self.backend_name == "postgresql"

    @deprecated(version="4.0.0", reason="Use get_platform_stats instead")
    @abc.abstractmethod
    def get_base_stats(self, offset_sec: int = 86400) -> Stats:
        """获取基础统计数据"""
        raise NotImplementedError

    @deprecated(version="4.0.0", reason="Use get_platform_stats instead")
    @abc.abstractmethod
    def get_total_message_count(self) -> int:
        """获取总消息数"""
        raise NotImplementedError

    @deprecated(version="4.0.0", reason="Use get_platform_stats instead")
    @abc.abstractmethod
    def get_grouped_base_stats(self, offset_sec: int = 86400) -> Stats:
        """获取基础统计数据(合并)"""
        raise NotImplementedError

    # New methods in v4.0.0

    @abc.abstractmethod
    async def insert_platform_stats(
        self,
        platform_id: str,
        platform_type: str,
        count: int = 1,
        timestamp: datetime.datetime | None = None,
    ) -> None:
        """Insert a new platform statistic record."""
        ...

    @abc.abstractmethod
    async def count_platform_stats(self) -> int:
        """Count the number of platform statistics records."""
        ...

    @abc.abstractmethod
    async def get_platform_stats(self, offset_sec: int = 86400) -> list[PlatformStat]:
        """Get platform statistics within the specified offset in seconds and group by platform_id."""
        ...

    @abc.abstractmethod
    async def insert_provider_stat(
        self,
        *,
        umo: str,
        provider_id: str,
        provider_model: str | None = None,
        conversation_id: str | None = None,
        status: str = "completed",
        stats: dict | None = None,
        agent_type: str = "internal",
    ) -> ProviderStat:
        """Insert a per-response provider stat record."""
        ...

    @abc.abstractmethod
    async def get_conversations(
        self,
        user_id: str | None = None,
        platform_id: str | None = None,
    ) -> list[ConversationV2]:
        """Get all conversations for a specific user and platform_id(optional).

        content is not included in the result.
        """
        ...

    @abc.abstractmethod
    async def get_conversation_by_id(self, cid: str) -> ConversationV2:
        """Get a specific conversation by its ID."""
        ...

    @abc.abstractmethod
    async def get_all_conversations(
        self,
        page: int = 1,
        page_size: int = 20,
    ) -> list[ConversationV2]:
        """Get all conversations with pagination."""
        ...

    @abc.abstractmethod
    async def get_filtered_conversations(
        self,
        page: int = 1,
        page_size: int = 20,
        platform_ids: list[str] | None = None,
        search_query: str = "",
        **kwargs,
    ) -> tuple[list[ConversationV2], int]:
        """Get conversations filtered by platform IDs and search query."""
        ...

    @abc.abstractmethod
    async def create_conversation(
        self,
        user_id: str,
        platform_id: str,
        content: list[dict] | None = None,
        title: str | None = None,
        persona_id: str | None = None,
        cid: str | None = None,
        created_at: datetime.datetime | None = None,
        updated_at: datetime.datetime | None = None,
    ) -> ConversationV2:
        """Create a new conversation."""
        ...

    @abc.abstractmethod
    async def update_conversation(
        self,
        cid: str,
        title: str | None = None,
        persona_id: str | None = None,
        content: list[dict] | None = None,
        token_usage: int | None = None,
    ) -> None:
        """Update a conversation's history."""
        ...

    @abc.abstractmethod
    async def delete_conversation(self, cid: str) -> None:
        """Delete a conversation by its ID."""
        ...

    @abc.abstractmethod
    async def delete_conversations_by_user_id(self, user_id: str) -> None:
        """Delete all conversations for a specific user."""
        ...

    @abc.abstractmethod
    async def create_conversation_compression_snapshot(
        self,
        conversation_id: str,
        user_id: str,
        history: list[dict],
    ) -> ConversationCompressionSnapshot:
        """Persist a conversation snapshot captured before manual compression."""
        ...

    @abc.abstractmethod
    async def get_conversation_compression_snapshots(
        self,
        conversation_id: str,
        user_id: str,
        offset: int = 0,
        limit: int | None = None,
    ) -> list[ConversationCompressionSnapshot]:
        """Get conversation snapshots ordered from newest to oldest."""
        ...

    @abc.abstractmethod
    async def delete_conversation_compression_snapshots(
        self,
        conversation_id: str | None = None,
        user_id: str | None = None,
    ) -> None:
        """Delete conversation compression snapshots by conversation and/or user."""
        ...

    @abc.abstractmethod
    async def insert_platform_message_history(
        self,
        platform_id: str,
        user_id: str,
        content: dict,
        sender_id: str | None = None,
        sender_name: str | None = None,
        llm_checkpoint_id: str | None = None,
    ) -> PlatformMessageHistory:
        """Insert a new platform message history record."""
        ...

    @abc.abstractmethod
    async def update_platform_message_history(
        self,
        message_id: int,
        content: dict | None = None,
        llm_checkpoint_id: str | None = None,
    ) -> None:
        """Update a platform message history record."""
        ...

    @abc.abstractmethod
    async def delete_platform_message_history_by_id(self, message_id: int) -> None:
        """Delete a platform message history record by its ID."""
        ...

    @abc.abstractmethod
    async def delete_platform_message_offset(
        self,
        platform_id: str,
        user_id: str,
        offset_sec: int = 86400,
    ) -> None:
        """Delete platform message history records newer than the specified offset."""
        ...

    @abc.abstractmethod
    async def get_platform_message_history(
        self,
        platform_id: str,
        user_id: str,
        page: int = 1,
        page_size: int = 20,
    ) -> list[PlatformMessageHistory]:
        """Get platform message history for a specific user."""
        ...

    @abc.abstractmethod
    async def get_platform_message_history_by_id(
        self,
        message_id: int,
    ) -> PlatformMessageHistory | None:
        """Get a platform message history record by its ID."""
        ...

    @abc.abstractmethod
    async def create_webchat_thread(
        self,
        creator: str,
        parent_session_id: str,
        parent_message_id: int,
        base_checkpoint_id: str,
        selected_text: str,
    ) -> WebChatThread:
        """Create a WebChat side thread."""
        ...

    @abc.abstractmethod
    async def get_webchat_thread_by_id(
        self,
        thread_id: str,
    ) -> WebChatThread | None:
        """Get a WebChat side thread by thread_id."""
        ...

    @abc.abstractmethod
    async def get_webchat_threads_by_parent_session(
        self,
        parent_session_id: str,
        creator: str | None = None,
    ) -> list[WebChatThread]:
        """Get side threads for a parent WebChat session."""
        ...

    @abc.abstractmethod
    async def get_webchat_thread_by_parent_message_and_text(
        self,
        parent_session_id: str,
        parent_message_id: int,
        selected_text: str,
        creator: str | None = None,
    ) -> WebChatThread | None:
        """Get an existing side thread for the same selected text."""
        ...

    @abc.abstractmethod
    async def delete_webchat_thread(self, thread_id: str) -> None:
        """Delete a WebChat side thread."""
        ...

    @abc.abstractmethod
    async def delete_webchat_threads_by_parent_session(
        self,
        parent_session_id: str,
    ) -> list[str]:
        """Delete side threads for a parent WebChat session."""
        ...

    @abc.abstractmethod
    async def delete_webchat_threads_by_parent_message_ids(
        self,
        parent_session_id: str,
        parent_message_ids: list[int],
    ) -> list[str]:
        """Delete side threads linked to parent message IDs."""
        ...

    @abc.abstractmethod
    async def insert_attachment(
        self,
        path: str,
        type: str,
        mime_type: str,
    ):
        """Insert a new attachment record."""
        ...

    @abc.abstractmethod
    async def get_attachment_by_id(self, attachment_id: str) -> Attachment:
        """Get an attachment by its ID."""
        ...

    @abc.abstractmethod
    async def get_attachments(self, attachment_ids: list[str]) -> list[Attachment]:
        """Get multiple attachments by their IDs."""
        ...

    @abc.abstractmethod
    async def delete_attachment(self, attachment_id: str) -> bool:
        """Delete an attachment by its ID.

        Returns True if the attachment was deleted, False if it was not found.
        """
        ...

    @abc.abstractmethod
    async def delete_attachments(self, attachment_ids: list[str]) -> int:
        """Delete multiple attachments by their IDs.

        Returns the number of attachments deleted.
        """
        ...

    @abc.abstractmethod
    async def create_api_key(
        self,
        name: str,
        key_hash: str,
        key_prefix: str,
        scopes: list[str] | None,
        created_by: str,
        expires_at: datetime.datetime | None = None,
    ) -> ApiKey:
        """Create a new API key record."""
        ...

    @abc.abstractmethod
    async def list_api_keys(self) -> list[ApiKey]:
        """List all API keys."""
        ...

    @abc.abstractmethod
    async def get_api_key_by_id(self, key_id: str) -> ApiKey | None:
        """Get an API key by key_id."""
        ...

    @abc.abstractmethod
    async def get_active_api_key_by_hash(self, key_hash: str) -> ApiKey | None:
        """Get an active API key by hash (not revoked, not expired)."""
        ...

    @abc.abstractmethod
    async def touch_api_key(self, key_id: str) -> None:
        """Update last_used_at of an API key."""
        ...

    @abc.abstractmethod
    async def revoke_api_key(self, key_id: str) -> bool:
        """Revoke an API key.

        Returns True when the key exists and is updated.
        """
        ...

    @abc.abstractmethod
    async def delete_api_key(self, key_id: str) -> bool:
        """Delete an API key.

        Returns True when the key exists and is deleted.
        """
        ...

    @abc.abstractmethod
    async def insert_persona(
        self,
        persona_id: str,
        system_prompt: str,
        begin_dialogs: list[str] | None = None,
        tools: list[str] | None = None,
        skills: list[str] | None = None,
        custom_error_message: str | None = None,
        folder_id: str | None = None,
        sort_order: int = 0,
    ) -> Persona:
        """Insert a new persona record.

        Args:
            persona_id: Unique identifier for the persona
            system_prompt: System prompt for the persona
            begin_dialogs: Optional list of initial dialog strings
            tools: Optional list of tool names (None means all tools, [] means no tools)
            skills: Optional list of skill names (None means all skills, [] means no skills)
            custom_error_message: Optional persona-level fallback error message
            folder_id: Optional folder ID to place the persona in (None means root)
            sort_order: Sort order within the folder (default 0)
        """
        ...

    @abc.abstractmethod
    async def get_persona_by_id(self, persona_id: str) -> Persona:
        """Get a persona by its ID."""
        ...

    @abc.abstractmethod
    async def get_personas(self) -> list[Persona]:
        """Get all personas for a specific bot."""
        ...

    @abc.abstractmethod
    async def update_persona(
        self,
        persona_id: str,
        system_prompt: str | None = None,
        begin_dialogs: list[str] | None = None,
        tools: list[str] | None = None,
        skills: list[str] | None = None,
        custom_error_message: str | None = None,
    ) -> Persona | None:
        """Update a persona's system prompt or begin dialogs."""
        ...

    @abc.abstractmethod
    async def delete_persona(self, persona_id: str) -> None:
        """Delete a persona by its ID."""
        ...

    # ====
    # Persona Folder Management
    # ====

    @abc.abstractmethod
    async def insert_persona_folder(
        self,
        name: str,
        parent_id: str | None = None,
        description: str | None = None,
        sort_order: int = 0,
    ) -> PersonaFolder:
        """Insert a new persona folder."""
        ...

    @abc.abstractmethod
    async def get_persona_folder_by_id(self, folder_id: str) -> PersonaFolder | None:
        """Get a persona folder by its folder_id."""
        ...

    @abc.abstractmethod
    async def get_persona_folders(
        self, parent_id: str | None = None
    ) -> list[PersonaFolder]:
        """Get all persona folders, optionally filtered by parent_id."""
        ...

    @abc.abstractmethod
    async def get_all_persona_folders(self) -> list[PersonaFolder]:
        """Get all persona folders."""
        ...

    @abc.abstractmethod
    async def update_persona_folder(
        self,
        folder_id: str,
        name: str | None = None,
        parent_id: T.Any = None,
        description: T.Any = None,
        sort_order: int | None = None,
    ) -> PersonaFolder | None:
        """Update a persona folder."""
        ...

    @abc.abstractmethod
    async def delete_persona_folder(self, folder_id: str) -> None:
        """Delete a persona folder by its folder_id."""
        ...

    @abc.abstractmethod
    async def move_persona_to_folder(
        self, persona_id: str, folder_id: str | None
    ) -> Persona | None:
        """Move a persona to a folder (or root if folder_id is None)."""
        ...

    @abc.abstractmethod
    async def get_personas_by_folder(
        self, folder_id: str | None = None
    ) -> list[Persona]:
        """Get all personas in a specific folder."""
        ...

    @abc.abstractmethod
    async def batch_update_sort_order(
        self,
        items: list[dict],
    ) -> None:
        """Batch update sort_order for personas and/or folders.

        Args:
            items: List of dicts with keys:
                - id: The persona_id or folder_id
                - type: Either "persona" or "folder"
                - sort_order: The new sort_order value
        """
        ...

    @abc.abstractmethod
    async def insert_preference_or_update(
        self,
        scope: str,
        scope_id: str,
        key: str,
        value: dict,
    ) -> Preference:
        """Insert a new preference record."""
        ...

    @abc.abstractmethod
    async def get_preference(self, scope: str, scope_id: str, key: str) -> Preference:
        """Get a preference by scope ID and key."""
        ...

    @abc.abstractmethod
    async def get_preferences(
        self,
        scope: str,
        scope_id: str | None = None,
        key: str | None = None,
    ) -> list[Preference]:
        """Get all preferences for a specific scope ID or key."""
        ...

    @abc.abstractmethod
    async def remove_preference(self, scope: str, scope_id: str, key: str) -> None:
        """Remove a preference by scope ID and key."""
        ...

    @abc.abstractmethod
    async def clear_preferences(self, scope: str, scope_id: str) -> None:
        """Clear all preferences for a specific scope ID."""
        ...

    @abc.abstractmethod
    async def get_command_configs(self) -> list[CommandConfig]:
        """Get all stored command configurations."""
        ...

    @abc.abstractmethod
    async def get_command_config(self, handler_full_name: str) -> CommandConfig | None:
        """Fetch a single command configuration by handler."""
        ...

    @abc.abstractmethod
    async def upsert_command_config(
        self,
        handler_full_name: str,
        plugin_name: str,
        module_path: str,
        original_command: str,
        *,
        resolved_command: str | None = None,
        enabled: bool | None = None,
        keep_original_alias: bool | None = None,
        conflict_key: str | None = None,
        resolution_strategy: str | None = None,
        note: str | None = None,
        extra_data: dict | None = None,
        auto_managed: bool | None = None,
    ) -> CommandConfig:
        """Create or update a command configuration."""
        ...

    @abc.abstractmethod
    async def delete_command_config(self, handler_full_name: str) -> None:
        """Delete a single command configuration."""
        ...

    @abc.abstractmethod
    async def delete_command_configs(self, handler_full_names: list[str]) -> None:
        """Bulk delete command configurations."""
        ...

    @abc.abstractmethod
    async def list_command_conflicts(
        self,
        status: str | None = None,
    ) -> list[CommandConflict]:
        """List recorded command conflict entries."""
        ...

    @abc.abstractmethod
    async def upsert_command_conflict(
        self,
        conflict_key: str,
        handler_full_name: str,
        plugin_name: str,
        *,
        status: str | None = None,
        resolution: str | None = None,
        resolved_command: str | None = None,
        note: str | None = None,
        extra_data: dict | None = None,
        auto_generated: bool | None = None,
    ) -> CommandConflict:
        """Create or update a conflict record."""
        ...

    @abc.abstractmethod
    async def delete_command_conflicts(self, ids: list[int]) -> None:
        """Delete conflict records."""
        ...

    # @abc.abstractmethod
    # async def insert_llm_message(
    #     self,
    #     cid: str,
    #     role: str,
    #     content: list,
    #     tool_calls: list = None,
    #     tool_call_id: str = None,
    #     parent_id: str = None,
    # ) -> LLMMessage:
    #     """Insert a new LLM message into the conversation."""
    #     ...

    # @abc.abstractmethod
    # async def get_llm_messages(self, cid: str) -> list[LLMMessage]:
    #     """Get all LLM messages for a specific conversation."""
    #     ...

    @abc.abstractmethod
    async def get_session_conversations(
        self,
        page: int = 1,
        page_size: int = 20,
        search_query: str | None = None,
        platform: str | None = None,
    ) -> tuple[list[dict], int]:
        """Get paginated session conversations with joined conversation and persona details, support search and platform filter."""
        ...

    # ====
    # Cron Job Management
    # ====

    @abc.abstractmethod
    async def create_cron_job(
        self,
        name: str,
        job_type: str,
        cron_expression: str | None,
        *,
        timezone: str | None = None,
        payload: dict | None = None,
        description: str | None = None,
        enabled: bool = True,
        persistent: bool = True,
        run_once: bool = False,
        status: str | None = None,
        job_id: str | None = None,
    ) -> CronJob:
        """Create and persist a cron job definition."""
        ...

    @abc.abstractmethod
    async def update_cron_job(
        self,
        job_id: str,
        *,
        name: str | None = None,
        cron_expression: str | None = None,
        timezone: str | None = None,
        payload: dict | None = None,
        description: str | None = None,
        enabled: bool | None = None,
        persistent: bool | None = None,
        run_once: bool | None = None,
        status: str | None = None,
        next_run_time: datetime.datetime | None = None,
        last_run_at: datetime.datetime | None = None,
        last_error: str | None = None,
    ) -> CronJob | None:
        """Update fields of a cron job by job_id."""
        ...

    @abc.abstractmethod
    async def delete_cron_job(self, job_id: str) -> None:
        """Delete a cron job by its public job_id."""
        ...

    @abc.abstractmethod
    async def get_cron_job(self, job_id: str) -> CronJob | None:
        """Fetch a cron job by job_id."""
        ...

    @abc.abstractmethod
    async def list_cron_jobs(self, job_type: str | None = None) -> list[CronJob]:
        """List cron jobs, optionally filtered by job_type."""
        ...

    # ====
    # Platform Session Management
    # ====

    @abc.abstractmethod
    async def create_platform_session(
        self,
        creator: str,
        platform_id: str = "webchat",
        session_id: str | None = None,
        display_name: str | None = None,
        is_group: int = 0,
    ) -> PlatformSession:
        """Create a new Platform session."""
        ...

    @abc.abstractmethod
    async def get_platform_session_by_id(
        self, session_id: str
    ) -> PlatformSession | None:
        """Get a Platform session by its ID."""
        ...

    @abc.abstractmethod
    async def get_platform_sessions_by_ids(
        self, session_ids: list[str]
    ) -> list[PlatformSession]:
        """Get platform sessions by IDs."""
        ...

    @abc.abstractmethod
    async def get_platform_sessions_by_creator(
        self,
        creator: str,
        platform_id: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> list[dict]:
        """Get all Platform sessions for a specific creator (username) and optionally platform.

        Returns a list of dicts containing session info and project info (if session belongs to a project).
        """
        ...

    @abc.abstractmethod
    async def get_platform_sessions_by_creator_paginated(
        self,
        creator: str,
        platform_id: str | None = None,
        page: int = 1,
        page_size: int = 20,
        exclude_project_sessions: bool = False,
    ) -> tuple[list[dict], int]:
        """Get paginated platform sessions and total count for a creator.

        Returns:
            tuple[list[dict], int]: (sessions_with_project_info, total_count)
        """
        ...

    @abc.abstractmethod
    async def update_platform_session(
        self,
        session_id: str,
        display_name: str | None = None,
    ) -> None:
        """Update a Platform session's updated_at timestamp and optionally display_name."""
        ...

    @abc.abstractmethod
    async def delete_platform_session(self, session_id: str) -> None:
        """Delete a Platform session by its ID."""
        ...

    # ====
    # ChatUI Project Management
    # ====

    @abc.abstractmethod
    async def create_chatui_project(
        self,
        creator: str,
        title: str,
        emoji: str | None = "📁",
        description: str | None = None,
    ) -> ChatUIProject:
        """Create a new ChatUI project."""
        ...

    @abc.abstractmethod
    async def get_chatui_project_by_id(self, project_id: str) -> ChatUIProject | None:
        """Get a ChatUI project by its ID."""
        ...

    @abc.abstractmethod
    async def get_chatui_projects_by_creator(
        self,
        creator: str,
        page: int = 1,
        page_size: int = 100,
    ) -> list[ChatUIProject]:
        """Get all ChatUI projects for a specific creator."""
        ...

    @abc.abstractmethod
    async def update_chatui_project(
        self,
        project_id: str,
        title: str | None = None,
        emoji: str | None = None,
        description: str | None = None,
    ) -> None:
        """Update a ChatUI project."""
        ...

    @abc.abstractmethod
    async def delete_chatui_project(self, project_id: str) -> None:
        """Delete a ChatUI project by its ID."""
        ...

    @abc.abstractmethod
    async def add_session_to_project(
        self,
        session_id: str,
        project_id: str,
    ) -> SessionProjectRelation:
        """Add a session to a project."""
        ...

    @abc.abstractmethod
    async def remove_session_from_project(self, session_id: str) -> None:
        """Remove a session from its project."""
        ...

    @abc.abstractmethod
    async def get_project_sessions(
        self,
        project_id: str,
        page: int = 1,
        page_size: int = 100,
    ) -> list[PlatformSession]:
        """Get all sessions in a project."""
        ...

    @abc.abstractmethod
    async def get_project_by_session(
        self, session_id: str, creator: str
    ) -> ChatUIProject | None:
        """Get the project that a session belongs to."""
        ...


def _normalize_database_config(config: dict | None) -> dict:
    normalized = copy.deepcopy(config or {})
    normalized.setdefault("backend", "sqlite")
    normalized.setdefault("sqlite_path", "")
    normalized.setdefault("url", "")
    normalized.setdefault("host", "127.0.0.1")
    normalized.setdefault("port", 5432)
    normalized.setdefault("user", "")
    normalized.setdefault("password", "")
    normalized.setdefault("database", "")
    normalized.setdefault("schema", "")
    normalized.setdefault("ssl_mode", "prefer")
    return normalized


def _url_backend_name(url: str) -> str | None:
    try:
        return make_url(url).get_backend_name()
    except Exception:
        return None


def _normalize_postgres_url(url: str) -> str:
    parsed = make_url(url)
    if parsed.get_backend_name() != "postgresql":
        return url
    if parsed.drivername != "postgresql+asyncpg":
        parsed = parsed.set(drivername="postgresql+asyncpg")
    return parsed.render_as_string(hide_password=False)


def build_database_url(config: dict | None) -> str:
    db_config = _normalize_database_config(config)
    backend = str(db_config.get("backend") or "sqlite").strip().lower()
    url = str(db_config.get("url") or "").strip()

    if url:
        backend_from_url = _url_backend_name(url)
        if backend_from_url == "postgresql":
            return _normalize_postgres_url(url)
        return url

    if backend == "postgres":
        host = str(db_config.get("host") or "127.0.0.1").strip() or "127.0.0.1"
        port = int(db_config.get("port") or 5432)
        username = str(db_config.get("user") or "")
        password = str(db_config.get("password") or "")
        database = str(db_config.get("database") or "").strip()
        if not database:
            raise ValueError("database.database 不能为空")
        return URL.create(
            "postgresql+asyncpg",
            username=username or None,
            password=password or None,
            host=host,
            port=port,
            database=database,
        ).render_as_string(hide_password=False)

    sqlite_path = str(db_config.get("sqlite_path") or "").strip()
    if not sqlite_path:
        raise ValueError("database.sqlite_path 不能为空")
    return f"sqlite+aiosqlite:///{sqlite_path}"


def sanitize_database_url(url: str) -> str:
    safe_url = url.strip()
    if not safe_url:
        return ""
    try:
        parsed = make_url(safe_url)
    except Exception:
        return safe_url
    if parsed.password is None:
        return safe_url
    return parsed.render_as_string(hide_password=True)


def _postgres_connect_args(config: dict) -> dict[str, T.Any]:
    ssl_mode = str(config.get("ssl_mode") or "prefer").strip().lower()
    if ssl_mode in {"", "prefer", "allow"}:
        return {}
    if ssl_mode == "disable":
        return {"ssl": False}

    ssl_context = ssl.create_default_context()
    if ssl_mode == "require":
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        return {"ssl": ssl_context}
    if ssl_mode in {"verify-ca", "verify_full", "verify-full"}:
        if ssl_mode == "verify-ca":
            ssl_context.check_hostname = False
        return {"ssl": ssl_context}
    raise ValueError(f"不支持的 ssl_mode: {ssl_mode}")


def get_database_connect_args(config: dict | None) -> dict[str, T.Any]:
    db_config = _normalize_database_config(config)
    backend = str(db_config.get("backend") or "sqlite").strip().lower()
    url = str(db_config.get("url") or "").strip().lower()
    if backend == "postgres" or url.startswith("postgresql"):
        return _postgres_connect_args(db_config)
    return {}


def get_database_engine_options(config: dict | None) -> dict[str, T.Any]:
    db_config = _normalize_database_config(config)
    backend = str(db_config.get("backend") or "sqlite").strip().lower()
    url = str(db_config.get("url") or "").strip().lower()
    if backend == "postgres" or url.startswith("postgresql"):
        return {"pool_pre_ping": True}
    return {}


def get_database_schema(config: dict | None) -> str | None:
    db_config = _normalize_database_config(config)
    schema = str(db_config.get("schema") or "").strip()
    return schema or None


def get_database_backend(config: dict | None) -> str:
    db_config = _normalize_database_config(config)
    url = str(db_config.get("url") or "").strip()
    backend_from_url = _url_backend_name(url) if url else None
    if backend_from_url == "postgresql":
        return "postgres"
    if backend_from_url == "sqlite":
        return "sqlite"
    return str(db_config.get("backend") or "sqlite").strip().lower() or "sqlite"


def create_main_database(config: dict | None):
    db_config = _normalize_database_config(config)
    backend = get_database_backend(db_config)
    if backend == "postgres":
        from astrbot.core.db.postgres import PostgresDatabase

        return PostgresDatabase(
            database_url=build_database_url(db_config),
            connect_args=get_database_connect_args(db_config),
            engine_options=get_database_engine_options(db_config),
            schema=get_database_schema(db_config),
        )

    from astrbot.core.db.sqlite import SQLiteDatabase

    sqlite_url = build_database_url(db_config)
    sqlite_path = sqlite_url.removeprefix("sqlite+aiosqlite:///")
    return SQLiteDatabase(sqlite_path)
