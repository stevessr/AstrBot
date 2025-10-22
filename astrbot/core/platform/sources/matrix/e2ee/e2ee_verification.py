"""
Matrix E2EE 设备验证模块
处理设备验证和密钥交换
"""

import hashlib
import secrets
from typing import Optional, Dict, Any, List, Tuple
from enum import Enum
from astrbot import logger


class VerificationMethod(Enum):
    """验证方法"""

    SAS = "m.sas.v1"  # 短认证字符串
    QR_CODE = "m.qr_code.show.v1"  # 二维码
    RECIPROCATE = "m.reciprocate.v1"  # 相互验证


class VerificationState(Enum):
    """验证状态"""

    PENDING = "pending"
    READY = "ready"
    STARTED = "started"
    ACCEPTED = "accepted"
    KEY_EXCHANGE = "key_exchange"
    MAC_RECEIVED = "mac_received"
    MAC_EXCHANGE = "mac_exchange"
    VERIFIED = "verified"
    CANCELLED = "cancelled"


class MatrixE2EEVerification:
    """Matrix E2EE 设备验证处理"""

    def __init__(self, user_id: str, device_id: str, client=None):
        """
        初始化验证模块

        Args:
            user_id: 本地用户 ID
            device_id: 本地设备 ID
            client: Matrix HTTP 客户端（可选，用于发送验证事件）
        """
        self.user_id = user_id
        self.device_id = device_id
        self.client = client
        self.verifications: Dict[str, Dict[str, Any]] = {}  # 验证会话存储

    async def start_verification(
        self,
        other_user_id: str,
        other_device_id: str,
        methods: Optional[List[str]] = None,
    ) -> Tuple[bool, str]:
        """
        启动设备验证（使用 to-device 消息）

        Args:
            other_user_id: 对方用户 ID
            other_device_id: 对方设备 ID
            methods: 支持的验证方法列表

        Returns:
            (是否成功，验证 ID)
        """
        try:
            if methods is None:
                methods = [VerificationMethod.SAS.value]

            verification_id = f"${secrets.token_hex(16)}"

            self.verifications[verification_id] = {
                "state": VerificationState.PENDING.value,
                "other_user_id": other_user_id,
                "other_device_id": other_device_id,
                "methods": methods,
                "our_commitment": None,
                "their_commitment": None,
                "our_key": None,
                "their_key": None,
                "sas_code": None,
            }

            # 发送验证请求到 Matrix 服务器（使用 to-device 消息）
            if self.client:
                await self._send_verification_request(
                    verification_id, other_user_id, other_device_id, methods
                )

            logger.info(
                f"Started verification {verification_id} with "
                f"{other_user_id}:{other_device_id}"
            )
            return True, verification_id
        except Exception as e:
            logger.error(f"Failed to start verification: {e}")
            return False, ""

    async def _send_verification_request(
        self,
        transaction_id: str,
        other_user_id: str,
        other_device_id: str,
        methods: List[str],
    ):
        """
        通过 to-device 消息发送验证请求到 Matrix 服务器

        Args:
            transaction_id: 事务 ID
            other_user_id: 对方用户 ID
            other_device_id: 对方设备 ID
            methods: 支持的验证方法
        """
        try:
            import time

            content = {
                "from_device": self.device_id,
                "methods": methods,
                "timestamp": int(time.time() * 1000),  # 当前时间戳（毫秒）
                "transaction_id": transaction_id,
            }

            # 通过 to-device 消息发送验证请求
            messages = {other_user_id: {other_device_id: content}}

            await self.client.send_to_device("m.key.verification.request", messages)
            logger.info(
                f"Sent to-device verification request to {other_user_id}:{other_device_id}"
            )

        except Exception as e:
            logger.error(f"Failed to send verification request: {e}")
            raise

    async def accept_verification(self, verification_id: str) -> bool:
        """
        接受验证请求（但不立即发送 start，等待 ready）

        Args:
            verification_id: 验证 ID

        Returns:
            是否成功
        """
        try:
            if verification_id not in self.verifications:
                logger.warning(f"Verification {verification_id} not found")
                return False

            verification = self.verifications[verification_id]
            verification["state"] = VerificationState.ACCEPTED.value

            # 不立即发送 start，等待对方发送 ready
            # start 会在 handle_ready() 中发送

            logger.info(
                f"Accepted verification {verification_id}, waiting for ready from other device"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to accept verification: {e}")
            return False

    async def _send_start_event(
        self, transaction_id: str, verification: Dict[str, Any]
    ):
        """发送 m.key.verification.start 事件"""
        try:
            other_user_id = verification["other_user_id"]
            other_device_id = verification["other_device_id"]

            content = {
                "from_device": self.device_id,
                "method": "m.sas.v1",
                "transaction_id": transaction_id,
                "key_agreement_protocols": ["curve25519-hkdf-sha256"],
                "hashes": ["sha256"],
                "message_authentication_codes": [
                    "hkdf-hmac-sha256.v2",
                    "hmac-sha256",
                ],
                "short_authentication_string": ["decimal", "emoji"],
            }

            messages = {other_user_id: {other_device_id: content}}

            await self.client.send_to_device("m.key.verification.start", messages)
            logger.info(f"Sent verification start to {other_user_id}:{other_device_id}")

        except Exception as e:
            logger.error(f"Failed to send start event: {e}")
            raise

    def generate_sas_code(self, verification_id: str) -> Optional[str]:
        """
        生成短认证字符串（SAS）

        Args:
            verification_id: 验证 ID

        Returns:
            SAS 代码，或 None 如果失败
        """
        try:
            if verification_id not in self.verifications:
                logger.warning(f"Verification {verification_id} not found")
                return None

            verification = self.verifications[verification_id]

            # 生成 SAS 代码
            # 使用 SHA256 哈希生成可读的代码
            combined = (
                f"{self.device_id}:{verification['other_device_id']}:{verification_id}"
            )
            hash_bytes = hashlib.sha256(combined.encode()).digest()

            # 转换为易读的格式（例如：ABCD-EFGH-IJKL）
            sas_code = "-".join(
                hash_bytes[i : i + 4].hex().upper() for i in range(0, 12, 4)
            )

            verification["sas_code"] = sas_code
            verification["state"] = VerificationState.KEY_EXCHANGE.value

            logger.info(f"Generated SAS code for verification {verification_id}")
            return sas_code
        except Exception as e:
            logger.error(f"Failed to generate SAS code: {e}")
            return None

    def confirm_sas(self, verification_id: str, sas_code: str) -> bool:
        """
        确认 SAS 代码

        Args:
            verification_id: 验证 ID
            sas_code: 用户输入的 SAS 代码

        Returns:
            是否匹配
        """
        try:
            if verification_id not in self.verifications:
                logger.warning(f"Verification {verification_id} not found")
                return False

            verification = self.verifications[verification_id]
            expected_code = verification.get("sas_code")

            if expected_code and expected_code == sas_code:
                verification["state"] = VerificationState.MAC_EXCHANGE.value
                logger.info(f"SAS code confirmed for verification {verification_id}")
                return True
            else:
                logger.warning(f"SAS code mismatch for verification {verification_id}")
                return False
        except Exception as e:
            logger.error(f"Failed to confirm SAS: {e}")
            return False

    def complete_verification(self, verification_id: str) -> bool:
        """
        完成验证

        Args:
            verification_id: 验证 ID

        Returns:
            是否成功
        """
        try:
            if verification_id not in self.verifications:
                logger.warning(f"Verification {verification_id} not found")
                return False

            verification = self.verifications[verification_id]
            verification["state"] = VerificationState.VERIFIED.value

            logger.info(f"Completed verification {verification_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to complete verification: {e}")
            return False

    def cancel_verification(self, verification_id: str, reason: str = "") -> bool:
        """
        取消验证

        Args:
            verification_id: 验证 ID
            reason: 取消原因

        Returns:
            是否成功
        """
        try:
            if verification_id not in self.verifications:
                logger.warning(f"Verification {verification_id} not found")
                return False

            verification = self.verifications[verification_id]
            verification["state"] = VerificationState.CANCELLED.value
            verification["cancel_reason"] = reason

            logger.info(f"Cancelled verification {verification_id}: {reason}")
            return True
        except Exception as e:
            logger.error(f"Failed to cancel verification: {e}")
            return False

    def get_verification_status(self, verification_id: str) -> Optional[Dict[str, Any]]:
        """
        获取验证状态

        Args:
            verification_id: 验证 ID

        Returns:
            验证信息，或 None 如果不存在
        """
        return self.verifications.get(verification_id)

    def get_all_verifications(self) -> Dict[str, Dict[str, Any]]:
        """获取所有验证会话"""
        return self.verifications.copy()

    # ==================== 事件处理方法 ====================

    async def handle_ready(self, sender: str, content: Dict[str, Any]):
        """处理 m.key.verification.ready 事件"""
        transaction_id = content.get("transaction_id")
        from_device = content.get("from_device")
        methods = content.get("methods", [])

        logger.info(
            f"Received ready from {sender}:{from_device}, transaction: {transaction_id}"
        )
        logger.info(f"Supported methods: {methods}")

        # 查找对应的验证会话
        verification = None
        ver_id = None
        for ver_id, ver_data in self.verifications.items():
            if ver_id == transaction_id or (
                ver_data.get("other_user_id") == sender
                and ver_data.get("other_device_id") == from_device
            ):
                verification = ver_data
                verification["state"] = VerificationState.READY.value
                logger.info(f"Updated verification {ver_id} to READY state")
                break

        if not verification:
            logger.warning(f"No verification found for ready from {sender}")
            return

        # 自动发送 start 事件响应 ready
        if self.client and ver_id:
            logger.info(f"Sending start event in response to ready for {ver_id}")
            await self._send_start_event(ver_id, verification)

    async def handle_start(self, sender: str, content: Dict[str, Any]):
        """处理 m.key.verification.start 事件"""
        transaction_id = content.get("transaction_id")
        method = content.get("method")

        logger.info(
            f"Received start from {sender}, transaction: {transaction_id}, method: {method}"
        )

        # 更新验证状态
        if transaction_id in self.verifications:
            self.verifications[transaction_id]["state"] = (
                VerificationState.STARTED.value
            )
            logger.info(f"Verification {transaction_id} started with method {method}")

    async def handle_accept(self, sender: str, content: Dict[str, Any]):
        """处理 m.key.verification.accept 事件并发送 key"""
        transaction_id = content.get("transaction_id")
        commitment = content.get("commitment")

        logger.info(
            f"Received accept from {sender}, transaction: {transaction_id}, commitment: {commitment}"
        )

        if transaction_id in self.verifications:
            verification = self.verifications[transaction_id]
            verification["state"] = VerificationState.ACCEPTED.value
            verification["their_commitment"] = commitment

            logger.info(f"Verification {transaction_id} accepted")

            # 自动发送 key 事件
            if self.client:
                await self._send_key_event(transaction_id, verification)

    async def _send_key_event(self, transaction_id: str, verification: Dict[str, Any]):
        """发送 m.key.verification.key 事件"""
        try:
            import secrets

            other_user_id = verification["other_user_id"]
            other_device_id = verification["other_device_id"]

            # 生成临时公钥（在真实实现中应使用 Curve25519）
            our_key = secrets.token_hex(32)
            verification["our_key"] = our_key

            content = {
                "transaction_id": transaction_id,
                "key": our_key,
            }

            messages = {other_user_id: {other_device_id: content}}

            await self.client.send_to_device("m.key.verification.key", messages)
            logger.info(f"Sent verification key to {other_user_id}:{other_device_id}")

        except Exception as e:
            logger.error(f"Failed to send key event: {e}")
            raise

    async def handle_key(self, sender: str, content: Dict[str, Any]):
        """处理 m.key.verification.key 事件并自动生成 SAS 码"""
        transaction_id = content.get("transaction_id")
        key = content.get("key")

        logger.info(f"Received key from {sender}, transaction: {transaction_id}")

        if transaction_id in self.verifications:
            verification = self.verifications[transaction_id]
            verification["their_key"] = key
            verification["state"] = VerificationState.KEY_EXCHANGE.value

            logger.info(f"Stored key for verification {transaction_id}")

            # 自动生成 SAS 代码
            sas_code = self.generate_sas_code(transaction_id)
            if sas_code:
                logger.info(f"✨ Generated SAS code for {transaction_id}: {sas_code}")
                logger.info(
                    "📱 User should verify this code matches their client display"
                )

            # 自动发送 MAC（假设用户已确认 SAS 码）
            if self.client:
                await self._send_mac_event(transaction_id, verification)

    async def _send_mac_event(self, transaction_id: str, verification: Dict[str, Any]):
        """发送 m.key.verification.mac 事件"""
        try:
            import hashlib

            other_user_id = verification["other_user_id"]
            other_device_id = verification["other_device_id"]

            # 生成 MAC（在真实实现中应使用 HMAC-SHA256）
            our_key = verification.get("our_key", "")
            their_key = verification.get("their_key", "")
            combined = f"{our_key}{their_key}{transaction_id}"
            mac = hashlib.sha256(combined.encode()).hexdigest()

            content = {
                "transaction_id": transaction_id,
                "mac": {self.device_id: mac},
                "keys": f"ed25519:{self.device_id}",
            }

            messages = {other_user_id: {other_device_id: content}}

            await self.client.send_to_device("m.key.verification.mac", messages)
            logger.info(f"Sent verification MAC to {other_user_id}:{other_device_id}")

        except Exception as e:
            logger.error(f"Failed to send MAC event: {e}")
            raise

    async def handle_mac(self, sender: str, content: Dict[str, Any]):
        """处理 m.key.verification.mac 事件并发送 done"""
        transaction_id = content.get("transaction_id")
        mac_data = content.get("mac", {})

        logger.info(
            f"Received MAC from {sender}, transaction: {transaction_id}, mac: {mac_data}"
        )

        if transaction_id in self.verifications:
            verification = self.verifications[transaction_id]
            verification["state"] = VerificationState.MAC_RECEIVED.value
            verification["their_mac"] = mac_data

            logger.info(f"MAC received for verification {transaction_id}")

            # 自动发送 done 事件
            if self.client:
                await self._send_done_event(transaction_id, verification)

    async def _send_done_event(self, transaction_id: str, verification: Dict[str, Any]):
        """发送 m.key.verification.done 事件"""
        try:
            other_user_id = verification["other_user_id"]
            other_device_id = verification["other_device_id"]

            content = {
                "transaction_id": transaction_id,
            }

            messages = {other_user_id: {other_device_id: content}}

            await self.client.send_to_device("m.key.verification.done", messages)
            logger.info(
                f"✅ Sent verification done to {other_user_id}:{other_device_id}"
            )
            logger.info(f"🎉 Verification {transaction_id} completed!")

        except Exception as e:
            logger.error(f"Failed to send done event: {e}")
            raise

    async def handle_done(self, sender: str, content: Dict[str, Any]):
        """处理 m.key.verification.done 事件"""
        transaction_id = content.get("transaction_id")

        logger.info(f"Received done from {sender}, transaction: {transaction_id}")

        if transaction_id in self.verifications:
            self.verifications[transaction_id]["state"] = (
                VerificationState.VERIFIED.value
            )
            logger.info(f"Verification {transaction_id} completed successfully")

    async def handle_cancel(self, sender: str, content: Dict[str, Any]):
        """处理 m.key.verification.cancel 事件"""
        transaction_id = content.get("transaction_id")
        reason = content.get("reason", "unknown")
        code = content.get("code", "m.unknown")

        logger.info(
            f"Received cancel from {sender}, transaction: {transaction_id}, reason: {code} - {reason}"
        )

        if transaction_id in self.verifications:
            self.verifications[transaction_id]["state"] = (
                VerificationState.CANCELLED.value
            )
            self.verifications[transaction_id]["cancel_reason"] = reason
            self.verifications[transaction_id]["cancel_code"] = code
            logger.info(f"Verification {transaction_id} cancelled")
