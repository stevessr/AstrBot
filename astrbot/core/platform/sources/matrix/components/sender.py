"""
Matrix 消息发送组件，支持普通消息、引用（回复）消息和加密消息（不依赖 matrix-nio）
"""

import json
import logging
from typing import Optional
from astrbot.api.event import MessageChain
from astrbot.core.platform.astr_message_event import MessageSesion
from .markdown_utils import markdown_to_html

logger = logging.getLogger("astrbot.matrix.sender")


class MatrixSender:
    def __init__(self, client, e2ee_manager=None):
        self.client = client
        self.e2ee_manager = e2ee_manager

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
            room_encrypted: 房间是否加密
            room_members: 房间成员列表（用于 E2EE）
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

        # 如果房间加密且 E2EE 已启用，发送加密消息
        if room_encrypted and self.e2ee_manager and self.e2ee_manager.is_enabled():
            await self._send_encrypted_message(room_id, content, room_members or [])
        else:
            # 发送普通消息
            await self.client.send_message(
                room_id=room_id,
                msg_type="m.room.message",
                content=content,
            )

    async def _send_encrypted_message(
        self, room_id: str, content: dict, room_members: list
    ):
        """
        发送加密消息

        根据 matrix-sdk-crypto 教程的流程：
        1. 确保所有设备都有 Olm 会话
        2. 分享房间密钥
        3. 加密消息
        4. 发送加密消息
        """
        try:
            # 1. 分享房间密钥（内部会自动调用 get_missing_sessions）
            logger.debug(f"Sharing room key for {room_id} with {len(room_members)} members")
            await self.e2ee_manager.share_room_key(room_id, room_members)

            # 2. 加密消息内容
            plaintext = json.dumps(content)
            encrypted_content = self.e2ee_manager.encrypt_group_message(room_id, plaintext)

            if not encrypted_content:
                logger.error("Failed to encrypt message, sending plaintext instead")
                await self.client.send_message(
                    room_id=room_id,
                    msg_type="m.room.message",
                    content=content,
                )
                return

            # 3. 发送加密消息
            await self.client.send_message(
                room_id=room_id,
                msg_type="m.room.encrypted",
                content=encrypted_content,
            )
            logger.debug(f"Sent encrypted message to {room_id}")

        except Exception as e:
            logger.error(f"Error sending encrypted message: {e}")
            # 降级到普通消息
            logger.warning("Falling back to plaintext message")
            await self.client.send_message(
                room_id=room_id,
                msg_type="m.room.message",
                content=content,
            )
