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
    STARTED = "started"
    ACCEPTED = "accepted"
    KEY_EXCHANGE = "key_exchange"
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

    def accept_verification(self, verification_id: str) -> bool:
        """
        接受验证请求

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

            logger.info(f"Accepted verification {verification_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to accept verification: {e}")
            return False

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
