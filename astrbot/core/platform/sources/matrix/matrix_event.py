from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.platform import AstrBotMessage, PlatformMetadata
from astrbot.api.message_components import Plain, Image, File, Reply
from pathlib import Path
from astrbot import logger
import mimetypes
from astrbot.core.platform.sources.matrix.components.markdown_utils import (
    markdown_to_html,
)


class MatrixPlatformEvent(AstrMessageEvent):
    """Matrix 平台事件处理器（不依赖 matrix-nio）"""

    def __init__(
        self,
        message_str: str,
        message_obj: AstrBotMessage,
        platform_meta: PlatformMetadata,
        session_id: str,
        client,
    ):
        super().__init__(message_str, message_obj, platform_meta, session_id)
        self.client = client  # MatrixHTTPClient instance

    @staticmethod
    async def send_with_client(
        client,
        message_chain: MessageChain,
        room_id: str,
        reply_to: str | None = None,
    ) -> int:
        """使用提供的 client 将指定消息链发送到指定房间。

        Args:
            client: MatrixHTTPClient 实例
            message_chain: 要发送的消息链
            room_id: 目标房间 ID（Matrix 的 roomId）
            reply_to: 可选，被引用的消息 event_id

        Returns:
            已发送的消息段数量
        """
        sent_count = 0

        # 若未显式传入 reply_to，则尝试从消息链中提取 Reply 段
        if reply_to is None:
            for seg in message_chain.chain:
                if isinstance(seg, Reply) and getattr(seg, "id", None):
                    reply_to = str(seg.id)
                    break

        for segment in message_chain.chain:
            # Reply 段仅用于标注引用关系，实际发送时跳过
            if isinstance(segment, Reply):
                continue
            if isinstance(segment, Plain):
                # 发送支持 Markdown 渲染的文本消息
                content = {
                    "msgtype": "m.text",
                    "body": segment.text,
                }

                # 生成 formatted_body - 优先使用 segment 中的，否则从 body 转换
                formatted_body = None
                if hasattr(segment, "formatted_body") and segment.formatted_body:
                    formatted_body = segment.formatted_body
                else:
                    # 从 body 文本生成 HTML 格式
                    try:
                        formatted_body = markdown_to_html(segment.text)
                    except Exception as e:
                        logger.warning(f"Failed to render markdown: {e}")
                        formatted_body = segment.text.replace("\n", "<br>")

                # 添加格式化内容
                if hasattr(segment, "format") and segment.format:
                    content["format"] = segment.format
                else:
                    content["format"] = "org.matrix.custom.html"

                if formatted_body:
                    content["formatted_body"] = formatted_body

                # 若需要引用回复，添加 m.relates_to 的 in_reply_to
                if reply_to:
                    content["m.relates_to"] = {"m.in_reply_to": {"event_id": reply_to}}

                try:
                    await client.send_message(
                        room_id=room_id, msg_type="m.room.message", content=content
                    )
                    sent_count += 1
                except Exception as e:
                    logger.error(f"发送文本消息失败：{e}")

            elif isinstance(segment, Image):
                try:
                    # 统一转换为本地路径
                    img_path = await segment.convert_to_file_path()
                    filename = Path(img_path).name
                    with open(img_path, "rb") as f:
                        image_data = f.read()

                    # 猜测内容类型，默认使用 image/png
                    content_type = mimetypes.guess_type(filename)[0] or "image/png"
                    upload_resp = await client.upload_file(
                        data=image_data, content_type=content_type, filename=filename
                    )

                    content_uri = upload_resp["content_uri"]
                    content = {
                        "msgtype": "m.image",
                        "body": filename,
                        "url": content_uri,
                    }
                    if reply_to:
                        content["m.relates_to"] = {
                            "m.in_reply_to": {"event_id": reply_to}
                        }

                    await client.send_message(
                        room_id=room_id, msg_type="m.room.message", content=content
                    )
                    sent_count += 1
                except Exception as e:
                    logger.error(f"发送图片消息失败：{e}")

            elif isinstance(segment, File):
                try:
                    file_path = await segment.get_file()
                    if not file_path:
                        logger.warning("文件消息没有可用的文件路径或下载失败")
                        continue

                    with open(file_path, "rb") as f:
                        file_data = f.read()

                    filename = Path(file_path).name
                    content_type = "application/octet-stream"

                    upload_resp = await client.upload_file(
                        data=file_data, content_type=content_type, filename=filename
                    )

                    content_uri = upload_resp["content_uri"]
                    content = {
                        "msgtype": "m.file",
                        "body": filename,
                        "url": content_uri,
                        "filename": filename,
                    }
                    if reply_to:
                        content["m.relates_to"] = {
                            "m.in_reply_to": {"event_id": reply_to}
                        }

                    await client.send_message(
                        room_id=room_id, msg_type="m.room.message", content=content
                    )
                    sent_count += 1
                except Exception as e:
                    logger.error(f"发送文件消息失败：{e}")

        return sent_count

    async def send(self, message_chain: MessageChain):
        """发送消息"""
        self.message_chain = message_chain
        # Matrix 的 room_id 即为会话 ID
        room_id = self.session_id
        await MatrixPlatformEvent.send_with_client(self.client, message_chain, room_id)
        return await super().send(message_chain)

    async def send_streaming(self, generator, use_fallback: bool = False):
        """Matrix 流式发送 - 通过不断编辑同一条消息"""
        import asyncio

        room_id = self.session_id
        delta = ""  # 累积的文本内容
        current_content = ""  # 当前已发送的内容
        message_event_id = None  # 消息的 event_id
        last_edit_time = 0  # 上次编辑消息的时间
        throttle_interval = 0.8  # 编辑消息的间隔时间 (秒)

        async for chain in generator:
            if isinstance(chain, MessageChain):
                # 处理消息链中的每个组件
                for component in chain.chain:
                    if isinstance(component, Plain):
                        delta += component.text
                    else:
                        # 对于非文本组件（图片、文件等），先发送当前的文本
                        if delta and delta != current_content:
                            if message_event_id:
                                try:
                                    # 生成 formatted_body
                                    try:
                                        formatted_body = markdown_to_html(delta)
                                    except Exception as e:
                                        logger.warning(
                                            f"Failed to render markdown: {e}"
                                        )
                                        formatted_body = delta.replace("\n", "<br>")

                                    await self.client.edit_message(
                                        room_id=room_id,
                                        original_event_id=message_event_id,
                                        new_content={
                                            "body": delta,
                                            "format": "org.matrix.custom.html",
                                            "formatted_body": formatted_body,
                                        },
                                    )
                                    current_content = delta
                                except Exception as e:
                                    logger.warning(f"编辑消息失败 (streaming): {e}")
                            else:
                                # 发送第一条消息
                                try:
                                    # 生成 formatted_body
                                    try:
                                        formatted_body = markdown_to_html(delta)
                                    except Exception as e:
                                        logger.warning(
                                            f"Failed to render markdown: {e}"
                                        )
                                        formatted_body = delta.replace("\n", "<br>")

                                    content = {
                                        "msgtype": "m.text",
                                        "body": delta,
                                        "format": "org.matrix.custom.html",
                                        "formatted_body": formatted_body,
                                    }
                                    response = await self.client.send_message(
                                        room_id=room_id,
                                        msg_type="m.room.message",
                                        content=content,
                                    )
                                    message_event_id = response.get("event_id")
                                    current_content = delta
                                except Exception as e:
                                    logger.warning(f"发送消息失败 (streaming): {e}")
                            delta = ""  # 重置 delta

                        # 单独发送非文本组件
                        temp_chain = MessageChain()
                        temp_chain.chain = [component]
                        await self.send(temp_chain)

                # 处理文本累积和节流编辑
                if delta:
                    current_time = asyncio.get_event_loop().time()
                    time_since_last_edit = current_time - last_edit_time

                    if message_event_id and time_since_last_edit >= throttle_interval:
                        # 编辑现有消息
                        try:
                            # 生成 formatted_body
                            try:
                                formatted_body = markdown_to_html(delta)
                            except Exception as e:
                                logger.warning(f"Failed to render markdown: {e}")
                                formatted_body = delta.replace("\n", "<br>")

                            await self.client.edit_message(
                                room_id=room_id,
                                original_event_id=message_event_id,
                                new_content={
                                    "body": delta,
                                    "format": "org.matrix.custom.html",
                                    "formatted_body": formatted_body,
                                },
                            )
                            current_content = delta
                            last_edit_time = asyncio.get_event_loop().time()
                        except Exception as e:
                            logger.warning(f"编辑消息失败 (streaming): {e}")
                    elif not message_event_id:
                        # 发送第一条消息
                        try:
                            # 生成 formatted_body
                            try:
                                formatted_body = markdown_to_html(delta)
                            except Exception as e:
                                logger.warning(f"Failed to render markdown: {e}")
                                formatted_body = delta.replace("\n", "<br>")

                            content = {
                                "msgtype": "m.text",
                                "body": delta,
                                "format": "org.matrix.custom.html",
                                "formatted_body": formatted_body,
                            }
                            response = await self.client.send_message(
                                room_id=room_id,
                                msg_type="m.room.message",
                                content=content,
                            )
                            message_event_id = response.get("event_id")
                            current_content = delta
                            last_edit_time = asyncio.get_event_loop().time()
                        except Exception as e:
                            logger.warning(f"发送消息失败 (streaming): {e}")

        # 最后确保所有内容都已发送
        if delta and current_content != delta:
            try:
                # 生成 formatted_body
                try:
                    formatted_body = markdown_to_html(delta)
                except Exception as e:
                    logger.warning(f"Failed to render markdown: {e}")
                    formatted_body = delta.replace("\n", "<br>")

                if message_event_id:
                    await self.client.edit_message(
                        room_id=room_id,
                        original_event_id=message_event_id,
                        new_content={
                            "body": delta,
                            "format": "org.matrix.custom.html",
                            "formatted_body": formatted_body,
                        },
                    )
                else:
                    content = {
                        "msgtype": "m.text",
                        "body": delta,
                        "format": "org.matrix.custom.html",
                        "formatted_body": formatted_body,
                    }
                    await self.client.send_message(
                        room_id=room_id,
                        msg_type="m.room.message",
                        content=content,
                    )
            except Exception as e:
                logger.warning(f"发送最终消息失败 (streaming): {e}")

        return await super().send_streaming(generator, use_fallback)
