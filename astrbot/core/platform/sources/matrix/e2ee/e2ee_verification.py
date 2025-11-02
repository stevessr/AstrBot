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

    def generate_sas_code(self, verification_id: str) -> Optional[Dict[str, str]]:
        """
        生成短认证字符串（SAS）- 支持 emoji 和 decimal 格式
        
        按照 Matrix 规范生成 SAS：
        - Emoji: 7 个 emoji 符号
        - Decimal: 3 组 4 位数字
        
        Args:
            verification_id: 验证 ID
        
        Returns:
            包含 emoji 和 decimal 格式的字典，或 None 如果失败
        """
        try:
            if verification_id not in self.verifications:
                logger.warning(f"Verification {verification_id} not found")
                return None

            verification = self.verifications[verification_id]
            
            # 需要双方的密钥来生成 SAS
            our_key = verification.get("our_key")
            their_key = verification.get("their_key")
            
            if not our_key or not their_key:
                logger.warning(f"Missing keys for SAS generation")
                return None

            # 生成共享密钥材料
            # 按照 Matrix 规范：HKDF-SHA256(共享密钥, info, 6 bytes)
            import hashlib
            import hmac
            
            # 简化实现：使用 HMAC 生成 SAS 字节
            combined = f"{our_key}|{their_key}|{verification_id}".encode()
            sas_bytes = hmac.new(b"MATRIX_KEY_VERIFICATION_SAS", combined, hashlib.sha256).digest()[:6]

            # Emoji SAS - 使用 Matrix 规范定义的 64 个 emoji
            EMOJI_SAS = [
                "🐶", "🐱", "🦁", "🐴", "🦄", "🐷", "🐮", "🐗",
                "🐵", "🐔", "🐧", "🐦", "🐤", "🐣", "🐺", "🐗",
                "🐝", "🐛", "🦋", "🐌", "🐞", "🐜", "🦟", "🐢",
                "🐍", "🦎", "🐙", "🦑", "🦀", "🦞", "🦐", "🐡",
                "🐠", "🐟", "🐬", "🐳", "🐋", "🦈", "🐊", "🐅",
                "🐆", "🦓", "🦍", "🐘", "🦏", "🦛", "🐪", "🐫",
                "🦒", "🐃", "🐂", "🐄", "🐎", "🐖", "🐏", "🐑",
                "🐐", "🦌", "🐕", "🐩", "🐈", "🐓", "🦃", "🦚",
            ]
            
            # 从 6 字节生成 7 个 emoji（每个使用 6 bits = 64 种可能）
            emoji_indices = []
            bit_string = ''.join(format(b, '08b') for b in sas_bytes)
            for i in range(7):
                start = i * 6
                if start + 6 <= len(bit_string):
                    index = int(bit_string[start:start+6], 2)
                    emoji_indices.append(index % 64)
            
            emoji_sas = ' '.join(EMOJI_SAS[i] for i in emoji_indices)

            # Decimal SAS - 生成 3 组 4 位数字
            # 使用前 5 字节生成 3 个 13-bit 数字（范围 0-8191，显示为 4 位）
            num1 = ((sas_bytes[0] << 5) | (sas_bytes[1] >> 3)) & 0x1FFF
            num2 = (((sas_bytes[1] & 0x07) << 10) | (sas_bytes[2] << 2) | (sas_bytes[3] >> 6)) & 0x1FFF
            num3 = (((sas_bytes[3] & 0x3F) << 7) | (sas_bytes[4] >> 1)) & 0x1FFF
            
            decimal_sas = f"{num1:04d}-{num2:04d}-{num3:04d}"

            sas_codes = {
                "emoji": emoji_sas,
                "decimal": decimal_sas,
            }
            
            verification["sas_codes"] = sas_codes
            verification["state"] = VerificationState.KEY_EXCHANGE.value

            logger.debug(f"Generated SAS codes for verification {verification_id}")
            return sas_codes
            
        except Exception as e:
            logger.error(f"Failed to generate SAS code: {e}", exc_info=True)
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

    async def handle_request(self, sender: str, content: Dict[str, Any]):
        """
        处理 m.key.verification.request 事件（初始验证请求）
        这是验证流程的第一步
        """
        transaction_id = content.get("transaction_id")
        from_device = content.get("from_device")
        methods = content.get("methods", [])
        timestamp = content.get("timestamp")

        logger.info(f"📨 Received verification request from {sender}:{from_device}")
        logger.info(f"   Transaction: {transaction_id}")
        logger.info(f"   Supported methods: {methods}")

        # 检查是否支持 SAS 验证
        if "m.sas.v1" not in methods:
            logger.warning(f"Device {sender}:{from_device} doesn't support m.sas.v1, cannot verify")
            return

        # 创建验证会话
        verification = {
            "other_user_id": sender,
            "other_device_id": from_device,
            "transaction_id": transaction_id,
            "state": VerificationState.REQUESTED.value,
            "methods": methods,
            "timestamp": timestamp,
        }
        self.verifications[transaction_id] = verification

        # 自动发送 ready 响应
        try:
            content = {
                "from_device": self.device_id,
                "methods": ["m.sas.v1"],  # 我们支持的方法
                "transaction_id": transaction_id,
            }

            messages = {sender: {from_device: content}}
            await self.client.send_to_device("m.key.verification.ready", messages)
            
            verification["state"] = VerificationState.READY.value
            logger.info(f"✅ Sent ready response, waiting for start...")

        except Exception as e:
            logger.error(f"Failed to send ready response: {e}")
            raise

    async def handle_ready(self, sender: str, content: Dict[str, Any]):
        """处理 m.key.verification.ready 事件"""
        transaction_id = content.get("transaction_id")
        from_device = content.get("from_device")
        methods = content.get("methods", [])

        logger.info(
            f"📨 Received ready from {sender}:{from_device}, transaction: {transaction_id}"
        )
        logger.info(f"   Supported methods: {methods}")

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
                logger.info(f"✅ Updated verification {ver_id} to READY state")
                break

        if not verification:
            logger.warning(f"No verification found for ready from {sender}")
            return

        # 自动发送 start 事件响应 ready
        if self.client and ver_id:
            logger.info(f"Sending start event in response to ready for {ver_id}")
            await self._send_start_event(ver_id, verification)

    async def handle_start(self, sender: str, content: Dict[str, Any]):
        """处理 m.key.verification.start 事件并自动接受"""
        transaction_id = content.get("transaction_id")
        method = content.get("method")
        from_device = content.get("from_device")

        logger.info(f"📨 Received start from {sender}:{from_device}")
        logger.info(f"   Transaction: {transaction_id}, method: {method}")

        # 检查是否支持该方法
        if method != "m.sas.v1":
            logger.warning(f"Unsupported verification method: {method}")
            return

        # 更新或创建验证状态
        if transaction_id not in self.verifications:
            # 如果还没有验证会话，创建一个
            self.verifications[transaction_id] = {
                "other_user_id": sender,
                "other_device_id": from_device,
                "transaction_id": transaction_id,
                "state": VerificationState.STARTED.value,
            }
        else:
            self.verifications[transaction_id]["state"] = VerificationState.STARTED.value

        verification = self.verifications[transaction_id]
        verification["method"] = method
        verification["start_content"] = content

        logger.info(f"✅ Verification {transaction_id} started with method {method}")

        # 自动发送 accept 响应
        if self.client:
            await self._send_accept_event(transaction_id, verification)

    async def _send_accept_event(self, transaction_id: str, verification: Dict[str, Any]):
        """发送 m.key.verification.accept 事件"""
        try:
            import secrets
            import hashlib

            other_user_id = verification["other_user_id"]
            other_device_id = verification["other_device_id"]

            # 获取 start 事件的内容
            start_content = verification.get("start_content", {})

            # 生成 commitment (hash of our public key)
            # 在真实实现中应使用真实的公钥
            our_key = secrets.token_bytes(32)
            commitment = hashlib.sha256(our_key).hexdigest()
            verification["our_commitment_key"] = our_key

            content = {
                "transaction_id": transaction_id,
                "method": "m.sas.v1",
                "key_agreement_protocol": "curve25519-hkdf-sha256",
                "hash": "sha256",
                "message_authentication_code": "hkdf-hmac-sha256.v2",
                "short_authentication_string": ["emoji", "decimal"],
                "commitment": commitment,
            }

            messages = {other_user_id: {other_device_id: content}}

            await self.client.send_to_device("m.key.verification.accept", messages)
            verification["state"] = VerificationState.ACCEPTED.value
            logger.info(f"✅ Sent accept response to {other_user_id}:{other_device_id}")

        except Exception as e:
            logger.error(f"Failed to send accept event: {e}")
            raise

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
        """处理 m.key.verification.key 事件并生成 SAS 码"""
        transaction_id = content.get("transaction_id")
        key = content.get("key")

        logger.info(f"📨 Received key from {sender}, transaction: {transaction_id}")

        if transaction_id not in self.verifications:
            logger.warning(f"Verification {transaction_id} not found")
            return

        verification = self.verifications[transaction_id]
        verification["their_key"] = key
        verification["state"] = VerificationState.KEY_EXCHANGE.value

        logger.info(f"✅ Stored key for verification {transaction_id}")

        # 如果我们还没有发送 key，现在发送
        if "our_key" not in verification:
            if self.client:
                await self._send_key_event(transaction_id, verification)

        # 生成 SAS 代码（需要双方的公钥）
        if "our_key" in verification and "their_key" in verification:
            sas_code = self.generate_sas_code(transaction_id)
            if sas_code:
                logger.info(f"")
                logger.info(f"✨ ================== SAS 验证码 ==================")
                logger.info(f"   Transaction: {transaction_id}")
                logger.info(f"   Emoji: {sas_code['emoji']}")
                logger.info(f"   Decimal: {sas_code['decimal']}")
                logger.info(f"   ⚠️  请确认此代码与您其他设备上显示的一致！")
                logger.info(f"===================================================")
                logger.info(f"")

                # 自动发送 MAC（在实际使用中应该等待用户确认）
                # TODO: 添加用户确认步骤
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
