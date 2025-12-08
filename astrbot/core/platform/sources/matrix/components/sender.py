"""
Matrix 消息发送组件，支持普通消息和引用（回复）消息（不依赖 matrix-nio）
"""

import logging
from typing import Optional
from astrbot.api.event import MessageChain
from astrbot.core.platform.astr_message_event import MessageSesion
from .markdown_utils import markdown_to_html

logger = logging.getLogger("astrbot.matrix.sender")


class MatrixSender:
    def __init__(self, client):
        self.client = client

    async def send_message(
        self,
        session: MessageSesion,
        message_chain: MessageChain,
        reply_to: Optional[str] = None,
        room_encrypted: bool = False,
        room_members: Optional[list] = None,
    ):
        """
        发送消息到房间

        Args:
            session: 消息会话
            message_chain: 消息链
            reply_to: 回复的消息 ID
            room_encrypted: 房间是否加密 (ignored - E2EE removed)
            room_members: 房间成员列表 (ignored - E2EE removed)
        """
        room_id = session.session_id
        if not room_id:
            logger.error(
                "Session does not have a valid room_id",
                extra={"plugin_tag": "matrix", "short_levelname": "ERRO"},
            )
            return

        # 获取消息文本
        body_text = (
            message_chain.text if hasattr(message_chain, "text") else str(message_chain)
        )

        # 渲染 Markdown 为 HTML - 根据 Matrix 规范，始终包含 HTML 格式
        try:
            formatted_body = markdown_to_html(body_text)
        except Exception as e:
            logger.warning(
                f"Failed to render markdown: {e}",
                extra={"plugin_tag": "matrix", "short_levelname": "WARN"},
            )
            formatted_body = body_text.replace("\n", "<br>")

        content = {
            "msgtype": "m.text",
            "body": body_text,
            "format": "org.matrix.custom.html",
            "formatted_body": formatted_body,
        }

        if reply_to:
            content["m.relates_to"] = {"m.in_reply_to": {"event_id": reply_to}}

        await self.client.send_message(
            room_id=room_id,
            msg_type="m.room.message",
            content=content,
        )
