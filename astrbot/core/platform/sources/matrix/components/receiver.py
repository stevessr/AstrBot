"""
Matrix 消息接收与转换组件，支持解析引用（回复）消息（不依赖 matrix-nio）
"""

import logging
from typing import Optional
from astrbot.api.platform import AstrBotMessage, MessageType, MessageMember

logger = logging.getLogger("astrbot.matrix.receiver")


class MatrixReceiver:
    def __init__(self, user_id: str, mxc_to_http, bot_name: str = None, client=None):
        self.user_id = user_id
        self.mxc_to_http = mxc_to_http
        self.bot_name = bot_name or "bot"
        self.client = client  # 可选，MatrixHTTPClient 实例

    async def convert_message(self, room, event) -> Optional[AstrBotMessage]:
        try:
            message = AstrBotMessage()
            message.session_id = room.room_id
            message.message_id = event.event_id
            message.raw_message = event
            message.timestamp = event.origin_server_ts
            member_count = getattr(room, "member_count", 2)
            if member_count > 2 or getattr(room, "is_group", False):
                message.type = MessageType.GROUP_MESSAGE
                message.group_id = room.room_id
            else:
                message.type = MessageType.FRIEND_MESSAGE
            sender_display_name = (
                room.user_name(event.sender)
                if hasattr(room, "user_name")
                else event.sender
            )
            message.sender = MessageMember(
                user_id=event.sender,
                nickname=sender_display_name or event.sender.split(":")[0].lstrip("@"),
            )
            message.self_id = self.user_id
            message.message = []

            # 解析引用消息
            event_content = getattr(event, "content", {})
            if "m.relates_to" in event_content:
                relates_to = event_content["m.relates_to"]
                if "m.in_reply_to" in relates_to:
                    reply_event_id = relates_to["m.in_reply_to"]["event_id"]
                    message.reply_to = reply_event_id

            # 普通文本
            from ..client.event_types import (
                RoomMessageText,
                RoomMessageImage,
                RoomMessageFile,
            )

            if isinstance(event, RoomMessageText) or event.msgtype == "m.text":
                from astrbot.api.message_components import Plain

                text_body = event.body or ""
                message.message_str = text_body
                message.message.append(Plain(text_body))

                # 检测是否 @ 了机器人
                # Matrix 的 @ 格式：@[display_name] 或检查 formatted_body 中的提及
                is_mentioned = False

                # 方法 1：检查 body 中的 @[bot_name] 格式
                if (
                    f"@[{self.bot_name}]" in text_body
                    or f"@{self.bot_name}" in text_body
                ):
                    is_mentioned = True

                # 方法 2：检查 formatted_body 中的 HTML 提及标签
                formatted_body = event_content.get("formatted_body")
                if formatted_body:
                    # Matrix 的 HTML 格式提及：<a href="https://matrix.to/#/@user:server">@DisplayName</a>
                    if self.user_id in formatted_body:
                        is_mentioned = True

                # 方法 3：检查 content 中的 m.mentions 字段（新版 Matrix 规范）
                if "m.mentions" in event_content:
                    mentions = event_content["m.mentions"]
                    if "user_ids" in mentions and self.user_id in mentions["user_ids"]:
                        is_mentioned = True

                # 设置标志位，让框架知道机器人被 @ 了
                if is_mentioned:
                    message.is_tome = True  # 标记为发给机器人的消息

            elif isinstance(event, RoomMessageImage) or event.msgtype == "m.image":
                from astrbot.api.message_components import Image, Plain
                import os
                from astrbot.core.utils.astrbot_path import get_astrbot_data_path

                mxc_url = getattr(event, "url", None)
                if mxc_url:
                    # 使用 MatrixHTTPClient 下载图片并持久化
                    if hasattr(self, "client") and self.client is not None:
                        try:
                            img_bytes = await self.client.download_file(mxc_url)

                            # 持久化保存到临时目录
                            temp_dir = os.path.join(
                                get_astrbot_data_path(), "temp", "matrix_images"
                            )
                            os.makedirs(temp_dir, exist_ok=True)

                            # 使用 event_id 作为文件名，避免冲突
                            # 从 mxc URL 中提取媒体 ID 用作文件名
                            media_id = mxc_url.split("/")[-1]
                            # 从 info 中获取文件扩展名
                            file_ext = ".jpg"  # 默认
                            if hasattr(event, "info") and event.info:
                                mimetype = event.info.get("mimetype", "")
                                if "png" in mimetype:
                                    file_ext = ".png"
                                elif "gif" in mimetype:
                                    file_ext = ".gif"
                                elif "webp" in mimetype:
                                    file_ext = ".webp"

                            filename = f"{media_id}{file_ext}"
                            file_path = os.path.join(temp_dir, filename)

                            # 保存文件
                            with open(file_path, "wb") as f:
                                f.write(img_bytes)

                            # 使用 Image 组件，传入文件路径
                            message.message.append(
                                Image(file=file_path, filename=event.body)
                            )
                            message.message_str = f"[图片：{event.body}]"
                            logger.debug(
                                f"Image downloaded and saved: {file_path}",
                                extra={
                                    "plugin_tag": "matrix",
                                    "short_levelname": "DEBG",
                                },
                            )
                        except Exception as e:
                            logger.error(
                                f"Failed to download image: {e}",
                                extra={
                                    "plugin_tag": "matrix",
                                    "short_levelname": "ERRO",
                                },
                            )
                            # 降级：显示错误信息，不添加图片组件
                            message.message.append(
                                Plain(f"[图片下载失败：{event.body}] {e}")
                            )
                            message.message_str = f"[图片下载失败：{event.body}]"
                    else:
                        # 没有 client，无法下载
                        message.message.append(
                            Plain(f"[图片：{event.body}] (无法下载，客户端未初始化)")
                        )
                        message.message_str = f"[图片：{event.body}] (无法下载)"
                else:
                    message.message_str = f"[图片：{event.body}] (无 URL)"
                    message.message.append(Plain(f"[图片：{event.body}] (无 URL)"))
            elif isinstance(event, RoomMessageFile) or event.msgtype == "m.file":
                from astrbot.api.message_components import Plain

                message.message_str = f"[文件：{event.body}]"
                message.message.append(Plain(f"[文件：{event.body}]"))
            else:
                logger.warning(
                    f"Unknown message type: {type(event)}",
                    extra={"plugin_tag": "matrix", "short_levelname": "WARN"},
                )
                return None
            return message
        except Exception as e:
            logger.error(
                f"Error converting Matrix message: {e}",
                extra={"plugin_tag": "matrix", "short_levelname": "ERRO"},
            )
            logger.error(
                f"Event: {event}",
                extra={"plugin_tag": "matrix", "short_levelname": "ERRO"},
            )
            return None
