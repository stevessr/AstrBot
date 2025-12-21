"""
E2EE Manager - 端到端加密管理器

整合 OlmMachine 和 HTTP 客户端，提供高层 E2EE 操作接口。
"""

from pathlib import Path
from typing import Any

from astrbot.api import logger

from .crypto_store import CryptoStore
from .olm_machine import OlmMachine, VODOZEMAC_AVAILABLE


class E2EEManager:
    """
    端到端加密管理器

    负责:
    - 初始化加密组件
    - 设备密钥上传
    - 消息加密/解密
    - 密钥交换
    """

    def __init__(
        self,
        client,
        user_id: str,
        device_id: str,
        store_path: str | Path,
    ):
        """
        初始化 E2EE 管理器

        Args:
            client: MatrixHTTPClient 实例
            user_id: 用户 ID
            device_id: 设备 ID
            store_path: 加密存储路径
        """
        self.client = client
        self.user_id = user_id
        self.device_id = device_id
        self.store_path = Path(store_path) / user_id.replace(":", "_")

        self._store: CryptoStore | None = None
        self._olm: OlmMachine | None = None
        self._initialized = False

    @property
    def is_available(self) -> bool:
        """检查 E2EE 是否可用"""
        return VODOZEMAC_AVAILABLE

    async def initialize(self):
        """初始化 E2EE 组件"""
        if not VODOZEMAC_AVAILABLE:
            logger.warning("vodozemac 未安装，E2EE 功能不可用")
            return False

        try:
            # 创建存储和加密机器
            self._store = CryptoStore(self.store_path, self.user_id, self.device_id)
            self._olm = OlmMachine(self._store, self.user_id, self.device_id)

            # 上传设备密钥
            await self._upload_device_keys()

            self._initialized = True
            logger.info(f"E2EE 初始化成功 (device_id: {self.device_id})")
            return True

        except Exception as e:
            logger.error(f"E2EE 初始化失败: {e}")
            return False

    async def _upload_device_keys(self):
        """上传设备密钥到服务器"""
        if not self._olm:
            return

        try:
            # 获取设备密钥
            device_keys = self._olm.get_device_keys()

            # 生成一次性密钥
            one_time_keys = self._olm.generate_one_time_keys(50)

            # 上传到服务器
            response = await self.client.upload_keys(
                device_keys=device_keys,
                one_time_keys=one_time_keys,
            )

            # 标记密钥为已发布
            self._olm.mark_keys_as_published()

            counts = response.get("one_time_key_counts", {})
            logger.info(f"设备密钥已上传，一次性密钥数量: {counts}")

        except Exception as e:
            logger.error(f"上传设备密钥失败: {e}")

    async def decrypt_event(
        self, event_content: dict, sender: str, room_id: str
    ) -> dict | None:
        """
        解密加密事件

        Args:
            event_content: m.room.encrypted 事件的 content
            sender: 发送者 ID
            room_id: 房间 ID

        Returns:
            解密后的事件内容，或 None
        """
        if not self._olm or not self._initialized:
            logger.warning("E2EE 未初始化，无法解密")
            return None

        algorithm = event_content.get("algorithm")

        if algorithm == "m.megolm.v1.aes-sha2":
            session_id = event_content.get("session_id")
            ciphertext = event_content.get("ciphertext")

            if not session_id or not ciphertext:
                logger.warning("缺少 session_id 或 ciphertext")
                return None

            decrypted = self._olm.decrypt_megolm(session_id, ciphertext)
            if decrypted:
                logger.debug(f"成功解密 Megolm 消息 (session: {session_id[:8]}...)")
            return decrypted

        elif algorithm == "m.olm.v1.curve25519-aes-sha2-256":
            # Olm 消息解密
            sender_key = event_content.get("sender_key")
            ciphertext_data = event_content.get("ciphertext", {})

            # 找到发给本设备的密文
            my_key = self._olm.curve25519_key
            if my_key not in ciphertext_data:
                logger.warning("消息不是发给本设备的")
                return None

            my_ciphertext = ciphertext_data[my_key]
            message_type = my_ciphertext.get("type")
            body = my_ciphertext.get("body")

            try:
                plaintext = self._olm.decrypt_olm_message(sender_key, message_type, body)
                import json

                return json.loads(plaintext)
            except Exception as e:
                logger.error(f"Olm 解密失败: {e}")
                return None

        else:
            logger.warning(f"不支持的加密算法: {algorithm}")
            return None

    async def handle_room_key(self, event: dict, sender_key: str):
        """
        处理 m.room_key 事件 (接收 Megolm 会话密钥)

        Args:
            event: 解密后的 m.room_key 事件内容
            sender_key: 发送者的 curve25519 密钥
        """
        if not self._olm or not self._initialized:
            return

        room_id = event.get("room_id")
        session_id = event.get("session_id")
        session_key = event.get("session_key")
        algorithm = event.get("algorithm")

        if algorithm != "m.megolm.v1.aes-sha2":
            logger.warning(f"不支持的密钥算法: {algorithm}")
            return

        if not all([room_id, session_id, session_key]):
            logger.warning("m.room_key 事件缺少必要字段")
            return

        self._olm.add_megolm_inbound_session(
            room_id, session_id, session_key, sender_key
        )
        logger.info(f"收到房间 {room_id} 的 Megolm 密钥")

    async def encrypt_message(
        self, room_id: str, event_type: str, content: dict
    ) -> dict | None:
        """
        加密消息

        Args:
            room_id: 房间 ID
            event_type: 事件类型
            content: 事件内容

        Returns:
            加密后的 m.room.encrypted 内容，或 None
        """
        if not self._olm or not self._initialized:
            logger.warning("E2EE 未初始化，无法加密")
            return None

        try:
            # 检查是否有出站会话
            if not self._store or not self._store.get_megolm_outbound(room_id):
                # 创建新会话并分发密钥
                await self._create_and_share_session(room_id)

            # 加密消息
            return self._olm.encrypt_megolm(room_id, event_type, content)

        except Exception as e:
            logger.error(f"加密消息失败: {e}")
            return None

    async def _create_and_share_session(self, room_id: str):
        """创建 Megolm 出站会话并分发密钥"""
        if not self._olm:
            return

        # 创建会话
        session_id, session_key = self._olm.create_megolm_outbound_session(room_id)
        logger.info(f"为房间 {room_id} 创建了 Megolm 会话")

        # TODO: 分发密钥给房间内所有设备
        # 这需要:
        # 1. 获取房间成员列表
        # 2. 查询每个成员的设备密钥
        # 3. 声明一次性密钥
        # 4. 创建 Olm 会话
        # 5. 发送 m.room_key 到每个设备

    async def ensure_room_keys_sent(self, room_id: str, members: list[str]):
        """
        确保房间密钥已发送给所有成员

        Args:
            room_id: 房间 ID
            members: 成员用户 ID 列表
        """
        # TODO: 实现密钥分发
        pass
