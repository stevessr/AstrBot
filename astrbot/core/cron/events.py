import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from astrbot.core import logger
from astrbot.core.message.components import Plain
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.platform.astrbot_message import AstrBotMessage, MessageMember
from astrbot.core.platform.message_session import MessageSession
from astrbot.core.platform.message_type import MessageType
from astrbot.core.platform.platform_metadata import PlatformMetadata


class CronMessageEvent(AstrMessageEvent):
    """Synthetic event used when a cron job triggers the main agent loop."""

    # 全局钩子注册表
    _send_hooks: list[
        Callable[[AstrMessageEvent, MessageChain], Awaitable[MessageChain]]
    ] = []

    @classmethod
    def register_send_hook(
        cls,
        hook: Callable[[AstrMessageEvent, MessageChain], Awaitable[MessageChain]],
    ) -> None:
        """注册一个发送前钩子，用于处理消息链。

        钩子函数签名: async hook(event: AstrMessageEvent, message_chain: MessageChain) -> MessageChain

        钩子可以修改 message_chain 并返回修改后的结果。
        """
        cls._send_hooks.append(hook)
        logger.info(f"CronMessageEvent 注册了发送钩子: {hook.__name__}")

    def __init__(
        self,
        *,
        context,
        session: MessageSession,
        message: str,
        sender_id: str = "astrbot",
        sender_name: str = "Scheduler",
        extras: dict[str, Any] | None = None,
        message_type: MessageType = MessageType.FRIEND_MESSAGE,
    ) -> None:
        platform_meta = PlatformMetadata(
            name="cron",
            description="CronJob",
            id=session.platform_id,
        )

        msg_obj = AstrBotMessage()
        msg_obj.type = message_type
        msg_obj.self_id = sender_id
        msg_obj.session_id = session.session_id
        msg_obj.message_id = uuid.uuid4().hex
        msg_obj.sender = MessageMember(user_id=session.session_id, nickname=sender_name)
        msg_obj.message = [Plain(message)]
        msg_obj.message_str = message
        msg_obj.raw_message = message
        msg_obj.timestamp = int(time.time())

        super().__init__(message, msg_obj, platform_meta, session.session_id)

        # Ensure we use the original session for sending messages
        self.session = session
        self.context_obj = context
        self.is_at_or_wake_command = True
        self.is_wake = True

        if extras:
            self._extras.update(extras)

    async def send(self, message: MessageChain) -> None:
        if message is None:
            return

        # 执行所有注册的钩子，允许修改消息链
        for hook in self._send_hooks:
            try:
                message = await hook(self, message)
            except Exception as e:
                logger.error(f"CronMessageEvent 钩子执行失败: {e}", exc_info=True)

        await self.context_obj.send_message(self.session, message)
        await super().send(message)

    async def send_streaming(self, generator, use_fallback: bool = False) -> None:
        async for chain in generator:
            await self.send(chain)


__all__ = ["CronMessageEvent"]
