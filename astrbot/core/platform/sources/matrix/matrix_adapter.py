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
from .components.sync_manager import MatrixSyncManager
from .components.event_processor import MatrixEventProcessor

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
        "matrix_auth_method": "password",  # password, token, oauth2
        "matrix_device_name": "AstrBot",
        "matrix_device_id": "",
        "matrix_store_path": "./data/matrix_store",
        "matrix_auto_join_rooms": True,
        "matrix_sync_timeout": 30000,
        "matrix_bot_name": "AstrBot",  # 机器人的显示名称，用于检测 @
        "matrix_enable_e2ee": True,  # 是否启用端到端加密
        # OAuth2: 所有配置自动从服务器获取，只需设置 matrix_auth_method="oauth2"
        "matrix_refresh_token": "",  # OAuth2 刷新令牌（自动保存）
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

        # Initialize sync manager
        self.sync_manager = MatrixSyncManager(
            client=self.client,
            sync_timeout=self.config.sync_timeout,
            auto_join_rooms=self.config.auto_join_rooms,
        )

        # Initialize event processor
        self.event_processor = MatrixEventProcessor(
            client=self.client,
            user_id=self.config.user_id,
            startup_ts=self._startup_ts,
            e2ee_manager=self.e2ee_manager,
        )

        # Set up callbacks
        self.sync_manager.set_room_event_callback(self.event_processor.process_room_events)
        self.sync_manager.set_to_device_event_callback(self.event_processor.process_to_device_events)
        self.sync_manager.set_invite_callback(self._handle_invite)
        self.event_processor.set_message_callback(self.message_callback)

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
            await self.sync_manager.sync_forever()
        except KeyboardInterrupt:
            logger.info("Matrix adapter received shutdown signal")
            raise
        except Exception as e:
            logger.error(f"Matrix adapter error: {e}")
            logger.error("Matrix 适配器启动失败。请检查配置并查看上方详细错误信息。")
            raise



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
        """
        Process a message event (called by event processor after filtering)

        Args:
            room: Room object
            event: Parsed event object
        """
        try:
            # Convert to AstrBot message format
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

            # Stop sync manager
            if hasattr(self, 'sync_manager'):
                self.sync_manager.stop()

            # Close E2EE manager
            if self.e2ee_manager:
                await self.e2ee_manager.close()

            # Close HTTP client
            if self.client:
                await self.client.close()

            logger.info("Matrix 适配器已被优雅地关闭")
        except Exception as e:
            logger.error(f"Matrix 适配器关闭时出错：{e}")
