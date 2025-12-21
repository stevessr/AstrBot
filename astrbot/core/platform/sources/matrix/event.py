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
        thread_root: str | None = None,
        use_thread: bool = False,
        original_message_info: dict | None = None,
    ) -> int:
        """使用提供的 client 将指定消息链发送到指定房间。

        Args:
            client: MatrixHTTPClient 实例
            message_chain: 要发送的消息链
            room_id: 目标房间 ID（Matrix 的 roomId）
            reply_to: 可选，被引用的消息 event_id
            thread_root: 可选，嘟文串根消息的 event_id
            use_thread: 是否使用嘟文串模式回复

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

        # Merge adjacent Plain components
        merged_chain = []
        for segment in message_chain.chain:
            if isinstance(segment, Plain) and merged_chain and isinstance(merged_chain[-1], Plain):
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
                # Matrix 规范建议: body 包含 fallback，formatted_body 包含 HTML fallback
                if original_message_info and reply_to:
                    # 简单构建纯文本 fallback
                    # > <@alice:example.org> This is the original message
                    orig_sender = original_message_info.get("sender", "")
                    orig_body = original_message_info.get("body", "")
                    if len(orig_body) > 50:
                        orig_body = orig_body[:50] + "..."
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
                            room_id=room_id
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
                    # 记录发送消息的日志
                    if reply_to:
                        logger.info(f"发送回复消息到房间 {room_id}，回复事件ID: {reply_to}")
                    else:
                        logger.info(f"发送消息到房间 {room_id}")

                    await client.send_message(
                        room_id=room_id, msg_type="m.room.message", content=content
                    )
                    sent_count += 1

                    # 记录发送成功
                    logger.debug(f"消息发送成功，房间: {room_id}，内容预览: {segment.text[:50]}...")
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

                    # 记录发送消息的日志
                    logger.info(f"发送图片消息到房间 {room_id}，文件: {filename}")
                    if reply_to:
                        logger.info(f"  回复事件ID: {reply_to}")

                    # 发送未加密消息
                    await client.send_message(
                        room_id=room_id, msg_type="m.room.message", content=content
                    )
                    sent_count += 1
                    logger.debug(f"图片消息发送成功，房间: {room_id}")
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

                    # 记录发送消息的日志
                    logger.info(f"发送文件消息到房间 {room_id}，文件: {filename}")
                    if reply_to:
                        logger.info(f"  回复事件ID: {reply_to}")

                    try:
                        # 发送未加密消息
                        await client.send_message(
                            room_id=room_id, msg_type="m.room.message", content=content
                        )
                        sent_count += 1
                        logger.debug(f"文件消息发送成功，房间: {room_id}")
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
                        # 如果是嘟文串的一部分，获取根消息ID
                        thread_root = relates_to.get("event_id")
                        use_thread = True
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

        # 记录发送消息的日志
        logger.info(f"Matrix 适配器发送消息到房间 {room_id}")
        if reply_to:
            logger.info(f"  回复事件ID: {reply_to}")
        if thread_root:
            logger.info(f"  嘟文串根事件ID: {thread_root}")

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

        # 嘟文串相关变量
        reply_to = None
        thread_root = None
        use_thread = False
        original_message_info = None

        # 检查第一个消息链是否包含回复信息
        first_chain_processed = False

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
                    # 这是因为流式输出跳过了 ResultDecorateStage，不会自动添加 Reply 组件
                    if not reply_to and self.message_obj and self.message_obj.message_id:
                        reply_to = str(self.message_obj.message_id)

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
                                        # 如果是嘟文串的一部分，获取根消息ID
                                        thread_root = relates_to.get("event_id")
                                        use_thread = True
                                    else:
                                        # 如果不是嘟文串，默认使用普通回复模式
                                        use_thread = False
                                        thread_root = None
                        except Exception as e:
                            logger.warning(f"Failed to get event for threading: {e}")

                    first_chain_processed = True

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

                                    # 如果有回复引用信息，预处理 body 以包含 fallback
                                    if original_message_info and reply_to:
                                        # 简单构建纯文本 fallback
                                        orig_sender = original_message_info.get("sender", "")
                                        orig_body = original_message_info.get("body", "")
                                        if len(orig_body) > 50:
                                            orig_body = orig_body[:50] + "..."
                                        fallback_text = f"> <{orig_sender}> {orig_body}\n\n"
                                        content["body"] = fallback_text + content["body"]

                                        # 为 formatted_body 添加 HTML fallback
                                        from .utils.utils import MatrixUtils
                                        fallback_html = MatrixUtils.create_reply_fallback(
                                            original_body=original_message_info.get("body", ""),
                                            original_sender=original_message_info.get("sender", ""),
                                            original_event_id=reply_to,
                                            room_id=room_id
                                        )
                                        content["formatted_body"] = fallback_html + content["formatted_body"]

                                    # 添加嘟文串支持
                                    if use_thread and thread_root:
                                        content["m.relates_to"] = {
                                            "rel_type": "m.thread",
                                            "event_id": thread_root,
                                            "m.in_reply_to": {"event_id": reply_to}
                                            if reply_to
                                            else None,
                                        }
                                    elif reply_to:
                                        content["m.relates_to"] = {
                                            "m.in_reply_to": {"event_id": reply_to}
                                        }

                                    response = await self.client.send_message(
                                        room_id=room_id,
                                        msg_type="m.room.message",
                                        content=content,
                                    )
                                    message_event_id = response.get("event_id")
                                    current_content = delta

                                    # 记录流式发送第一条消息
                                    logger.info(f"流式发送第一条消息到房间 {room_id}，事件ID: {message_event_id}")
                                    if reply_to:
                                        logger.info(f"  回复事件ID: {reply_to}")
                                except Exception as e:
                                    logger.error(f"发送消息失败 (streaming): {e}")
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

                            content: dict[str, Any] = {
                                "msgtype": "m.text",
                                "body": delta,
                                "format": "org.matrix.custom.html",
                                "formatted_body": formatted_body,
                            }

                            # 如果有回复引用信息，预处理 body 以包含 fallback
                            if original_message_info and reply_to:
                                # 简单构建纯文本 fallback
                                orig_sender = original_message_info.get("sender", "")
                                orig_body = original_message_info.get("body", "")
                                if len(orig_body) > 50:
                                    orig_body = orig_body[:50] + "..."
                                fallback_text = f"> <{orig_sender}> {orig_body}\n\n"
                                content["body"] = fallback_text + content["body"]

                                # 为 formatted_body 添加 HTML fallback
                                from .utils.utils import MatrixUtils
                                fallback_html = MatrixUtils.create_reply_fallback(
                                    original_body=original_message_info.get("body", ""),
                                    original_sender=original_message_info.get("sender", ""),
                                    original_event_id=reply_to,
                                    room_id=room_id
                                )
                                content["formatted_body"] = fallback_html + content["formatted_body"]

                            # 添加嘟文串支持
                            if use_thread and thread_root:
                                content["m.relates_to"] = {
                                    "rel_type": "m.thread",
                                    "event_id": thread_root,
                                    "m.in_reply_to": {"event_id": reply_to}
                                    if reply_to
                                    else None,
                                }
                            elif reply_to:
                                content["m.relates_to"] = {
                                    "m.in_reply_to": {"event_id": reply_to}
                                }

                            response = await self.client.send_message(
                                room_id=room_id,
                                msg_type="m.room.message",
                                content=content,
                            )
                            message_event_id = response.get("event_id")
                            current_content = delta
                            last_edit_time = asyncio.get_event_loop().time()

                            # 记录流式发送消息
                            logger.info(f"流式发送消息到房间 {room_id}，事件ID: {message_event_id}")
                            if reply_to:
                                logger.info(f"  回复事件ID: {reply_to}")
                        except Exception as e:
                            logger.error(f"发送消息失败 (streaming): {e}")

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

                    # 如果有回复引用信息，预处理 body 以包含 fallback
                    if original_message_info and reply_to:
                        # 简单构建纯文本 fallback
                        orig_sender = original_message_info.get("sender", "")
                        orig_body = original_message_info.get("body", "")
                        if len(orig_body) > 50:
                            orig_body = orig_body[:50] + "..."
                        fallback_text = f"> <{orig_sender}> {orig_body}\n\n"
                        content["body"] = fallback_text + content["body"]

                        # 为 formatted_body 添加 HTML fallback
                        from .utils.utils import MatrixUtils
                        fallback_html = MatrixUtils.create_reply_fallback(
                            original_body=original_message_info.get("body", ""),
                            original_sender=original_message_info.get("sender", ""),
                            original_event_id=reply_to,
                            room_id=room_id
                        )
                        content["formatted_body"] = fallback_html + content["formatted_body"]

                    # 添加嘟文串支持
                    if use_thread and thread_root:
                        content["m.relates_to"] = {
                            "rel_type": "m.thread",
                            "event_id": thread_root,
                            "m.in_reply_to": {"event_id": reply_to}
                            if reply_to
                            else None,
                        }
                    elif reply_to:
                        content["m.relates_to"] = {
                            "m.in_reply_to": {"event_id": reply_to}
                        }

                    await self.client.send_message(
                        room_id=room_id, msg_type="m.room.message", content=content
                    )

                    # 记录流式发送最终消息
                    logger.info(f"流式发送最终消息到房间 {room_id}")
                    if reply_to:
                        logger.info(f"  回复事件ID: {reply_to}")
            except Exception as e:
                logger.error(f"发送最终消息失败 (streaming): {e}")

        return await super().send_streaming(generator, use_fallback)
