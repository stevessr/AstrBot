import asyncio
import time
from astrbot.api import logger
from astrbot.api.event import MessageChain
from astrbot.api.platform import Platform, PlatformMetadata, register_platform_adapter
from astrbot.core.platform.astr_message_event import MessageSesion
from .matrix_event import MatrixPlatformEvent

# 组件导入
from .components.config import MatrixConfig
from .components.auth import MatrixAuth
from .components.sender import MatrixSender
from .components.receiver import MatrixReceiver
from .components.event_handler import MatrixEventHandler
from .components.utils import MatrixUtils

# 自定义 Matrix 客户端（不依赖 matrix-nio）
from .client import MatrixHTTPClient


@register_platform_adapter(
    "matrix",
    "Matrix 协议适配器",
    default_config_tmpl={
        "matrix_homeserver": "https://matrix.org",
        "matrix_user_id": "",
        "matrix_password": "",
        "matrix_access_token": "",
        "matrix_auth_method": "password",  # password, token
        "matrix_device_name": "AstrBot",
        "matrix_device_id": "",
        "matrix_store_path": "./data/matrix_store",
        "matrix_auto_join_rooms": True,
        "matrix_sync_timeout": 30000,
        "matrix_bot_name": "AstrBot",  # 机器人的显示名称，用于检测 @
        "matrix_enable_e2ee": True,  # 是否启用端到端加密
    },
    adapter_display_name="Matrix",
)
class MatrixPlatformAdapter(Platform):
    def __init__(
        self, platform_config: dict, platform_settings: dict, event_queue: asyncio.Queue
    ) -> None:
        super().__init__(event_queue)
        self.config = MatrixConfig(platform_config)
        # 记录启动时间（毫秒）。用于过滤启动前的历史消息，避免启动时回复历史消息
        self._startup_ts = int(time.time() * 1000)

        # 使用自定义 HTTP 客户端（不依赖 matrix-nio）
        self.client = MatrixHTTPClient(homeserver=self.config.homeserver)
        self.auth = MatrixAuth(self.client, self.config)

        # E2EE support
        self.e2ee_manager = None
        if self.config.enable_e2ee:
            from .components.e2ee import MatrixE2EEManager

            self.e2ee_manager = MatrixE2EEManager(
                store_path=self.config.store_path,
                user_id=self.config.user_id,
                device_id=self.config.device_id,
                homeserver=self.config.homeserver,
                client=self.client,  # 传递客户端用于发送验证事件
            )

        self.sender = MatrixSender(self.client)

        # 获取机器人名称用于检测 @
        bot_name = platform_config.get("matrix_bot_name", self.config.device_name)
        self.receiver = MatrixReceiver(
            self.config.user_id,
            lambda mxc: MatrixUtils.mxc_to_http(mxc, self.config.homeserver),
            bot_name=bot_name,
            client=self.client,  # 传递 client 用于下载图片
        )
        self.event_handler = MatrixEventHandler(
            self.client, self.config.auto_join_rooms
        )

        self.sync_timeout = self.config.sync_timeout

        # 消息去重：记录已处理的消息 ID，防止重复处理
        self._processed_messages = set()
        self._max_processed_messages = 1000  # 最多缓存 1000 条消息 ID

        # 事件回调存储（替代 nio 的 add_event_callback）
        self._event_callbacks = {
            "m.room.message": [],
            "m.room.member": [],
        }
        logger.info("Matrix Adapter 初始化完成")

    async def send_by_session(
        self, session: MessageSesion, message_chain: MessageChain, reply_to: str = None
    ):
        try:
            room_id = session.session_id
            if reply_to is None:
                try:
                    from astrbot.api.message_components import Reply as _Reply

                    for seg in message_chain.chain:
                        if isinstance(seg, _Reply) and getattr(seg, "id", None):
                            reply_to = str(seg.id)
                            break
                except Exception:
                    pass

            # 检查是否有 Markdown 内容，渲染为 HTML
            from astrbot.core.platform.sources.matrix.components.markdown_utils import (
                markdown_to_html,
            )
            from astrbot.api.message_components import Plain

            new_chain = []
            for seg in message_chain.chain:
                if isinstance(seg, Plain):
                    # Simple check for Markdown
                    text = seg.text
                    if any(
                        x in text for x in ["**", "*", "`", "#", "- ", "> ", "[", "]("]
                    ):
                        html = markdown_to_html(text)
                        # 构建符合 Matrix 格式的回复内容（带引用和 HTML 渲染）
                        if reply_to:
                            # 获取被回复消息的内容用于构建引用块
                            try:
                                resp = await self.client.get_event(room_id, reply_to)
                                if resp and "content" in resp:
                                    replied_body = resp["content"].get("body", "")
                                    # 构建引用格式
                                    quoted_lines = [
                                        "> " + line
                                        for line in replied_body.splitlines()
                                    ]
                                    quoted_text = "\n".join(quoted_lines) + "\n\n"
                                    full_text = quoted_text + text
                                    # 修复：引用块应该包含原始消息的 HTML，而不是当前消息的 HTML
                                    quoted_html = "".join(
                                        f"<p>{line}</p>"
                                        for line in replied_body.splitlines()
                                    )
                                    full_html = f"<mx-reply><blockquote>{quoted_html}</blockquote></mx-reply>{html}"
                                else:
                                    full_text = text
                                    full_html = html
                            except Exception:
                                full_text = text
                                full_html = html
                        else:
                            full_text = text
                            full_html = html

                        # 创建包含 format 和 formatted_body 的 Plain 对象
                        new_chain.append(
                            Plain(
                                text=full_text,
                                format="org.matrix.custom.html",
                                formatted_body=full_html,
                                convert=True,
                            )
                        )
                    else:
                        new_chain.append(seg)
                else:
                    new_chain.append(seg)
            new_message_chain = MessageChain(new_chain)

            # 发送消息
            await MatrixPlatformEvent.send_with_client(
                self.client, new_message_chain, room_id, reply_to=reply_to
            )
            await super().send_by_session(session, new_message_chain)
        except Exception as e:
            logger.error(f"Failed to send message via session: {e}")

    def meta(self) -> PlatformMetadata:
        id_ = getattr(self.config, "id", None) or "matrix"
        return PlatformMetadata(name="matrix", description="Matrix 协议适配器", id=id_)

    async def run(self):
        try:
            await self.auth.login()

            # Initialize E2EE if enabled
            if self.e2ee_manager:
                success = await self.e2ee_manager.initialize()
                if success:
                    logger.info("E2EE enabled and initialized successfully")
                else:
                    logger.warning("E2EE initialization failed, running without E2EE")
                    self.e2ee_manager = None

            logger.info(
                f"Matrix Platform Adapter is running for {self.config.user_id} on {self.config.homeserver}"
            )
            await self._sync_forever()
        except KeyboardInterrupt:
            logger.info("Matrix adapter received shutdown signal")
            raise
        except Exception as e:
            logger.error(f"Matrix adapter error: {e}")
            logger.error("Matrix 适配器启动失败。请检查配置并查看上方详细错误信息。")
            raise

    async def _sync_forever(self):
        """自定义 sync 循环（替代 nio 的 sync_forever）"""
        next_batch = None
        first_sync = True

        while True:
            try:
                # 执行 sync
                sync_response = await self.client.sync(
                    since=next_batch,
                    timeout=self.sync_timeout,
                    full_state=first_sync,
                )

                next_batch = sync_response.get("next_batch")
                first_sync = False

                # 处理 to-device 消息（E2EE 验证等）
                to_device_events = sync_response.get("to_device", {}).get("events", [])
                if to_device_events and self.e2ee_manager:
                    await self._process_to_device_events(to_device_events)

                # 处理 rooms 事件
                rooms = sync_response.get("rooms", {})

                # 处理 joined rooms
                for room_id, room_data in rooms.get("join", {}).items():
                    await self._process_room_events(room_id, room_data)

                # 处理 invited rooms
                if self.config.auto_join_rooms:
                    for room_id, invite_data in rooms.get("invite", {}).items():
                        await self._handle_invite(room_id, invite_data)

            except KeyboardInterrupt:
                raise
            except Exception as e:
                logger.error(f"Error in sync loop: {e}")
                # Wait a bit before retrying
                await asyncio.sleep(5)

    async def _process_to_device_events(self, events: list):
        """处理 to-device 事件（E2EE 验证等）"""
        for event in events:
            event_type = event.get("type")
            content = event.get("content", {})
            sender = event.get("sender")

            # 记录所有 to-device 事件（用于调试）
            logger.info(f"📨 Received to-device event: {event_type} from {sender}")
            logger.debug(f"Event content: {content}")

            # 处理 E2EE 验证相关事件
            if event_type in [
                "m.key.verification.ready",
                "m.key.verification.start",
                "m.key.verification.accept",
                "m.key.verification.key",
                "m.key.verification.mac",
                "m.key.verification.done",
                "m.key.verification.cancel",
            ]:
                if self.e2ee_manager:
                    await self.e2ee_manager.handle_verification_event(event)
                else:
                    logger.warning(f"Received {event_type} but E2EE is not enabled")
            elif event_type == "m.room_key":
                # 处理房间密钥分享
                if self.e2ee_manager:
                    await self.e2ee_manager.handle_room_key(sender, content)
                else:
                    logger.warning("Received m.room_key but E2EE is not enabled")
            elif event_type == "m.forwarded_room_key":
                # 处理从其他设备转发过来的房间密钥
                if self.e2ee_manager:
                    await self.e2ee_manager.handle_room_key(sender, content)
                else:
                    logger.warning("Received m.forwarded_room_key but E2EE is not enabled")
            elif event_type == "m.room.encrypted":
                # 处理加密消息（可能包含验证事件）
                if self.e2ee_manager:
                    logger.info(
                        f"Received encrypted to-device message from {sender}, attempting to decrypt..."
                    )
                    # TODO: 实现 Olm 解密 to-device 消息
                    logger.debug(f"Encrypted content: {content}")
                else:
                    logger.warning(
                        "Received encrypted message but E2EE manager not available"
                    )
            else:
                # 记录未处理的事件类型
                logger.warning(f"⚠️ Unhandled to-device event type: {event_type}")

    async def _process_room_events(self, room_id: str, room_data: dict):
        """处理房间事件"""
        timeline = room_data.get("timeline", {})
        events = timeline.get("events", [])

        # 构建简化的 room 对象
        from .client.event_types import MatrixRoom

        room = MatrixRoom(room_id=room_id)

        # 处理 state 事件以获取房间信息
        state_events = room_data.get("state", {}).get("events", [])
        for event in state_events:
            if event.get("type") == "m.room.member":
                user_id = event.get("state_key")
                content = event.get("content", {})
                if content.get("membership") == "join":
                    display_name = content.get("displayname", user_id)
                    room.members[user_id] = display_name
                    room.member_count += 1

        # 处理 timeline 事件
        for event_data in events:
            await self._handle_event(room, event_data)

    async def _handle_event(self, room, event_data: dict):
        """处理单个事件"""
        from .client.event_types import parse_event

        event_type = event_data.get("type")

        if event_type == "m.room.message":
            # 解析明文消息事件
            event = parse_event(event_data, room.room_id)
            await self.message_callback(room, event)
        elif event_type == "m.room.encrypted":
            # 处理加密消息
            if self.e2ee_manager and self.e2ee_manager.is_enabled():
                logger.debug(f"Received encrypted message in room {room.room_id}")
                # 尝试解密消息
                decrypted_event = await self._decrypt_room_event(event_data, room)
                if decrypted_event:
                    # 解密成功，处理明文消息
                    event = parse_event(decrypted_event, room.room_id)
                    await self.message_callback(room, event)
                else:
                    logger.warning(
                        f"Failed to decrypt message in room {room.room_id}, sender: {event_data.get('sender')}"
                    )
            else:
                logger.warning(
                    f"Received encrypted message but E2EE is not enabled in room {room.room_id}"
                )

    async def _decrypt_room_event(self, event_data: dict, room) -> dict | None:
        """解密房间加密事件"""
        try:
            content = event_data.get("content", {})
            sender = event_data.get("sender")

            # 提取加密信息
            algorithm = content.get("algorithm")
            sender_key = content.get("sender_key")
            ciphertext = content.get("ciphertext")
            session_id = content.get("session_id")
            device_id = content.get("device_id")

            logger.debug(
                f"Decrypting: algorithm={algorithm}, sender={sender}, device={device_id}"
            )

            # 调用 E2EE manager 解密
            if algorithm == "m.megolm.v1.aes-sha2":
                # Megolm 群组加密（加密房间使用）
                plaintext = await self.e2ee_manager.decrypt_megolm_event(
                    room.room_id, sender, sender_key, session_id, ciphertext
                )
            elif algorithm == "m.olm.v1.curve25519-aes-sha2":
                # Olm 1 对 1 加密
                plaintext = await self.e2ee_manager.decrypt_olm_event(
                    sender, device_id, ciphertext
                )
            else:
                logger.warning(f"Unsupported encryption algorithm: {algorithm}")
                return None

            if plaintext:
                # 构建解密后的事件
                import json

                decrypted_content = json.loads(plaintext)
                decrypted_event = event_data.copy()
                decrypted_event["type"] = decrypted_content.get(
                    "type", "m.room.message"
                )
                decrypted_event["content"] = decrypted_content.get("content", {})
                return decrypted_event

            return None

        except Exception as e:
            logger.error(f"Error decrypting room event: {e}")
            return None

    async def _handle_invite(self, room_id: str, invite_data: dict):
        """处理房间邀请"""
        try:
            logger.info(f"Received invite to room {room_id}")
            result = await self.client.join_room(room_id)
            if result.get("room_id"):
                logger.info(f"Successfully joined room {room_id}")
            else:
                logger.error(f"Failed to join room {room_id}: {result}")
        except Exception as e:
            logger.error(f"Error joining room {room_id}: {e}")

    async def _save_config(self):
        """Save configuration changes back to the platform config"""
        try:
            # Import here to avoid circular dependency
            from astrbot.core.config.astrbot_config import AstrBotConfig

            # Load the main config
            main_config = AstrBotConfig()

            # Find and update our platform config
            for platform in main_config.get("platform", []):
                if platform.get("id") == self.config.get("id"):
                    platform["matrix_device_id"] = self.device_id
                    if self.access_token and not platform.get("matrix_access_token"):
                        platform["matrix_access_token"] = self.access_token
                        logger.info("Saved access_token to config for future use")
                    break

                    # Save the updated config
            main_config.save_config()
            logger.debug("Matrix adapter config saved successfully")
        except Exception as e:
            logger.warning(f"Failed to save Matrix config: {e}")

    async def message_callback(self, room, event):
        try:
            # 忽略自己发送的消息
            if event.sender == self.config.user_id:
                logger.debug(f"Ignoring message from self: {event.event_id}")
                return

            # 历史消息过滤：忽略启动前的事件，避免启动时回复历史消息
            evt_ts = getattr(event, "origin_server_ts", None)
            if evt_ts is None:
                evt_ts = getattr(event, "server_timestamp", None)
            if evt_ts is not None and evt_ts < (
                self._startup_ts - 1000
            ):  # 允许 1s 的时间漂移
                logger.debug(
                    f"Ignoring historical message before startup: id={getattr(event, 'event_id', '<unknown>')} ts={evt_ts} startup={self._startup_ts}"
                )
                return

            # 消息去重：检查是否已处理过该消息
            if event.event_id in self._processed_messages:
                logger.debug(f"Ignoring duplicate message: {event.event_id}")
                return

            # 记录已处理的消息 ID
            self._processed_messages.add(event.event_id)

            # 限制缓存大小，防止内存泄漏
            if len(self._processed_messages) > self._max_processed_messages:
                # 移除最旧的一半消息 ID（简单的 FIFO 策略）
                old_messages = list(self._processed_messages)[
                    : self._max_processed_messages // 2
                ]
                for msg_id in old_messages:
                    self._processed_messages.discard(msg_id)

            abm = await self.receiver.convert_message(room, event)
            if abm is None:
                logger.warning(f"Failed to convert message: {event}")
                return
            await self.handle_msg(abm)
        except Exception as e:
            logger.error(f"Error in message callback: {e}")

    # 消息转换已由 receiver 组件处理

    # mxc_to_http 已由 utils 组件处理

    async def handle_msg(self, message):
        try:
            message_event = MatrixPlatformEvent(
                message_str=message.message_str,
                message_obj=message,
                platform_meta=self.meta(),
                session_id=message.session_id,
                client=self.client,
            )
            self.commit_event(message_event)
            logger.debug(
                f"Message event committed: session={message.session_id}, type={message.type}, sender={message.sender.user_id}"
            )
        except Exception as e:
            logger.error(f"Failed to handle message: {e}")

    def get_client(self):
        return self.client

    async def terminate(self):
        try:
            logger.info("Shutting down Matrix adapter...")
            # E2EE support removed: nothing to close
            if self.client:
                await self.client.close()
            logger.info("Matrix 适配器已被优雅地关闭")
        except Exception as e:
            logger.error(f"Matrix 适配器关闭时出错：{e}")
