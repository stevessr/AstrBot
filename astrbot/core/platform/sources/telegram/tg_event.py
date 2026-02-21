import asyncio
import os
import re
from typing import Any, cast

import telegramify_markdown
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReactionTypeCustomEmoji,
    ReactionTypeEmoji,
)
from telegram.constants import ChatAction
from telegram.error import BadRequest
from telegram.ext import ExtBot

from astrbot import logger
from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.message_components import (
    At,
    File,
    Image,
    Plain,
    Record,
    Reply,
    Video,
)
from astrbot.api.platform import AstrBotMessage, MessageType, PlatformMetadata
from astrbot.core import sp


class TelegramPlatformEvent(AstrMessageEvent):
    # Telegram 的最大消息长度限制
    MAX_MESSAGE_LENGTH = 4096

    SPLIT_PATTERNS = {
        "paragraph": re.compile(r"\n\n"),
        "line": re.compile(r"\n"),
        "sentence": re.compile(r"[.!?。！？]"),
        "word": re.compile(r"\s"),
    }

    # 消息类型到 chat action 的映射，用于优先级判断
    ACTION_BY_TYPE: dict[type, str] = {
        Record: ChatAction.UPLOAD_VOICE,
        Video: ChatAction.UPLOAD_VIDEO,
        File: ChatAction.UPLOAD_DOCUMENT,
        Image: ChatAction.UPLOAD_PHOTO,
        Plain: ChatAction.TYPING,
    }

    def __init__(
        self,
        message_str: str,
        message_obj: AstrBotMessage,
        platform_meta: PlatformMetadata,
        session_id: str,
        client: ExtBot,
    ) -> None:
        super().__init__(message_str, message_obj, platform_meta, session_id)
        self.client = client

    @classmethod
    def _split_message(cls, text: str) -> list[str]:
        if len(text) <= cls.MAX_MESSAGE_LENGTH:
            return [text]

        chunks = []
        while text:
            if len(text) <= cls.MAX_MESSAGE_LENGTH:
                chunks.append(text)
                break

            split_point = cls.MAX_MESSAGE_LENGTH
            segment = text[: cls.MAX_MESSAGE_LENGTH]

            for _, pattern in cls.SPLIT_PATTERNS.items():
                if matches := list(pattern.finditer(segment)):
                    last_match = matches[-1]
                    split_point = last_match.end()
                    break

            chunks.append(text[:split_point])
            text = text[split_point:].lstrip()

        return chunks

    @classmethod
    async def _send_chat_action(
        cls,
        client: ExtBot,
        chat_id: str,
        action: ChatAction | str,
        message_thread_id: str | None = None,
    ) -> None:
        """发送聊天状态动作"""
        try:
            payload: dict[str, Any] = {"chat_id": chat_id, "action": action}
            if message_thread_id:
                payload["message_thread_id"] = message_thread_id
            await client.send_chat_action(**payload)
        except Exception as e:
            logger.warning(f"[Telegram] 发送 chat action 失败：{e}")

    @classmethod
    def _get_chat_action_for_chain(cls, chain: list[Any]) -> ChatAction | str:
        """根据消息链中的组件类型确定合适的 chat action（按优先级）"""
        for seg_type, action in cls.ACTION_BY_TYPE.items():
            if any(isinstance(seg, seg_type) for seg in chain):
                return action
        return ChatAction.TYPING

    @staticmethod
    def _is_gif_file(path: str) -> bool:
        if not path:
            return False
        normalized = path.split("?", 1)[0].split("#", 1)[0].lower()
        return normalized.endswith(".gif")

    @classmethod
    async def _send_media_with_action(
        cls,
        client: ExtBot,
        upload_action: ChatAction | str,
        send_coro,
        *,
        user_name: str,
        message_thread_id: str | None = None,
        **payload: Any,
    ) -> Any:
        """发送媒体时显示 upload action，发送完成后恢复 typing"""
        effective_thread_id = message_thread_id or cast(
            str | None, payload.get("message_thread_id")
        )
        result = await send_coro(**payload)
        await cls._send_chat_action(
            client, user_name, upload_action, effective_thread_id
        )
        send_payload = dict(payload)
        if effective_thread_id and "message_thread_id" not in send_payload:
            send_payload["message_thread_id"] = effective_thread_id
        await send_coro(**send_payload)
        await cls._send_chat_action(
            client, user_name, ChatAction.TYPING, effective_thread_id
        )
        return result

    @classmethod
    async def _send_voice_with_fallback(
        cls,
        client: ExtBot,
        path: str,
        payload: dict[str, Any],
        *,
        caption: str | None = None,
        user_name: str = "",
        message_thread_id: str | None = None,
        use_media_action: bool = False,
    ) -> Any:
        """Send a voice message, falling back to a document if the user's
        privacy settings forbid voice messages (``BadRequest`` with
        ``Voice_messages_forbidden``).

        When *use_media_action* is ``True`` the helper wraps the send calls
        with ``_send_media_with_action`` (used by the streaming path).
        """
        try:
            if use_media_action:
                media_payload = dict(payload)
                if message_thread_id and "message_thread_id" not in media_payload:
                    media_payload["message_thread_id"] = message_thread_id
                await cls._send_media_with_action(
                    client,
                    ChatAction.UPLOAD_VOICE,
                    client.send_voice,
                    user_name=user_name,
                    voice=path,
                    **cast(Any, media_payload),
                )
            return await client.send_voice(voice=path, **cast(Any, payload))
        except BadRequest as e:
            # python-telegram-bot raises BadRequest for Voice_messages_forbidden;
            # distinguish the voice-privacy case via the API error message.
            if "Voice_messages_forbidden" not in e.message:
                raise
            logger.warning(
                "User privacy settings prevent receiving voice messages, falling back to sending an audio file. "
                "To enable voice messages, go to Telegram Settings → Privacy and Security → Voice Messages → set to 'Everyone'."
            )
            if use_media_action:
                media_payload = dict(payload)
                if message_thread_id and "message_thread_id" not in media_payload:
                    media_payload["message_thread_id"] = message_thread_id
                await cls._send_media_with_action(
                    client,
                    ChatAction.UPLOAD_DOCUMENT,
                    client.send_document,
                    user_name=user_name,
                    document=path,
                    caption=caption,
                    **cast(Any, media_payload),
                )
            return await client.send_document(
                document=path,
                caption=caption,
                **cast(Any, payload),
            )

    @staticmethod
    def _build_file_id_cache_key(file_unique: str) -> str:
        return f"telegram_file_id_cache::{file_unique}"

    @staticmethod
    def _normalize_cached_media_value(cache_value: Any) -> dict[str, str] | None:
        if not isinstance(cache_value, dict):
            return None
        file_id = str(cache_value.get("file_id", "") or "").strip()
        media_type = str(cache_value.get("media_type", "") or "").strip().lower()
        if not file_id or media_type not in {"photo", "animation"}:
            return None
        return {"file_id": file_id, "media_type": media_type}

    @classmethod
    async def _get_cached_file_id(
        cls,
        adapter_id: str,
        file_unique: str,
    ) -> dict[str, str] | None:
        cache_key = cls._build_file_id_cache_key(file_unique)
        cache_value = await sp.get_async(
            scope="platform",
            scope_id=adapter_id,
            key=cache_key,
            default=None,
        )
        return cls._normalize_cached_media_value(cache_value)

    @classmethod
    async def _set_cached_file_id(
        cls,
        adapter_id: str,
        file_unique: str,
        file_id: str,
        media_type: str,
    ) -> None:
        normalized_file_id = str(file_id or "").strip()
        normalized_media_type = str(media_type or "").strip().lower()
        if not normalized_file_id or normalized_media_type not in {
            "photo",
            "animation",
        }:
            return
        cache_key = cls._build_file_id_cache_key(file_unique)
        await sp.put_async(
            scope="platform",
            scope_id=adapter_id,
            key=cache_key,
            value={
                "file_id": normalized_file_id,
                "media_type": normalized_media_type,
            },
        )

    @classmethod
    async def _remove_cached_file_id(
        cls,
        adapter_id: str,
        file_unique: str,
    ) -> None:
        cache_key = cls._build_file_id_cache_key(file_unique)
        await sp.remove_async(scope="platform", scope_id=adapter_id, key=cache_key)

    @staticmethod
    def _extract_sent_message_file_id(sent_message: Any, media_type: str) -> str | None:
        normalized_media_type = str(media_type or "").strip().lower()
        if normalized_media_type == "photo":
            photos = getattr(sent_message, "photo", None) or []
            if photos:
                return str(getattr(photos[-1], "file_id", "") or "").strip() or None
            return None
        if normalized_media_type == "animation":
            animation = getattr(sent_message, "animation", None)
            if animation is None:
                return None
            return str(getattr(animation, "file_id", "") or "").strip() or None
        return None

    @staticmethod
    def _get_media_send_meta(media_type: str) -> tuple[str, ChatAction | str, Any]:
        normalized_media_type = str(media_type or "").strip().lower()
        if normalized_media_type == "animation":
            return "animation", ChatAction.UPLOAD_VIDEO, "animation"
        return "photo", ChatAction.UPLOAD_PHOTO, "photo"

    @classmethod
    async def _send_image_with_file_id_cache(
        cls,
        client: ExtBot,
        image: Image,
        payload: dict[str, Any],
        *,
        adapter_id: str,
        user_name: str = "",
        message_thread_id: str | None = None,
        use_media_action: bool = False,
    ) -> Any:
        file_unique = str(getattr(image, "file_unique", "") or "").strip()

        async def _send_media(media_value: str, media_type: str) -> Any:
            media_arg, upload_action, send_method_name = cls._get_media_send_meta(media_type)
            send_coro = getattr(client, f"send_{send_method_name}")
            media_payload = dict(payload)
            media_payload[media_arg] = media_value
            if use_media_action:
                return await cls._send_media_with_action(
                    client,
                    upload_action,
                    send_coro,
                    user_name=user_name,
                    message_thread_id=message_thread_id,
                    **cast(Any, media_payload),
                )
            return await send_coro(**cast(Any, media_payload))

        if file_unique:
            cached_value = await cls._get_cached_file_id(adapter_id, file_unique)
            if cached_value:
                cached_file_id = str(cached_value.get("file_id", "") or "").strip()
                cached_media_type = str(cached_value.get("media_type", "") or "").strip().lower()
                if cached_file_id and cached_media_type in {"photo", "animation"}:
                    try:
                        return await _send_media(cached_file_id, cached_media_type)
                    except BadRequest as e:
                        logger.debug(
                            f"[Telegram] Cached file_id invalid for {file_unique}: {e}"
                        )
                        await cls._remove_cached_file_id(adapter_id, file_unique)
                    except Exception as e:
                        logger.debug(
                            f"[Telegram] Cached file_id send failed for {file_unique}: {e}"
                        )

        image_path = await image.convert_to_file_path()
        media_type = "animation" if cls._is_gif_file(image_path) else "photo"
        sent_message = await _send_media(image_path, media_type)

        if file_unique:
            sent_file_id = cls._extract_sent_message_file_id(sent_message, media_type)
            if sent_file_id:
                await cls._set_cached_file_id(
                    adapter_id,
                    file_unique,
                    sent_file_id,
                    media_type,
                )

        return sent_message

    async def _ensure_typing(
        self,
        user_name: str,
        message_thread_id: str | None = None,
    ) -> None:
        """确保显示 typing 状态"""
        await self._send_chat_action(
            self.client, user_name, ChatAction.TYPING, message_thread_id
        )

    async def send_typing(self) -> None:
        message_thread_id = None
        if self.get_message_type() == MessageType.GROUP_MESSAGE:
            user_name = self.message_obj.group_id
        else:
            user_name = self.get_sender_id()

        if "#" in user_name:
            user_name, message_thread_id = user_name.split("#")

        await self._ensure_typing(user_name, message_thread_id)

    @classmethod
    async def send_with_client(
        cls,
        client: ExtBot,
        message: MessageChain,
        user_name: str,
        adapter_id: str = "telegram",
    ) -> None:
        buttons = getattr(message, "buttons", None)
        reply_markup = None
        if buttons:
            keyboard = [
                [InlineKeyboardButton(text=label, callback_data=data)]
                for label, data in buttons
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
        buttons_used = False

        has_reply = False
        reply_message_id = None
        at_user_id = None
        for i in message.chain:
            if isinstance(i, Reply):
                has_reply = True
                reply_message_id = i.id
            if isinstance(i, At):
                at_user_id = i.name

        at_flag = False
        message_thread_id = None
        if "#" in user_name:
            # it's a supergroup chat with message_thread_id
            user_name, message_thread_id = user_name.split("#")

        # 根据消息链确定合适的 chat action 并发送
        action = cls._get_chat_action_for_chain(message.chain)
        await cls._send_chat_action(client, user_name, action, message_thread_id)

        for i in message.chain:
            payload = {
                "chat_id": user_name,
            }
            if has_reply:
                payload["reply_to_message_id"] = str(reply_message_id)
            if message_thread_id:
                payload["message_thread_id"] = message_thread_id

            if isinstance(i, Plain):
                if at_user_id and not at_flag:
                    i.text = f"@{at_user_id} {i.text}"
                    at_flag = True
                chunks = cls._split_message(i.text)
                for chunk in chunks:
                    try:
                        md_text = telegramify_markdown.markdownify(
                            chunk,
                            normalize_whitespace=False,
                        )
                        payload_local = dict(payload)
                        if reply_markup and not buttons_used:
                            payload_local["reply_markup"] = reply_markup
                            buttons_used = True
                        await client.send_message(
                            text=md_text,
                            parse_mode="MarkdownV2",
                            **cast(Any, payload_local),
                        )
                    except Exception as e:
                        logger.warning(
                            f"MarkdownV2 send failed: {e}. Using plain text instead.",
                        )
                        payload_local = dict(payload)
                        if reply_markup and not buttons_used:
                            payload_local["reply_markup"] = reply_markup
                            buttons_used = True
                        await client.send_message(
                            text=chunk,
                            **cast(Any, payload_local),
                        )
            elif isinstance(i, Image):
                payload_local = dict(payload)
                if reply_markup and not buttons_used:
                    payload_local["reply_markup"] = reply_markup
                    buttons_used = True
                await cls._send_image_with_file_id_cache(
                    client,
                    i,
                    payload_local,
                    adapter_id=adapter_id,
                    user_name=user_name,
                    message_thread_id=message_thread_id,
                    use_media_action=False,
                )
            elif isinstance(i, File):
                path = await i.get_file()
                name = i.name or os.path.basename(path)
                await client.send_document(
                    document=path, filename=name, **cast(Any, payload)
                )
            elif isinstance(i, Record):
                path = await i.convert_to_file_path()
                await cls._send_voice_with_fallback(
                    client,
                    path,
                    payload,
                    caption=i.text or None,
                    use_media_action=False,
                )
            elif isinstance(i, Video):
                path = await i.convert_to_file_path()
                await client.send_video(
                    video=path,
                    caption=getattr(i, "text", None) or None,
                    **cast(Any, payload),
                )

    async def send(self, message: MessageChain) -> None:
        adapter_id = str(getattr(self.platform_meta, "id", "telegram") or "telegram")
        if self.get_message_type() == MessageType.GROUP_MESSAGE:
            await self.send_with_client(
                self.client,
                message,
                self.message_obj.group_id,
                adapter_id=adapter_id,
            )
        else:
            await self.send_with_client(
                self.client,
                message,
                self.get_sender_id(),
                adapter_id=adapter_id,
            )
        await super().send(message)

    async def react(self, emoji: str | None, big: bool = False) -> None:
        """给原消息添加 Telegram 反应：
        - 普通 emoji：传入 '👍'、'😂' 等
        - 自定义表情：传入其 custom_emoji_id（纯数字字符串）
        - 取消本机器人的反应：传入 None 或空字符串
        """
        try:
            # 解析 chat_id（去掉超级群的 "#<thread_id>" 片段）
            if self.get_message_type() == MessageType.GROUP_MESSAGE:
                chat_id = (self.message_obj.group_id or "").split("#")[0]
            else:
                chat_id = self.get_sender_id()

            message_id = int(self.message_obj.message_id)

            # 组装 reaction 参数（必须是 ReactionType 的列表）
            if not emoji:  # 清空本 bot 的反应
                reaction_param = []  # 空列表表示移除本 bot 的反应
            elif emoji.isdigit():  # 自定义表情：传 custom_emoji_id
                reaction_param = [ReactionTypeCustomEmoji(emoji)]
            else:  # 普通 emoji
                reaction_param = [ReactionTypeEmoji(emoji)]

            await self.client.set_message_reaction(
                chat_id=chat_id,
                message_id=message_id,
                reaction=reaction_param,  # 注意是列表
                is_big=big,  # 可选：大动画
            )
        except Exception as e:
            logger.error(f"[Telegram] 添加反应失败：{e}")

    async def send_streaming(self, generator, use_fallback: bool = False):
        adapter_id = str(getattr(self.platform_meta, "id", "telegram") or "telegram")
        message_thread_id = None

        if self.get_message_type() == MessageType.GROUP_MESSAGE:
            user_name = self.message_obj.group_id
        else:
            user_name = self.get_sender_id()

        if "#" in user_name:
            # it's a supergroup chat with message_thread_id
            user_name, message_thread_id = user_name.split("#")
        payload = {
            "chat_id": user_name,
        }
        if message_thread_id:
            payload["message_thread_id"] = message_thread_id

        delta = ""
        current_content = ""
        message_id = None
        last_edit_time = 0  # 上次编辑消息的时间
        throttle_interval = 0.6  # 编辑消息的间隔时间 (秒)
        last_chat_action_time = 0  # 上次发送 chat action 的时间
        chat_action_interval = 0.5  # chat action 的节流间隔 (秒)

        # 发送初始 typing 状态
        await self._ensure_typing(user_name, message_thread_id)
        last_chat_action_time = asyncio.get_event_loop().time()

        async for chain in generator:
            if isinstance(chain, MessageChain):
                if chain.type == "break":
                    # 分割符
                    if message_id:
                        try:
                            await self.client.edit_message_text(
                                text=delta,
                                chat_id=payload["chat_id"],
                                message_id=message_id,
                            )
                        except Exception as e:
                            logger.warning(f"编辑消息失败 (streaming-break): {e!s}")
                    message_id = None  # 重置消息 ID
                    delta = ""  # 重置 delta
                    continue

                # 处理消息链中的每个组件
                for i in chain.chain:
                    if isinstance(i, Plain):
                        delta += i.text
                    elif isinstance(i, Image):
                        await self._send_image_with_file_id_cache(
                            self.client,
                            i,
                            payload,
                            adapter_id=adapter_id,
                            user_name=user_name,
                            message_thread_id=message_thread_id,
                            use_media_action=True,
                        )
                        continue
                    elif isinstance(i, File):
                        path = await i.get_file()
                        name = i.name or os.path.basename(path)
                        await self._send_media_with_action(
                            self.client,
                            ChatAction.UPLOAD_DOCUMENT,
                            self.client.send_document,
                            user_name=user_name,
                            document=path,
                            filename=name,
                            **cast(Any, payload),
                        )
                        continue
                    elif isinstance(i, Record):
                        path = await i.convert_to_file_path()
                        await self._send_voice_with_fallback(
                            self.client,
                            path,
                            payload,
                            caption=i.text or delta or None,
                            user_name=user_name,
                            message_thread_id=message_thread_id,
                            use_media_action=True,
                        )
                        continue
                    elif isinstance(i, Video):
                        path = await i.convert_to_file_path()
                        await self._send_media_with_action(
                            self.client,
                            ChatAction.UPLOAD_VIDEO,
                            self.client.send_video,
                            user_name=user_name,
                            video=path,
                            **cast(Any, payload),
                        )
                        continue
                    else:
                        logger.warning(f"不支持的消息类型：{type(i)}")
                        continue

                # Plain
                if message_id and len(delta) <= self.MAX_MESSAGE_LENGTH:
                    current_time = asyncio.get_event_loop().time()
                    time_since_last_edit = current_time - last_edit_time

                    # 如果距离上次编辑的时间 >= 设定的间隔，等待一段时间
                    if time_since_last_edit >= throttle_interval:
                        # 发送 typing 状态（带节流）
                        current_time = asyncio.get_event_loop().time()
                        if current_time - last_chat_action_time >= chat_action_interval:
                            await self._ensure_typing(user_name, message_thread_id)
                            last_chat_action_time = current_time
                        # 编辑消息
                        try:
                            await self.client.edit_message_text(
                                text=delta,
                                chat_id=payload["chat_id"],
                                message_id=message_id,
                            )
                            current_content = delta
                        except Exception as e:
                            logger.warning(f"编辑消息失败 (streaming): {e!s}")
                        last_edit_time = (
                            asyncio.get_event_loop().time()
                        )  # 更新上次编辑的时间
                else:
                    # delta 长度一般不会大于 4096，因此这里直接发送
                    # 发送 typing 状态（带节流）
                    current_time = asyncio.get_event_loop().time()
                    if current_time - last_chat_action_time >= chat_action_interval:
                        await self._ensure_typing(user_name, message_thread_id)
                        last_chat_action_time = current_time
                    try:
                        msg = await self.client.send_message(
                            text=delta, **cast(Any, payload)
                        )
                        current_content = delta
                    except Exception as e:
                        logger.warning(f"发送消息失败 (streaming): {e!s}")
                    message_id = msg.message_id
                    last_edit_time = (
                        asyncio.get_event_loop().time()
                    )  # 记录初始消息发送时间

        try:
            if delta and current_content != delta:
                try:
                    markdown_text = telegramify_markdown.markdownify(
                        delta,
                        normalize_whitespace=False,
                    )
                    await self.client.edit_message_text(
                        text=markdown_text,
                        chat_id=payload["chat_id"],
                        message_id=message_id,
                        parse_mode="MarkdownV2",
                    )
                except Exception as e:
                    logger.warning(f"Markdown 转换失败，使用普通文本：{e!s}")
                    await self.client.edit_message_text(
                        text=delta,
                        chat_id=payload["chat_id"],
                        message_id=message_id,
                    )
        except Exception as e:
            logger.warning(f"编辑消息失败 (streaming): {e!s}")

        return await super().send_streaming(generator, use_fallback)
