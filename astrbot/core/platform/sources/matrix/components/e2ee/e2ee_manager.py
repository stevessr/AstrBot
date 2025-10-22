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
from .e2ee_auto_setup import MatrixE2EEAutoSetup


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
        self.auto_setup = MatrixE2EEAutoSetup(client, self, user_id, device_id)

        self.enabled = False
        # 记录已发起但尚未满足的群组密钥请求，避免频繁重复请求
        # key: f"{room_id}:{session_id}", value: 上次请求时间戳 (ms)
        self._pending_key_requests: Dict[str, int] = {}

    async def initialize(self, auto_setup: bool = True) -> bool:
        """
        初始化 E2EE 管理器并上传密钥到服务器

        Args:
            auto_setup: 是否自动设置 E2EE（获取设备、交换密钥等）

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

            # 自动设置 E2EE（如果启用）
            if auto_setup and self.client:
                logger.info("Starting automatic E2EE setup...")
                await self.auto_setup.setup_e2ee()

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

            # 构建 device_keys 对象（符合 Matrix 规范）
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
            logger.info("✅ Uploaded device keys successfully")
            logger.info(f"   One-time key counts: {otk_counts}")

        except Exception as e:
            logger.error(f"Failed to upload device keys: {e}")
            # 不抛出异常，因为 E2EE 可以继续工作

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

    async def share_room_key(self, room_id: str, user_ids: List[str]) -> bool:
        """
        分享房间密钥给指定用户的所有设备

        这个方法会：
        1. 确保所有用户的设备都有 Olm 会话
        2. 创建或获取房间的 Megolm 会话
        3. 将房间密钥加密后发送给每个设备

        Args:
            room_id: 房间 ID
            user_ids: 用户 ID 列表

        Returns:
            是否成功分享
        """
        try:
            # 1. 确保所有设备都有 Olm 会话
            sessions_created = await self.auto_setup.get_missing_sessions(user_ids)
            if sessions_created > 0:
                logger.info(
                    f"Created {sessions_created} new Olm sessions for room key sharing"
                )

            # 2. 确保房间有 Megolm 会话
            session = self.crypto.group_sessions.get(room_id)
            if not session:
                session_id = self.crypto.create_group_session(room_id)
                if not session_id:
                    logger.error(f"Failed to create group session for {room_id}")
                    return False
                session = self.crypto.group_sessions[room_id]

            # 3. 获取房间密钥
            room_key_content = {
                "algorithm": "m.megolm.v1.aes-sha2",
                "room_id": room_id,
                "session_id": session.session_id(),
                "session_key": session.session_key(),
            }

            # 4. 收集所有需要发送密钥的设备
            devices_to_share = []
            for user_id in user_ids:
                try:
                    # 对于当前用户，使用get_devices() API
                    if user_id == self.user_id:
                        response = await self.client.get_devices()
                        devices = response.get("devices", [])
                        for device in devices:
                            device_id = device.get("device_id")
                            # 跳过当前设备
                            if device_id == self.device_id:
                                continue
                            # 检查是否有 Olm 会话
                            if self.crypto.has_olm_session(user_id, device_id):
                                devices_to_share.append((user_id, device_id))
                    else:
                        # 对于其他用户，使用query_keys API获取设备信息
                        query_response = await self.client.query_keys(
                            device_keys={user_id: []}
                        )
                        device_keys = query_response.get("device_keys", {}).get(
                            user_id, {}
                        )
                        for device_id in device_keys.keys():
                            # 检查是否有 Olm 会话
                            if self.crypto.has_olm_session(user_id, device_id):
                                devices_to_share.append((user_id, device_id))
                except Exception as e:
                    logger.warning(f"Failed to get devices for {user_id}: {e}")
                    continue

            if not devices_to_share:
                logger.warning(f"No devices to share room key with for {room_id}")
                return False

            # 5. 为每个设备加密并发送房间密钥
            import json

            room_key_json = json.dumps(room_key_content)

            for user_id, device_id in devices_to_share:
                try:
                    # 使用 Olm 加密房间密钥
                    encrypted = self.crypto.encrypt_message(
                        user_id, device_id, room_key_json
                    )
                    if not encrypted:
                        logger.warning(
                            f"Failed to encrypt room key for {user_id}:{device_id}"
                        )
                        continue

                    # 发送 m.room_key 事件
                    await self.client.send_to_device(
                        event_type="m.room.encrypted",
                        messages={
                            user_id: {
                                device_id: {
                                    "algorithm": "m.olm.v1.curve25519-aes-sha2",
                                    "sender_key": self.crypto.account.curve25519_key.to_base64(),
                                    "ciphertext": encrypted,
                                }
                            }
                        },
                    )
                    logger.debug(f"Shared room key with {user_id}:{device_id}")

                except Exception as e:
                    logger.warning(
                        f"Failed to share room key with {user_id}:{device_id}: {e}"
                    )
                    continue

            logger.info(
                f"✅ Shared room key for {room_id} with {len(devices_to_share)} device(s)"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to share room key: {e}")
            return False

    async def decrypt_megolm_event(
        self,
        room_id: str,
        sender: str,
        sender_key: str,
        session_id: str,
        ciphertext: str,
    ) -> Optional[str]:
        """
        解密 Megolm 加密的房间事件

        Args:
            room_id: 房间 ID
            sender: 发送者用户 ID
            sender_key: 发送者设备的 Curve25519 密钥
            session_id: Megolm 会话 ID
            ciphertext: 密文

        Returns:
            解密后的明文，或 None 如果失败
        """
        try:
            logger.debug(
                f"Attempting to decrypt Megolm message in room {room_id} from {sender}"
            )

            # 从存储中获取对应的群组会话
            session = self.store.get_group_session(room_id, session_id)

            if not session:
                logger.warning(
                    f"No group session found for room {room_id}, session {session_id}"
                )
                logger.info(
                    "💡 Hint: You may need to request the room key from verified devices"
                )
                # 自动向本账号已验证的其他设备请求房间密钥
                try:
                    requested = await self.request_room_key(
                        room_id, session_id, sender_key
                    )
                    if not requested:
                        logger.debug(
                            f"Room key request for {session_id} was skipped (no suitable devices or rate limited)"
                        )
                except Exception as req_err:
                    logger.warning(f"Auto room key request failed: {req_err}")
                return None

            # 使用 vodozemac 解密
            plaintext = session.decrypt(ciphertext)
            logger.info(f"✅ Successfully decrypted Megolm message in room {room_id}")

            return plaintext

        except Exception as e:
            logger.error(f"Error decrypting Megolm event: {e}")
            return None

    async def decrypt_olm_event(
        self, sender: str, device_id: str, ciphertext: Dict[str, Any]
    ) -> Optional[str]:
        """
        解密 Olm 加密的事件（1 对 1）

        Args:
            sender: 发送者用户 ID
            device_id: 发送者设备 ID
            ciphertext: 密文字典（包含所有设备的密文）

        Returns:
            解密后的明文，或 None 如果失败
        """
        try:
            logger.debug(f"Attempting to decrypt Olm message from {sender}:{device_id}")

            # 目前返回 None，因为我们还没有实现 Olm 解密
            # 需要：
            # 1. 从 ciphertext 字典中找到给我们设备的密文
            # 2. 使用 vodozemac 的 Account/Session 解密
            logger.warning(
                "Olm decryption not yet implemented - message will be skipped"
            )
            return None

        except Exception as e:
            logger.error(f"Error decrypting Olm event: {e}")
            return None

    # ==================== 群组密钥请求 ====================

    async def request_room_key(
        self, room_id: str, session_id: str, sender_key: Optional[str] = None
    ) -> bool:
        """
        通过 to-device 发送 m.room_key_request，向本账号已验证且非当前设备请求 Megolm 群组密钥。

        Args:
            room_id: 房间 ID
            session_id: Megolm 会话 ID（缺这个无法定位密钥）
            sender_key: 发送者设备的 Curve25519 公钥（可选，但推荐提供）

        Returns:
            是否已成功发送至少一个请求
        """
        try:
            if not self.client:
                logger.warning("Matrix client not available, cannot request room key")
                return False

            if not self.enabled:
                logger.warning("E2EE manager not enabled, skip room key request")
                return False

            # 防抖：30 秒内同一个 room_id:session_id 只请求一次
            import time

            req_key = f"{room_id}:{session_id}"
            now_ms = int(time.time() * 1000)
            last_req = self._pending_key_requests.get(req_key, 0)
            if now_ms - last_req < 30_000:
                logger.debug(
                    f"Skip duplicate room key request for {req_key} within 30s window"
                )
                return False

            # 选择目标设备：本账号已验证且不是当前设备，且有E2EE支持
            verified_devices = self.store.get_verified_devices(self.user_id)
            target_devices = []

            for device_id in verified_devices:
                if device_id == self.device_id:
                    continue
                # 检查是否有Olm会话（表示设备支持E2EE）
                if self.crypto.has_olm_session(self.user_id, device_id):
                    target_devices.append(device_id)

            if not target_devices:
                if not verified_devices or len(verified_devices) <= 1:
                    logger.debug(
                        "No verified sibling devices found to request keys from; consider verifying another device."
                    )
                else:
                    logger.debug(
                        f"Found {len(verified_devices)} verified devices but none have Olm sessions; they may not support E2EE."
                    )
                # 仍然记录一次，避免疯狂重试
                self._pending_key_requests[req_key] = now_ms
                return False

            # 构造请求内容（Matrix 规范）
            request_id = f"$rk_{now_ms}_{session_id}"
            body: Dict[str, Any] = {
                "algorithm": "m.megolm.v1.aes-sha2",
                "room_id": room_id,
                "session_id": session_id,
            }
            if sender_key:
                body["sender_key"] = sender_key

            content = {
                "action": "request",
                "body": body,
                "request_id": request_id,
                "from_device": self.device_id,
            }

            # 发送给每个目标设备
            messages: Dict[str, Dict[str, Any]] = {
                self.user_id: dict.fromkeys(target_devices, content)
            }
            await self.client.send_to_device("m.room_key_request", messages)

            self._pending_key_requests[req_key] = now_ms
            logger.info(
                f"📤 Requested room key for {room_id} session {session_id} from {len(target_devices)} verified device(s)"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to request room key: {e}")
            return False

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

    async def handle_encrypted_to_device(
        self, sender: str, content: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        处理加密的 to-device 消息（m.room.encrypted with algorithm m.olm.v1.curve25519-aes-sha2）

        Args:
            sender: 发送者用户 ID
            content: 加密的事件内容

        Returns:
            解密后的事件内容，或 None 如果失败
        """
        try:
            algorithm = content.get("algorithm")
            sender_key = content.get("sender_key")
            ciphertext_data = content.get("ciphertext", {})

            if algorithm != "m.olm.v1.curve25519-aes-sha2":
                logger.warning(
                    f"Unsupported to-device encryption algorithm: {algorithm}"
                )
                return None

            # Find ciphertext for our device
            device_ciphertext = ciphertext_data.get(self.device_id)
            if not device_ciphertext:
                logger.warning(f"No ciphertext found for our device {self.device_id}")
                return None

            message_type = device_ciphertext.get("type")
            body = device_ciphertext.get("body")

            if message_type is None or body is None:
                logger.warning("Invalid Olm message format")
                return None

            # Try to decrypt with existing session
            # Extract device_id from sender (format: @user:server)
            # We need to find which device sent this
            # For now, we'll try all sessions with this sender
            plaintext = None
            for session_key, session in self.crypto.sessions.items():
                if session_key.startswith(f"{sender}:"):
                    try:
                        plaintext = self.crypto.decrypt_message(
                            sender, session_key.split(":", 1)[1], message_type, body
                        )
                        if plaintext:
                            break
                    except Exception:
                        continue

            # If no existing session worked and this is a PreKey message, create new session
            if not plaintext and message_type == 0:
                logger.info(
                    f"Creating new Olm session from PreKey message from {sender}"
                )
                # We need the sender's device_id - extract from sender_key or use a placeholder
                # In a real implementation, we'd track device_id from the event
                device_id = (
                    "UNKNOWN"  # This should be extracted from the event metadata
                )

                if self.crypto.create_inbound_session(
                    sender, device_id, sender_key, body
                ):
                    plaintext = self.crypto.decrypt_message(
                        sender, device_id, message_type, body
                    )

            if not plaintext:
                logger.error(f"Failed to decrypt Olm to-device message from {sender}")
                return None

            # Parse decrypted JSON
            import json

            decrypted_event = json.loads(plaintext)

            logger.info(
                f"✅ Decrypted Olm to-device message from {sender}: {decrypted_event.get('type')}"
            )
            return decrypted_event

        except Exception as e:
            logger.error(f"Error handling encrypted to-device message: {e}")
            return None

    async def handle_room_key(self, sender: str, content: Dict[str, Any]):
        """
        处理接收到的房间密钥（m.room_key 事件）

        Args:
            sender: 发送者用户 ID
            content: 事件内容
        """
        try:
            algorithm = content.get("algorithm")
            room_id = content.get("room_id")
            session_id = content.get("session_id")
            session_key = content.get("session_key")
            sender_key = content.get("sender_key")

            logger.info(
                f"📨 Received room key from {sender} for room {room_id}, session {session_id}"
            )

            # m.forwarded_room_key 可能没有 algorithm 字段；若缺失，且核心字段存在，也允许导入
            if algorithm and algorithm != "m.megolm.v1.aes-sha2":
                logger.warning(f"Unsupported room key algorithm: {algorithm}")
                return

            if not all([room_id, session_id, session_key, sender_key]):
                logger.warning("Incomplete room key data")
                return

            # 导入会话密钥
            imported_session_id = self.store.import_group_session(
                room_id, sender_key, session_key
            )

            if imported_session_id:
                logger.info(
                    f"✅ Imported room key for {room_id}, can now decrypt messages!"
                )
            else:
                logger.error(f"Failed to import room key for {room_id}")

        except Exception as e:
            logger.error(f"Error handling room key: {e}")

    # ==================== 生命周期 ====================

    async def close(self):
        """关闭管理器，保存所有数据"""
        try:
            await self.store.close()
            logger.info("E2EE manager closed")
        except Exception as e:
            logger.error(f"Error closing E2EE manager: {e}")
