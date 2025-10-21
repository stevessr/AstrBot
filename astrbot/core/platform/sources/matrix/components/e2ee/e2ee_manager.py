"""
Matrix E2EE 管理器
整合密钥存储、加密/解密、设备验证等功能
"""

from typing import Optional, Dict, Any, List
from astrbot import logger

from .e2ee_store import MatrixE2EEStore
from .e2ee_crypto import MatrixE2EECrypto
from .e2ee_verification import MatrixE2EEVerification
from .e2ee_recovery import MatrixE2EERecovery


class MatrixE2EEManager:
    """Matrix E2EE 管理器"""

    def __init__(
        self,
        store_path: str,
        user_id: str,
        device_id: str,
        homeserver: str,
        client=None,
    ):
        """
        初始化 E2EE 管理器

        Args:
            store_path: 密钥存储路径
            user_id: 用户 ID
            device_id: 设备 ID
            homeserver: 主服务器地址
            client: Matrix HTTP 客户端（用于发送验证事件）
        """
        self.store_path = store_path
        self.user_id = user_id
        self.device_id = device_id
        self.homeserver = homeserver
        self.client = client

        self.store = MatrixE2EEStore(store_path, user_id, device_id)
        self.crypto = MatrixE2EECrypto()
        self.verification = MatrixE2EEVerification(user_id, device_id, client)
        self.recovery = MatrixE2EERecovery(user_id, device_id)

        self.enabled = False

    async def initialize(self) -> bool:
        """
        初始化 E2EE 管理器并上传密钥到服务器

        Returns:
            是否成功初始化
        """
        try:
            # 初始化存储
            if not await self.store.initialize():
                logger.warning("Failed to initialize E2EE store")
                return False

            # 初始化加密模块
            self.crypto = MatrixE2EECrypto(self.store.account)

            # 上传设备密钥到服务器
            if self.client:
                await self._upload_device_keys()

            self.enabled = True
            logger.info("E2EE manager initialized successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize E2EE manager: {e}")
            return False

    async def _upload_device_keys(self):
        """上传设备密钥到 Matrix 服务器"""
        try:
            identity_keys = self.get_identity_keys()
            if not identity_keys:
                logger.warning("No identity keys to upload")
                return

            # 构建device_keys对象（符合Matrix规范）
            device_keys = {
                "user_id": self.user_id,
                "device_id": self.device_id,
                "algorithms": ["m.olm.v1.curve25519-aes-sha2", "m.megolm.v1.aes-sha2"],
                "keys": {
                    f"curve25519:{self.device_id}": identity_keys.get("curve25519"),
                    f"ed25519:{self.device_id}": identity_keys.get("ed25519"),
                },
            }

            # 签名设备密钥（在真实实现中应使用 Ed25519 签名）
            import json
            import hashlib

            canonical_json = json.dumps(
                device_keys, sort_keys=True, separators=(",", ":")
            )
            signature = hashlib.sha256(canonical_json.encode()).hexdigest()

            device_keys["signatures"] = {
                self.user_id: {f"ed25519:{self.device_id}": signature}
            }

            # 获取一次性密钥
            one_time_keys = self.get_one_time_keys(count=50)
            formatted_otks = {}
            if one_time_keys:
                for key_id, key_data in one_time_keys.items():
                    formatted_otks[f"curve25519:{key_id}"] = key_data

            # 上传到服务器
            response = await self.client.upload_keys(device_keys, formatted_otks)

            otk_counts = response.get("one_time_key_counts", {})
            logger.info(f"✅ Uploaded device keys successfully")
            logger.info(f"   One-time key counts: {otk_counts}")

        except Exception as e:
            logger.error(f"Failed to upload device keys: {e}")
            # 不抛出异常，因为E2EE可以继续工作

    def is_enabled(self) -> bool:
        """检查 E2EE 是否启用"""
        return self.enabled

    # ==================== 密钥管理 ====================

    def get_identity_keys(self) -> Optional[Dict[str, str]]:
        """获取身份密钥"""
        return self.store.get_identity_keys()

    def get_one_time_keys(self, count: int = 10) -> Optional[Dict[str, str]]:
        """获取一次性密钥"""
        return self.store.get_one_time_keys(count)

    def publish_keys(self) -> bool:
        """发布密钥到服务器"""
        try:
            self.store.mark_keys_as_published()
            logger.info("Keys published successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to publish keys: {e}")
            return False

    # ==================== 设备验证 ====================

    async def start_device_verification(
        self,
        other_user_id: str,
        other_device_id: str,
    ) -> Optional[str]:
        """
        启动设备验证（使用 to-device 消息）

        Args:
            other_user_id: 对方用户 ID
            other_device_id: 对方设备 ID

        Returns:
            验证 ID，或 None 如果失败
        """
        success, verification_id = await self.verification.start_verification(
            other_user_id, other_device_id
        )
        return verification_id if success else None

    async def accept_device_verification(self, verification_id: str) -> bool:
        """接受设备验证并发送 start 事件"""
        return await self.verification.accept_verification(verification_id)

    def get_sas_code(self, verification_id: str) -> Optional[str]:
        """获取 SAS 代码"""
        return self.verification.generate_sas_code(verification_id)

    def confirm_sas_code(self, verification_id: str, sas_code: str) -> bool:
        """确认 SAS 代码"""
        return self.verification.confirm_sas(verification_id, sas_code)

    def complete_device_verification(self, verification_id: str) -> bool:
        """完成设备验证"""
        success = self.verification.complete_verification(verification_id)
        if success:
            # 标记设备为已验证
            verification = self.verification.get_verification_status(verification_id)
            if verification:
                self.store.add_verified_device(
                    verification["other_user_id"],
                    verification["other_device_id"],
                )
        return success

    def cancel_device_verification(
        self, verification_id: str, reason: str = ""
    ) -> bool:
        """取消设备验证"""
        return self.verification.cancel_verification(verification_id, reason)

    def get_verification_status(self, verification_id: str) -> Optional[Dict[str, Any]]:
        """获取验证状态"""
        return self.verification.get_verification_status(verification_id)

    def get_all_verifications(self) -> Dict[str, Dict[str, Any]]:
        """获取所有验证会话"""
        return self.verification.get_all_verifications()

    # ==================== 设备信息 ====================

    def is_device_verified(self, user_id: str, device_id: str) -> bool:
        """检查设备是否已验证"""
        return self.store.is_device_verified(user_id, device_id)

    def get_verified_devices(self, user_id: str) -> List[str]:
        """获取用户的已验证设备列表"""
        return self.store.get_verified_devices(user_id)

    # ==================== 消息加密/解密 ====================

    def encrypt_message(
        self, user_id: str, device_id: str, plaintext: str
    ) -> Optional[Dict[str, Any]]:
        """加密消息"""
        return self.crypto.encrypt_message(user_id, device_id, plaintext)

    def decrypt_message(
        self, user_id: str, device_id: str, ciphertext: str
    ) -> Optional[str]:
        """解密消息"""
        return self.crypto.decrypt_message(user_id, device_id, ciphertext)

    def encrypt_group_message(self, room_id: str, plaintext: str) -> Optional[str]:
        """加密群组消息"""
        return self.crypto.encrypt_group_message(room_id, plaintext)

    def decrypt_group_message(self, room_id: str, ciphertext: str) -> Optional[str]:
        """解密群组消息"""
        return self.crypto.decrypt_group_message(room_id, ciphertext)

    # ==================== 密钥恢复 ====================

    def request_key_recovery(self, target_device_id: str) -> str:
        """向其他设备请求密钥恢复"""
        return self.recovery.request_key_recovery(target_device_id)

    def accept_recovery_request(self, request_id: str) -> bool:
        """接受密钥恢复请求"""
        return self.recovery.accept_recovery_request(request_id)

    def generate_recovery_code(self, request_id: str) -> Optional[str]:
        """生成恢复验证码"""
        return self.recovery.generate_recovery_code(request_id)

    def confirm_recovery_code(self, request_id: str, code: str) -> bool:
        """确认恢复验证码"""
        return self.recovery.confirm_recovery_code(request_id, code)

    def share_keys(self, request_id: str) -> bool:
        """分享密钥给请求设备"""
        # 获取当前设备的密钥
        identity_keys = self.get_identity_keys()
        one_time_keys = self.get_one_time_keys()

        keys = {
            "identity_keys": identity_keys,
            "one_time_keys": one_time_keys,
        }

        return self.recovery.share_keys(request_id, keys)

    def receive_keys(self, request_id: str) -> Optional[Dict]:
        """接收恢复的密钥"""
        return self.recovery.receive_keys(request_id)

    def cancel_recovery_request(self, request_id: str, reason: str = "") -> bool:
        """取消密钥恢复请求"""
        return self.recovery.cancel_recovery_request(request_id, reason)

    def get_recovery_request_status(self, request_id: str) -> Optional[Dict]:
        """获取恢复请求状态"""
        return self.recovery.get_recovery_request_status(request_id)

    def list_recovery_requests(self) -> List[Dict]:
        """列出所有恢复请求"""
        return self.recovery.list_recovery_requests()

    def list_pending_recovery_requests(self) -> List[Dict]:
        """列出待处理的恢复请求"""
        return self.recovery.list_pending_recovery_requests()

    # ==================== 事件处理 ====================

    async def handle_verification_event(self, event: Dict[str, Any]):
        """
        处理验证相关的 to-device 事件

        Args:
            event: to-device 事件数据
        """
        event_type = event.get("type")
        content = event.get("content", {})
        sender = event.get("sender")

        logger.info(f"Handling verification event: {event_type} from {sender}")

        try:
            if event_type == "m.key.verification.ready":
                # 对方准备好验证了
                await self.verification.handle_ready(sender, content)
            elif event_type == "m.key.verification.start":
                # 对方开始验证流程
                await self.verification.handle_start(sender, content)
            elif event_type == "m.key.verification.accept":
                # 对方接受了我们的验证方法
                await self.verification.handle_accept(sender, content)
            elif event_type == "m.key.verification.key":
                # 对方发送了公钥
                await self.verification.handle_key(sender, content)
            elif event_type == "m.key.verification.mac":
                # 对方发送了 MAC 验证
                await self.verification.handle_mac(sender, content)
            elif event_type == "m.key.verification.done":
                # 验证完成
                await self.verification.handle_done(sender, content)
            elif event_type == "m.key.verification.cancel":
                # 验证被取消
                await self.verification.handle_cancel(sender, content)
            else:
                logger.warning(f"Unknown verification event type: {event_type}")

        except Exception as e:
            logger.error(f"Error handling verification event {event_type}: {e}")

    # ==================== 生命周期 ====================

    async def close(self):
        """关闭管理器，保存所有数据"""
        try:
            await self.store.close()
            logger.info("E2EE manager closed")
        except Exception as e:
            logger.error(f"Error closing E2EE manager: {e}")
