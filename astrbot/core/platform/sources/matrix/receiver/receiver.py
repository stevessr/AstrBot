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

            logger.debug(
                f"Processing event: type={type(event).__name__}, msgtype={event.msgtype if hasattr(event, 'msgtype') else 'N/A'}",
                extra={
                    "plugin_tag": "matrix",
                    "short_levelname": "DEBG",
                },
            )

            # 解析引用消息
            event_content = getattr(event, "content", {})
            reply_event_id = None

            logger.info(
                f"Checking for reply: event_content keys = {list(event_content.keys())}",
                extra={
                    "plugin_tag": "matrix",
                    "short_levelname": "INFO",
                },
            )

            logger.info(
                f"Full event_content: {event_content}",
                extra={
                    "plugin_tag": "matrix",
                    "short_levelname": "INFO",
                },
            )

            if "m.relates_to" in event_content:
                relates_to = event_content["m.relates_to"]
                logger.info(
                    f"Found m.relates_to: {relates_to}",
                    extra={
                        "plugin_tag": "matrix",
                        "short_levelname": "INFO",
                    },
                )
                if "m.in_reply_to" in relates_to:
                    reply_event_id = relates_to["m.in_reply_to"]["event_id"]
                    message.reply_to = reply_event_id

                    logger.info(
                        f"Detected reply to event: {reply_event_id}, client is {'available' if self.client else 'None'}",
                        extra={
                            "plugin_tag": "matrix",
                            "short_levelname": "INFO",
                        },
                    )

                    # 获取被引用的消息内容
                    if self.client:
                        try:
                            from astrbot.api.message_components import Reply, Plain, Image

                            logger.info(
                                f"Fetching referenced event: {reply_event_id}",
                                extra={
                                    "plugin_tag": "matrix",
                                    "short_levelname": "INFO",
                                },
                            )

                            # 获取被引用的事件
                            referenced_event_data = await self.client.get_event(
                                room.room_id, reply_event_id
                            )

                            logger.info(
                                f"Referenced event data: {referenced_event_data}",
                                extra={
                                    "plugin_tag": "matrix",
                                    "short_levelname": "INFO",
                                },
                            )

                            # 解析被引用消息的内容
                            reply_chain = []
                            reply_message_str = ""
                            ref_content = referenced_event_data.get("content", {})
                            ref_msgtype = ref_content.get("msgtype", "")
                            ref_sender = referenced_event_data.get("sender", "")
                            ref_timestamp = referenced_event_data.get("origin_server_ts", 0)

                            # 获取发送者昵称
                            ref_sender_nickname = (
                                room.user_name(ref_sender)
                                if hasattr(room, "user_name")
                                else ref_sender.split(":")[0].lstrip("@")
                            )

                            logger.info(
                                f"Processing referenced message: msgtype={ref_msgtype}",
                                extra={
                                    "plugin_tag": "matrix",
                                    "short_levelname": "INFO",
                                },
                            )

                            if ref_msgtype == "m.text":
                                # 文本消息
                                ref_body = ref_content.get("body", "")
                                reply_chain.append(Plain(ref_body))
                                reply_message_str = ref_body
                            elif ref_msgtype == "m.image":
                                # 图片消息 - 下载并添加到引用链
                                ref_url = ref_content.get("url", "")
                                logger.info(
                                    f"Image message detected, mxc URL: {ref_url}",
                                    extra={
                                        "plugin_tag": "matrix",
                                        "short_levelname": "INFO",
                                    },
                                )
                                if ref_url:
                                    try:
                                        import os
                                        from astrbot.core.utils.astrbot_path import get_astrbot_data_path

                                        img_bytes = await self.client.download_file(ref_url)

                                        # 持久化保存到临时目录
                                        temp_dir = os.path.join(
                                            get_astrbot_data_path(), "temp", "matrix_images"
                                        )
                                        os.makedirs(temp_dir, exist_ok=True)

                                        # 使用媒体 ID 作为文件名
                                        media_id = ref_url.split("/")[-1]
                                        file_ext = ".jpg"  # 默认
                                        ref_info = ref_content.get("info", {})
                                        if ref_info:
                                            mimetype = ref_info.get("mimetype", "")
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

                                        abs_file_path = os.path.abspath(file_path)
                                        reply_chain.append(Image(file=abs_file_path))
                                        reply_message_str = "[图片]"
                                        logger.info(
                                            f"Referenced image downloaded: {abs_file_path}",
                                            extra={
                                                "plugin_tag": "matrix",
                                                "short_levelname": "INFO",
                                            },
                                        )
                                    except Exception as e:
                                        logger.error(
                                            f"Failed to download referenced image: {e}",
                                            extra={
                                                "plugin_tag": "matrix",
                                                "short_levelname": "ERRO",
                                            },
                                        )
                                        import traceback
                                        logger.error(
                                            f"Traceback: {traceback.format_exc()}",
                                            extra={
                                                "plugin_tag": "matrix",
                                                "short_levelname": "ERRO",
                                            },
                                        )
                                        ref_body = ref_content.get("body", "[图片]")
                                        reply_chain.append(Plain(f"[引用图片下载失败：{ref_body}]"))
                                        reply_message_str = f"[引用图片：{ref_body}]"
                                else:
                                    logger.warning(
                                        f"Referenced image has no URL in content: {ref_content}",
                                        extra={
                                            "plugin_tag": "matrix",
                                            "short_levelname": "WARN",
                                        },
                                    )
                                    ref_body = ref_content.get("body", "[图片]")
                                    reply_chain.append(Plain(f"[引用图片：{ref_body}]"))
                                    reply_message_str = f"[引用图片：{ref_body}]"
                            elif ref_msgtype == "m.file":
                                # 文件消息
                                ref_body = ref_content.get("body", "[文件]")
                                reply_chain.append(Plain(f"[文件：{ref_body}]"))
                                reply_message_str = f"[文件：{ref_body}]"
                            else:
                                # 其他类型
                                ref_body = ref_content.get("body", "[消息]")
                                reply_chain.append(Plain(ref_body))
                                reply_message_str = ref_body

                            # 创建 Reply 组件并添加到消息链
                            reply_component = Reply(
                                id=reply_event_id,
                                chain=reply_chain,
                                sender_id=ref_sender,
                                sender_nickname=ref_sender_nickname,
                                time=ref_timestamp,
                                message_str=reply_message_str,
                            )
                            message.message.append(reply_component)

                            logger.info(
                                f"Added Reply component with {len(reply_chain)} items in chain: {reply_message_str}",
                                extra={
                                    "plugin_tag": "matrix",
                                    "short_levelname": "INFO",
                                },
                            )

                        except Exception as e:
                            logger.error(
                                f"Failed to fetch referenced message: {e}",
                                extra={
                                    "plugin_tag": "matrix",
                                    "short_levelname": "ERRO",
                                },
                            )
                    else:
                        logger.warning(
                            f"Cannot fetch referenced event {reply_event_id}: client is None",
                            extra={
                                "plugin_tag": "matrix",
                                "short_levelname": "WARN",
                            },
                        )

            # 普通文本
            from ..client.event_types import (
                RoomMessageText,
                RoomMessageImage,
                RoomMessageFile,
            )

            if isinstance(event, RoomMessageText) or event.msgtype == "m.text":
                from astrbot.api.message_components import Plain

                text_body = event.body or ""

                # 如果是回复消息，需要去除 Matrix 的 fallback 引用格式
                # Fallback 格式：> <@user:server> quoted text\n\nactual reply
                if reply_event_id and "\n\n" in text_body:
                    # 分割并取实际回复内容（fallback 后的部分）
                    parts = text_body.split("\n\n", 1)
                    if len(parts) > 1 and parts[0].startswith(">"):
                        text_body = parts[1].strip()
                        logger.debug(
                            f"Stripped fallback quote, actual reply: {text_body}",
                            extra={
                                "plugin_tag": "matrix",
                                "short_levelname": "DEBG",
                            },
                        )

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

                            # 使用 Image 组件，传入绝对文件路径
                            # 确保路径格式正确，以便 convert_to_file_path() 可以识别
                            abs_file_path = os.path.abspath(file_path)
                            logger.debug(
                                f"Image saved to: {abs_file_path}",
                                extra={
                                    "plugin_tag": "matrix",
                                    "short_levelname": "DEBG",
                                },
                            )
                            message.message.append(Image(file=abs_file_path))
                            message.message_str = "[图片]"
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

            # 调试：输出最终消息结构
            logger.info(
                f"Final message chain has {len(message.message)} components: {[type(c).__name__ for c in message.message]}",
                extra={
                    "plugin_tag": "matrix",
                    "short_levelname": "INFO",
                },
            )

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
