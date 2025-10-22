"""
Matrix E2EE 加密/解密模块
处理消息的加密和解密，支持 Olm 和 Megolm 协议
"""

from typing import Optional, Dict, Any
from astrbot import logger

try:
    from vodozemac import (
        Account,
        Session,
        InboundGroupSession,
        OutboundGroupSession,
        OlmMessage,
        Curve25519PublicKey,
    )

    VODOZEMAC_AVAILABLE = True
    logger.info("✅ vodozemac library loaded successfully")
except ImportError as e:
    Account = None
    Session = None
    InboundGroupSession = None
    OutboundGroupSession = None
    OlmMessage = None
    Curve25519PublicKey = None
    VODOZEMAC_AVAILABLE = False
    logger.warning(f"vodozemac not available, E2EE features will be limited: {e}")
    logger.info("💡 To enable full E2EE support, install vodozemac-python:")
    logger.info("   pip install vodozemac>=0.9.0")
    logger.info("   or: uv add vodozemac>=0.9.0")


class MatrixE2EECrypto:
    """Matrix E2EE 加密/解密处理"""

    def __init__(self, account: Optional[Account] = None):
        """
        初始化加密模块

        Args:
            account: vodozemac Account 实例
        """
        self.account = account
        self.sessions: Dict[
            str, Session
        ] = {}  # Olm 一对一会话: "user_id:device_id" -> Session
        self.group_sessions: Dict[
            str, OutboundGroupSession
        ] = {}  # 出站群组会话: room_id -> OutboundGroupSession
        self.inbound_group_sessions: Dict[
            str, InboundGroupSession
        ] = {}  # 入站群组会话: session_id -> InboundGroupSession

    def create_outbound_session(
        self, user_id: str, device_id: str, identity_key: str, one_time_key: str
    ) -> bool:
        """
        创建出站 Olm 会话（用于加密消息）

        Args:
            user_id: 目标用户 ID
            device_id: 目标设备 ID
            identity_key: 目标设备的 Curve25519 身份密钥
            one_time_key: 目标设备的一次性密钥

        Returns:
            是否成功创建
        """
        if not self.account or not VODOZEMAC_AVAILABLE:
            logger.warning("Account not initialized or vodozemac not available")
            return False

        try:
            if not Curve25519PublicKey:
                logger.error("Curve25519PublicKey not available")
                return False

            session_key = f"{user_id}:{device_id}"

            # Parse keys
            identity_key_obj = Curve25519PublicKey.from_base64(identity_key)
            one_time_key_obj = Curve25519PublicKey.from_base64(one_time_key)

            # Create outbound session
            session = self.account.create_outbound_session(
                identity_key_obj, one_time_key_obj
            )
            self.sessions[session_key] = session

            logger.info(f"Created outbound Olm session with {session_key}")
            return True
        except Exception as e:
            logger.error(f"Failed to create outbound session: {e}")
            return False

    def create_inbound_session(
        self, user_id: str, device_id: str, sender_key: str, ciphertext: str
    ) -> bool:
        """
        创建入站 Olm 会话（用于解密消息）

        Args:
            user_id: 发送者用户 ID
            device_id: 发送者设备 ID
            sender_key: 发送者的 Curve25519 密钥
            ciphertext: 预密钥消息（OlmMessage type 0）

        Returns:
            是否成功创建
        """
        if not self.account or not VODOZEMAC_AVAILABLE:
            logger.warning("Account not initialized or vodozemac not available")
            return False

        try:
            if not OlmMessage:
                logger.error("OlmMessage not available")
                return False

            session_key = f"{user_id}:{device_id}"

            # Create OlmMessage from ciphertext
            olm_message = OlmMessage.from_parts(
                0, ciphertext
            )  # Type 0 = PreKey message

            # Create inbound session
            session = self.account.create_inbound_session(sender_key, olm_message)
            self.sessions[session_key] = session

            logger.info(f"Created inbound Olm session with {session_key}")
            return True
        except Exception as e:
            logger.error(f"Failed to create inbound session: {e}")
            return False

    def has_olm_session(self, user_id: str, device_id: str) -> bool:
        """
        检查是否存在 Olm 会话

        Args:
            user_id: 用户 ID
            device_id: 设备 ID

        Returns:
            是否存在会话
        """
        session_key = f"{user_id}:{device_id}"
        return session_key in self.sessions

    def get_session(self, user_id: str, device_id: str) -> Optional[Session]:
        """
        获取 Olm 会话

        Args:
            user_id: 用户 ID
            device_id: 设备 ID

        Returns:
            Session 对象，或 None 如果不存在
        """
        session_key = f"{user_id}:{device_id}"
        return self.sessions.get(session_key)

    def encrypt_message(
        self, user_id: str, device_id: str, plaintext: str
    ) -> Optional[Dict[str, Any]]:
        """
        使用 Olm 加密消息（1对1）

        Args:
            user_id: 目标用户 ID
            device_id: 目标设备 ID
            plaintext: 明文消息（JSON 字符串）

        Returns:
            加密后的消息内容，或 None 如果失败
        """
        if not VODOZEMAC_AVAILABLE:
            logger.warning("vodozemac not available, cannot encrypt")
            return None

        try:
            session_key = f"{user_id}:{device_id}"
            session = self.sessions.get(session_key)

            if not session:
                logger.warning(f"No Olm session found for {session_key}")
                return None

            # Encrypt message using Olm session
            olm_message = session.encrypt(plaintext)

            # Get message type and ciphertext
            message_type = olm_message.message_type
            ciphertext = olm_message.ciphertext

            return {
                "algorithm": "m.olm.v1.curve25519-aes-sha2",
                "sender_key": self.account.curve25519_key.to_base64()
                if self.account
                else "",
                "ciphertext": {
                    device_id: {
                        "type": message_type,
                        "body": ciphertext,
                    }
                },
            }
        except Exception as e:
            logger.error(f"Failed to encrypt Olm message: {e}")
            return None

    def decrypt_message(
        self, user_id: str, device_id: str, message_type: int, ciphertext: str
    ) -> Optional[str]:
        """
        使用 Olm 解密消息（1对1）

        Args:
            user_id: 发送者用户 ID
            device_id: 发送者设备 ID
            message_type: Olm 消息类型（0=PreKey, 1=Message）
            ciphertext: 密文

        Returns:
            解密后的明文（JSON 字符串），或 None 如果失败
        """
        if not VODOZEMAC_AVAILABLE:
            logger.warning("vodozemac not available, cannot decrypt")
            return None

        try:
            if not OlmMessage:
                logger.error("OlmMessage not available")
                return None

            session_key = f"{user_id}:{device_id}"
            session = self.sessions.get(session_key)

            if not session:
                logger.warning(f"No Olm session found for {session_key}")
                return None

            # Create OlmMessage from type and ciphertext
            olm_message = OlmMessage.from_parts(message_type, ciphertext)

            # Decrypt message
            plaintext = session.decrypt(olm_message)

            return plaintext
        except Exception as e:
            logger.error(f"Failed to decrypt Olm message: {e}")
            return None

    def create_group_session(self, room_id: str) -> Optional[str]:
        """
        创建 Megolm 出站群组会话

        Args:
            room_id: 房间 ID

        Returns:
            会话 ID，或 None 如果失败
        """
        if not VODOZEMAC_AVAILABLE:
            logger.warning("vodozemac not available, cannot create group session")
            return None

        try:
            if not OutboundGroupSession:
                logger.error("OutboundGroupSession not available")
                return None

            # Create outbound group session
            session = OutboundGroupSession()
            session_id = session.session_id()

            self.group_sessions[room_id] = session

            logger.info(
                f"Created Megolm outbound group session for {room_id}: {session_id}"
            )
            return session_id
        except Exception as e:
            logger.error(f"Failed to create group session: {e}")
            return None

    def encrypt_group_message(
        self, room_id: str, plaintext: str
    ) -> Optional[Dict[str, Any]]:
        """
        使用 Megolm 加密群组消息

        Args:
            room_id: 房间 ID
            plaintext: 明文消息（JSON 字符串）

        Returns:
            加密后的消息内容，或 None 如果失败
        """
        if not VODOZEMAC_AVAILABLE:
            logger.warning("vodozemac not available, cannot encrypt")
            return None

        try:
            session = self.group_sessions.get(room_id)

            if not session:
                logger.warning(f"No outbound group session found for {room_id}")
                # Try to create one
                session_id = self.create_group_session(room_id)
                if not session_id:
                    return None
                session = self.group_sessions[room_id]

            # Encrypt message using Megolm
            ciphertext = session.encrypt(plaintext)

            return {
                "algorithm": "m.megolm.v1.aes-sha2",
                "sender_key": self.account.curve25519_key.to_base64()
                if self.account
                else "",
                "ciphertext": ciphertext,
                "session_id": session.session_id(),
                "device_id": self.account.ed25519_key.to_base64()
                if self.account
                else "",
            }
        except Exception as e:
            logger.error(f"Failed to encrypt Megolm group message: {e}")
            return None

    def decrypt_group_message(self, session_id: str, ciphertext: str) -> Optional[str]:
        """
        使用 Megolm 解密群组消息

        Args:
            session_id: Megolm 会话 ID
            ciphertext: 密文

        Returns:
            解密后的明文（JSON 字符串），或 None 如果失败
        """
        if not VODOZEMAC_AVAILABLE:
            logger.warning("vodozemac not available, cannot decrypt")
            return None

        try:
            session = self.inbound_group_sessions.get(session_id)

            if not session:
                logger.warning(
                    f"No inbound group session found for session {session_id}"
                )
                return None

            # Decrypt message using Megolm
            plaintext = session.decrypt(ciphertext)

            return plaintext
        except Exception as e:
            logger.error(f"Failed to decrypt Megolm group message: {e}")
            return None

    def add_inbound_group_session(self, session_id: str, session: InboundGroupSession):
        """
        添加入站群组会话

        Args:
            session_id: 会话 ID
            session: InboundGroupSession 对象
        """
        self.inbound_group_sessions[session_id] = session
        logger.debug(f"Added inbound group session: {session_id}")

    def get_group_session_key(self, room_id: str) -> Optional[str]:
        """
        获取群组会话密钥（用于分享给其他设备）

        Args:
            room_id: 房间 ID

        Returns:
            会话密钥（导出格式），或 None 如果失败
        """
        if not VODOZEMAC_AVAILABLE:
            return None

        try:
            session = self.group_sessions.get(room_id)
            if not session:
                return None

            # Export session key
            return session.session_key()
        except Exception as e:
            logger.error(f"Failed to get group session key: {e}")
            return None
