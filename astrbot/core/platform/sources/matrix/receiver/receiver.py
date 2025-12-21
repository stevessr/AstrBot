"""
Matrix 消息接收组件
"""

import logging
import time

from astrbot.api.event import MessageChain
from astrbot.api.message_components import *
from astrbot.api.platform import AstrBotMessage
from astrbot.core.platform.astrbot_message import MessageMember
from astrbot.core.platform.message_type import MessageType
from astrbot.core.utils import astrbot_path

# Update import: Client event types are in ..client.event_types
from ..client.event_types import MatrixRoom, parse_event
from ..utils.utils import MatrixUtils

logger = logging.getLogger("astrbot.matrix.receiver")


class MatrixReceiver:
    def __init__(
        self,
        user_id: str,
        mxc_converter: callable = None,
        bot_name: str = None,
        client=None,
    ):
        self.user_id = user_id
        self.mxc_converter = mxc_converter
        self.bot_name = bot_name
        self.client = client  # MatrixHTTPClient instance needed for downloading files

    async def convert_message(self, room: MatrixRoom, event) -> AstrBotMessage:
        """
        将 Matrix 消息转换为 AstrBot 消息格式
        """
        message = AstrBotMessage()

        # 基础信息
        message.raw_message = event

        # Strip reply fallback from body
        message.message_str = MatrixUtils.strip_reply_fallback(event.body)
        message.session_id = room.room_id
        message.message_id = event.event_id  # Set message ID for replies
        message.self_id = self.user_id  # Set bot's self ID

        # 默认设为群组消息 (Matrix 房间概念)
        # TODO: 未来可根据房间人数判断是否为私聊
        message.type = MessageType.FRIEND_MESSAGE

        # 发送者信息
        sender_id = event.sender
        sender_name = room.members.get(sender_id, sender_id)

        message.sender = MessageMember(
            user_id=sender_id,
            nickname=sender_name,
        )

        # 构建消息链
        chain = MessageChain()

        # 处理回复
        relates_to = event.content.get("m.relates_to", {})
        reply_event_id = None

        # 1. 检查标准的 m.in_reply_to
        if "m.in_reply_to" in relates_to:
            reply_event_id = relates_to["m.in_reply_to"].get("event_id")

        # 2. 检查嘟文串 (Threading) 回复
        if not reply_event_id and relates_to.get("rel_type") == "m.thread":
            # 在嘟文串中，如果没有显式的 m.in_reply_to，则视为回复根消息或上一条消息
            # 这里简化处理，如果 rel_type 是 m.thread，我们将其视为回复
            reply_event_id = relates_to.get("event_id")

        if reply_event_id:
            # 创建回复组件
            from astrbot.api.message_components import Reply

            # 注意：Reply 组件通常需要完整的消息对象，但这里我们只有 ID
            # AstrBot 的 Reply 组件结构可能需要适配
            reply_comp = Reply(id=reply_event_id)
            chain.chain.append(reply_comp)

        # 处理消息内容
        msgtype = event.content.get("msgtype")

        if msgtype == "m.text":
            text = event.body

            # 处理 @提及
            # 简单实现：检查文本是否以 @bot_name 开头
            if self.bot_name and text.startswith(f"@{self.bot_name}"):
                from astrbot.api.message_components import At

                # 移除 @bot_name 前缀
                text = text[len(self.bot_name) + 1 :].lstrip()
                # 添加 At 组件 (self)
                chain.chain.append(At(user_id=self.user_id))  # bot self

            if text:
                chain.chain.append(Plain(text))

        elif msgtype == "m.image":
            from astrbot.api.message_components import Image

            url = event.content.get("url")
            if url and self.mxc_converter:
                http_url = self.mxc_converter(url)
                # Matrix 图片通常需要通过 access_token 访问，或者如果是公开房间
                # 这里暂存 http_url，后续可能需要下载
                chain.chain.append(Image.fromURL(http_url))

        elif msgtype in ["m.file", "m.audio", "m.video"]:
            # 其他文件类型暂作文本提示处理，或实现 File 组件
            chain.chain.append(Plain(f"[{msgtype}: {event.body}]"))

        else:
            # 未知类型，直接作为文本
            chain.chain.append(
                Plain(event.body or f"[Unknown message type: {msgtype}]")
            )

        message.message = (
            chain.chain
        )  # AstrBotMessage 需要列表格式的消息链 (list[BaseMessageComponent])
        return message
