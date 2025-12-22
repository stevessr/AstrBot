import mimetypes
from pathlib import Path
from typing import Any

from astrbot import logger
from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.message_components import File, Image, Plain, Reply
from astrbot.api.platform import AstrBotMessage, PlatformMetadata

# Update import: markdown_utils is now in utils.markdown_utils
from .utils.markdown_utils import (
    markdown_to_html,
)
from .constants import TEXT_TRUNCATE_LENGTH_50


class MatrixPlatformEvent(AstrMessageEvent):
    """Matrix 平台事件处理器（不依赖 matrix-nio）"""

    def __init__(
        self,
        message_str: str,
        message_obj: AstrBotMessage,
        platform_meta: PlatformMetadata,
        session_id: str,
        client,
        enable_threading: bool = False,
    ):
        super().__init__(message_str, message_obj, platform_meta, session_id)
        self.client = client  # MatrixHTTPClient instance
        self.enable_threading = enable_threading  # 试验性：是否默认开启嘟文串模式

    @staticmethod
    async def send_with_client(
        client,
        message_chain: MessageChain,
        room_id: str,
        reply_to: str | None = None,
        thread_root: str | None = None,
        use_thread: bool = False,
        original_message_info: dict | None = None,
        e2ee_manager=None,
    ) -> int:
        """使用提供的 client 将指定消息链发送到指定房间。

        Args:
            client: MatrixHTTPClient 实例
            message_chain: 要发送的消息链
            room_id: 目标房间 ID（Matrix 的 roomId）
            reply_to: 可选，被引用的消息 event_id
            thread_root: 可选，嘟文串根消息的 event_id
            use_thread: 是否使用嘟文串模式回复
            original_message_info: 可选，原始消息信息（用于回复）
            e2ee_manager: 可选，E2EEManager 实例（用于加密消息）

        Returns:
            已发送的消息段数量
        """
        sent_count = 0

        # 检查房间是否需要加密
        is_encrypted_room = False
        if e2ee_manager:
            try:
                is_encrypted_room = await client.is_room_encrypted(room_id)
                if is_encrypted_room:
                    logger.debug(f"房间 {room_id} 已加密，将使用 E2EE 发送消息")
            except Exception as e:
                logger.debug(f"检查房间加密状态失败：{e}")

        # 若未显式传入 reply_to，则尝试从消息链中提取 Reply 段
        if reply_to is None:
            for seg in message_chain.chain:
                if isinstance(seg, Reply) and getattr(seg, "id", None):
                    reply_to = str(seg.id)
                    break

        # Merge adjacent Plain components
        merged_chain = []
        for segment in message_chain.chain:
            if (
                isinstance(segment, Plain)
                and merged_chain
                and isinstance(merged_chain[-1], Plain)
            ):
                merged_chain[-1].text += segment.text
            else:
                merged_chain.append(segment)

        # Use a temporary chain for iteration
        chain_to_send = merged_chain

        for segment in chain_to_send:
            # Reply 段仅用于标注引用关系，实际发送时跳过
            if isinstance(segment, Reply):
                continue
            if isinstance(segment, Plain):
                # 发送支持 Markdown 渲染的文本消息
                content = {
                    "msgtype": "m.text",
                    "body": segment.text,
                }

                # 如果有回复引用信息，预处理 body 以包含 fallback (纯文本部分)
                # Matrix 规范建议：body 包含 fallback，formatted_body 包含 HTML fallback
                if original_message_info and reply_to:
                    orig_sender = original_message_info.get("sender", "")
                    orig_body = original_message_info.get("body", "")
                    if len(orig_body) > TEXT_TRUNCATE_LENGTH_50:
                        orig_body = orig_body[:TEXT_TRUNCATE_LENGTH_50] + "..."
                    fallback_text = f"> <{orig_sender}> {orig_body}\n\n"
                    # 这里更新 content["body"]，使其包含引用文本
                    content["body"] = fallback_text + content["body"]

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
                    # 如果有回复引用信息，添加 HTML fallback
                    if original_message_info and reply_to:
                        from .utils.utils import MatrixUtils

                        fallback_html = MatrixUtils.create_reply_fallback(
                            original_body=original_message_info.get("body", ""),
                            original_sender=original_message_info.get("sender", ""),
                            original_event_id=reply_to,
                            room_id=room_id,
                        )
                        formatted_body = fallback_html + formatted_body
                        # 确保 format 字段被设置
                        content["format"] = "org.matrix.custom.html"

                    content["formatted_body"] = formatted_body

                # 处理回复关系
                if use_thread and thread_root:
                    # 使用嘟文串模式
                    content["m.relates_to"] = {
                        "rel_type": "m.thread",
                        "event_id": thread_root,
                        "m.in_reply_to": {"event_id": reply_to} if reply_to else None,
                    }
                elif reply_to:
                    # 普通回复模式
                    content["m.relates_to"] = {"m.in_reply_to": {"event_id": reply_to}}

                try:
                    # 如果房间已加密，使用 E2EE 加密消息
                    if is_encrypted_room and e2ee_manager:
                        encrypted = await e2ee_manager.encrypt_message(
                            room_id, "m.room.message", content
                        )
                        if encrypted:
                            await client.send_message(
                                room_id=room_id,
                                msg_type="m.room.encrypted",
                                content=encrypted,
                            )
                            sent_count += 1
                        else:
                            logger.warning("加密消息失败，尝试发送未加密消息")
                            await client.send_message(
                                room_id=room_id,
                                msg_type="m.room.message",
                                content=content,
                            )
                            sent_count += 1
                    else:
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

                    # 获取图片尺寸
                    width, height = None, None
                    try:
                        import io

                        from PIL import Image as PILImage

                        with PILImage.open(io.BytesIO(image_data)) as img:
                            width, height = img.size
                    except Exception as e:
                        logger.debug(f"无法获取图片尺寸：{e}")

                    # 猜测内容类型，默认使用 image/png
                    content_type = mimetypes.guess_type(filename)[0] or "image/png"
                    upload_resp = await client.upload_file(
                        data=image_data, content_type=content_type, filename=filename
                    )

                    content_uri = upload_resp["content_uri"]

                    # 构建 info 字段
                    info: dict[str, Any] = {
                        "mimetype": content_type,
                        "size": len(image_data),
                    }
                    if width and height:
                        info["w"] = width
                        info["h"] = height

                    content = {
                        "msgtype": "m.image",
                        "body": filename,
                        "url": content_uri,
                        "info": info,
                    }

                    # 处理回复关系
                    if use_thread and thread_root:
                        # 使用嘟文串模式
                        content["m.relates_to"] = {
                            "rel_type": "m.thread",
                            "event_id": thread_root,
                            "m.in_reply_to": {"event_id": reply_to}
                            if reply_to
                            else None,
                        }
                    elif reply_to:
                        # 普通回复模式
                        content["m.relates_to"] = {
                            "m.in_reply_to": {"event_id": reply_to}
                        }

                    # 发送未加密消息
                    await client.send_message(
                        room_id=room_id, msg_type="m.room.message", content=content
                    )
                    sent_count += 1
                    logger.debug(f"图片消息发送成功，房间：{room_id}")
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

                    # 处理回复关系
                    if use_thread and thread_root:
                        # 使用嘟文串模式
                        content["m.relates_to"] = {
                            "rel_type": "m.thread",
                            "event_id": thread_root,
                            "m.in_reply_to": {"event_id": reply_to}
                            if reply_to
                            else None,
                        }
                    elif reply_to:
                        # 普通回复模式
                        content["m.relates_to"] = {
                            "m.in_reply_to": {"event_id": reply_to}
                        }

                    try:
                        # 发送未加密消息
                        await client.send_message(
                            room_id=room_id, msg_type="m.room.message", content=content
                        )
                        sent_count += 1
                    except Exception as e:
                        logger.error(f"发送文件消息失败：{e}")
                except Exception as e:
                    logger.error(f"处理文件消息过程出错：{e}")

        return sent_count

    async def send(self, message_chain: MessageChain):
        """发送消息"""
        self.message_chain = message_chain
        # Matrix 的 room_id 即为会话 ID
        room_id = self.session_id

        # 检查是否需要使用嘟文串模式
        reply_to = None
        thread_root = None
        use_thread = False

        # 尝试从消息链中提取 Reply 段
        try:
            from astrbot.api.message_components import Reply as _Reply

            for seg in message_chain.chain:
                if isinstance(seg, _Reply) and getattr(seg, "id", None):
                    reply_to = str(seg.id)
                    break
        except Exception:
            pass

        # 如果有回复，检查是否需要使用嘟文串模式
        if reply_to:
            try:
                # 获取被回复消息的事件信息
                resp = await self.client.get_event(room_id, reply_to)
                if resp:
                    # 提取原始消息信息用于 fallback
                    original_message_info = {
                        "sender": resp.get("sender", ""),
                        "body": resp.get("content", {}).get("body", ""),
                    }

                if resp and "content" in resp:
                    # 检查被回复消息是否已经是嘟文串的一部分
                    relates_to = resp["content"].get("m.relates_to", {})
                    if relates_to.get("rel_type") == "m.thread":
                        # 如果是嘟文串的一部分，获取根消息 ID
                        thread_root = relates_to.get("event_id")
                        use_thread = True
                    elif self.enable_threading:
                        # 试验性功能：如果启用嘟文串模式，创建新的嘟文串
                        use_thread = True
                        thread_root = reply_to  # 将被回复的消息作为嘟文串根
                    else:
                        # 如果不是嘟文串，不要强制开启嘟文串模式，使用标准回复
                        use_thread = False
                        thread_root = None
            except Exception as e:
                logger.warning(f"Failed to get event for threading: {e}")
        else:
            original_message_info = None

        await MatrixPlatformEvent.send_with_client(
            self.client,
            message_chain,
            room_id,
            reply_to=reply_to,
            thread_root=thread_root,
            use_thread=use_thread,
            original_message_info=original_message_info,
        )

        return await super().send(message_chain)

    async def send_streaming(self, generator, use_fallback: bool = False):
        """Matrix 流式发送 - 直接消费上游流式输出，累积后整块发送"""
        room_id = self.session_id
        accumulated_text = ""  # 累积的文本内容
        non_text_components = []  # 非文本组件列表
        typing_timeout = 30000  # 输入指示超时时间 (毫秒)

        # 嘟文串相关变量
        reply_to = None
        thread_root = None
        use_thread = False
        original_message_info = None

        # 检查第一个消息链是否包含回复信息
        first_chain_processed = False

        # 开启输入指示
        try:
            await self.client.set_typing(room_id, typing=True, timeout=typing_timeout)
        except Exception as e:
            logger.debug(f"发送输入指示失败：{e}")

        try:
            async for chain in generator:
                if isinstance(chain, MessageChain):
                    # 只在第一个消息链中检查回复信息
                    if not first_chain_processed:
                        try:
                            from astrbot.api.message_components import Reply as _Reply

                            for seg in chain.chain:
                                if isinstance(seg, _Reply) and getattr(seg, "id", None):
                                    reply_to = str(seg.id)
                                    break
                        except Exception:
                            pass

                        # 如果 message chain 中没有 Reply，则使用原始消息 ID 作为回复目标
                        if (
                            not reply_to
                            and self.message_obj
                            and self.message_obj.message_id
                        ):
                            reply_to = str(self.message_obj.message_id)

                        # 如果有回复，检查是否需要使用嘟文串模式
                        if reply_to:
                            try:
                                resp = await self.client.get_event(room_id, reply_to)
                                if resp:
                                    original_message_info = {
                                        "sender": resp.get("sender", ""),
                                        "body": resp.get("content", {}).get("body", ""),
                                    }
                                    if resp and "content" in resp:
                                        relates_to = resp["content"].get(
                                            "m.relates_to", {}
                                        )
                                        if relates_to.get("rel_type") == "m.thread":
                                            thread_root = relates_to.get("event_id")
                                            use_thread = True
                                        elif self.enable_threading:
                                            use_thread = True
                                            thread_root = reply_to
                                        else:
                                            use_thread = False
                                            thread_root = None
                            except Exception as e:
                                logger.warning(
                                    f"Failed to get event for threading: {e}"
                                )

                        first_chain_processed = True

                    # 累积消息链中的所有组件
                    for component in chain.chain:
                        if isinstance(component, Plain):
                            accumulated_text += component.text
                        elif not isinstance(component, Reply):
                            # 非文本、非 Reply 组件收集起来
                            non_text_components.append(component)

        finally:
            # 关闭输入指示
            try:
                await self.client.set_typing(room_id, typing=False)
            except Exception as e:
                logger.debug(f"停止输入指示失败：{e}")

        # 发送累积的文本内容
        if accumulated_text:
            try:
                # 生成 formatted_body
                try:
                    formatted_body = markdown_to_html(accumulated_text)
                except Exception as e:
                    logger.warning(f"Failed to render markdown: {e}")
                    formatted_body = accumulated_text.replace("\n", "<br>")

                content: dict[str, Any] = {
                    "msgtype": "m.text",
                    "body": accumulated_text,
                    "format": "org.matrix.custom.html",
                    "formatted_body": formatted_body,
                }

                # 如果有回复引用信息，添加 fallback
                if original_message_info and reply_to:
                    orig_sender = original_message_info.get("sender", "")
                    orig_body = original_message_info.get("body", "")
                    if len(orig_body) > TEXT_TRUNCATE_LENGTH_50:
                        orig_body = orig_body[:TEXT_TRUNCATE_LENGTH_50] + "..."
                    fallback_text = f"> <{orig_sender}> {orig_body}\n\n"
                    content["body"] = fallback_text + content["body"]

                    from .utils.utils import MatrixUtils

                    fallback_html = MatrixUtils.create_reply_fallback(
                        original_body=original_message_info.get("body", ""),
                        original_sender=original_message_info.get("sender", ""),
                        original_event_id=reply_to,
                        room_id=room_id,
                    )
                    content["formatted_body"] = (
                        fallback_html + content["formatted_body"]
                    )

                # 添加嘟文串支持
                if use_thread and thread_root:
                    content["m.relates_to"] = {
                        "rel_type": "m.thread",
                        "event_id": thread_root,
                        "m.in_reply_to": {"event_id": reply_to} if reply_to else None,
                    }
                elif reply_to:
                    content["m.relates_to"] = {"m.in_reply_to": {"event_id": reply_to}}

                await self.client.send_message(
                    room_id=room_id,
                    msg_type="m.room.message",
                    content=content,
                )
            except Exception as e:
                logger.error(f"发送消息失败 (streaming): {e}")

        # 发送非文本组件（图片、文件等）
        for component in non_text_components:
            try:
                temp_chain = MessageChain()
                temp_chain.chain = [component]
                await MatrixPlatformEvent.send_with_client(
                    self.client,
                    temp_chain,
                    room_id,
                    reply_to=reply_to,
                    thread_root=thread_root,
                    use_thread=use_thread,
                    original_message_info=original_message_info,
                )
            except Exception as e:
                logger.error(f"发送非文本组件失败：{e}")

        return await super().send_streaming(generator, use_fallback)
