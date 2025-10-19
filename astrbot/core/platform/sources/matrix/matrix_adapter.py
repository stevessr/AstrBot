from __future__ import annotations

import asyncio
import sys
import uuid
from typing import Optional

from astrbot.api import logger
from astrbot.api.message_components import Plain
from astrbot.api.platform import (
    AstrBotMessage,
    MessageMember,
    MessageType,
    Platform,
    PlatformMetadata,
    register_platform_adapter,
)

from .matrix_client import MatrixClient
from .matrix_event import MatrixPlatformEvent

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override


@register_platform_adapter("matrix", "Matrix 适配器", adapter_display_name="Matrix")
class MatrixPlatformAdapter(Platform):
    def __init__(
        self,
        platform_config: dict,
        platform_settings: dict,
        event_queue: asyncio.Queue,
    ) -> None:
        super().__init__(event_queue)
        self.config = platform_config
        self.settings = platform_settings
        self.client_self_id = uuid.uuid4().hex[:8]

        homeserver = self.config.get("homeserver", "")
        access_token = self.config.get("access_token", "")
        self.user_id: Optional[str] = self.config.get("user_id")
        if not homeserver or not access_token:
            logger.error("Matrix 适配器未配置 homeserver 或 access_token，将不会启动。")
        self.client = MatrixClient(
            homeserver,
            access_token,
            user_id=self.user_id,
            timeout=int(self.config.get("sync_timeout", 30000)),
        )
        self._sync_task: Optional[asyncio.Task] = None
        self._sync_token_path = self.config.get("sync_token_path", "")

    @override
    def meta(self) -> PlatformMetadata:
        return PlatformMetadata(
            name="matrix", description="Matrix 适配器", id=self.config.get("id")
        )

    @override
    async def run(self):
        if not self.config.get("enable", False):
            logger.warning("Matrix 适配器未启用。")
            return
        try:
            whoami = await self.client.whoami()
            self.user_id = whoami.get("user_id")
            logger.info(f"Matrix whoami: {self.user_id}")
        except Exception as e:
            logger.error(f"Matrix whoami 失败: {e!s}")
        self._sync_task = asyncio.create_task(self._sync_loop(), name="matrix_sync")
        await self._sync_task

    async def _sync_loop(self):
        sync_token: Optional[str] = None
        # Load persisted token
        if self._sync_token_path:
            try:
                with open(self._sync_token_path, "r", encoding="utf-8") as f:
                    sync_token = f.read().strip() or None
            except Exception:
                pass
        while True:
            try:
                resp = await self.client.sync(since=sync_token)
                sync_token = resp.get("next_batch") or sync_token
                # Persist token
                if self._sync_token_path and sync_token:
                    try:
                        with open(self._sync_token_path, "w", encoding="utf-8") as f:
                            f.write(sync_token)
                    except Exception:
                        pass
                rooms = resp.get("rooms", {}).get("join", {})
                for room_id, room in rooms.items():
                    timeline = room.get("timeline", {})
                    events = timeline.get("events", [])
                    for ev in events:
                        await self._handle_event(room_id, ev)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Matrix sync 循环错误: {e!s}")
                await asyncio.sleep(2)

    async def _handle_event(self, room_id: str, ev: dict):
        et = ev.get("type")
        if et == "m.room.message":
            content = ev.get("content", {})
            msgtype = content.get("msgtype")
            if msgtype == "m.text":
                await self._handle_text_message(room_id, ev)
        elif et == "m.room.encrypted":
            # E2EE 事件暂不解密，后续由 vodozemac 集成支持
            logger.debug("收到加密消息，暂不支持解密。")
        else:
            # ignore other event types
            pass

    async def _handle_text_message(self, room_id: str, ev: dict):
        content = ev.get("content", {})
        body = content.get("body", "")
        if not body:
            return
        sender = ev.get("sender")
        if (
            self.settings.get("ignore_bot_self_message", False)
            and sender == self.user_id
        ):
            return

        abm = AstrBotMessage()
        # 在 Matrix 中，DM 也是房间。统一使用 GROUP_MESSAGE 便于会话隔离
        abm.type = MessageType.GROUP_MESSAGE
        abm.group_id = room_id
        abm.session_id = room_id
        abm.message_id = ev.get("event_id")
        abm.sender = MessageMember(user_id=sender, nickname=sender)
        abm.self_id = self.user_id or ""
        abm.raw_message = ev
        abm.message_str = body
        abm.message = [Plain(body)]

        event = MatrixPlatformEvent(
            message_str=abm.message_str,
            message_obj=abm,
            platform_meta=self.meta(),
            session_id=abm.session_id,
            client=self.client,
            room_id=room_id,
            event_id=abm.message_id,
        )
        self.commit_event(event)

    @override
    async def send_by_session(self, session, message_chain):
        # session_id 即房间 ID
        room_id = session.session_id
        reply_to = None
        # Find a reply component if any
        for comp in message_chain.chain:
            if comp.type == "reply":
                reply_to = getattr(comp, "id", None)
                break
        # Send Plain chunks
        for comp in message_chain.chain:
            if isinstance(comp, Plain):
                await self.client.send_text(
                    room_id, comp.text, reply_to_event_id=reply_to
                )
                reply_to = None
        await super().send_by_session(session, message_chain)

    def get_client(self) -> MatrixClient:
        return self.client

    async def terminate(self):
        try:
            if self._sync_task and not self._sync_task.done():
                self._sync_task.cancel()
                try:
                    await self._sync_task
                except Exception:
                    pass
            await self.client.close()
            logger.info("Matrix 适配器已被优雅地关闭")
        except Exception as e:
            logger.error(f"Matrix 适配器关闭时出错: {e!s}")
