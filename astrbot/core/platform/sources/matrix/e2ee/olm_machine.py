"""
Olm Machine - Olm/Megolm 加密操作封装

使用 vodozemac 实现加密/解密操作。
注意: 此模块需要安装 vodozemac 库。
"""

import base64
import json
import secrets
from typing import Any

from astrbot.api import logger

from .crypto_store import CryptoStore

# 尝试导入 vodozemac
try:
    import vodozemac
    from vodozemac import (
        Account,
        InboundGroupSession,
        OutboundGroupSession,
        Session,
    )

    VODOZEMAC_AVAILABLE = True
except ImportError:
    VODOZEMAC_AVAILABLE = False
    logger.warning(
        "vodozemac 未安装，E2EE 功能将不可用。请运行: pip install vodozemac"
    )


class OlmMachine:
    """
    Olm/Megolm 加密操作封装

    提供:
    - 设备密钥生成
    - Olm 会话管理
    - Megolm 加密/解密
    """

    def __init__(self, store: CryptoStore, user_id: str, device_id: str):
        """
        初始化 OlmMachine

        Args:
            store: 加密存储
            user_id: 用户 ID
            device_id: 设备 ID
        """
        if not VODOZEMAC_AVAILABLE:
            raise RuntimeError("vodozemac 未安装，无法使用 E2EE")

        self.store = store
        self.user_id = user_id
        self.device_id = device_id

        # Olm 账户
        self._account: Account | None = None

        # Olm 会话缓存: sender_key -> [Session]
        self._olm_sessions: dict[str, list[Session]] = {}

        # Megolm 会话缓存
        self._megolm_inbound: dict[str, InboundGroupSession] = {}
        self._megolm_outbound: dict[str, OutboundGroupSession] = {}

        # 初始化或加载账户
        self._init_account()

    def _init_account(self):
        """初始化或加载 Olm 账户"""
        pickle = self.store.get_account_pickle()

        if pickle:
            # 从 pickle 恢复账户
            try:
                self._account = Account.from_pickle(pickle)
                logger.info("从存储恢复 Olm 账户")
            except Exception as e:
                logger.error(f"恢复 Olm 账户失败: {e}")
                self._create_new_account()
        else:
            self._create_new_account()

    def _create_new_account(self):
        """创建新的 Olm 账户"""
        self._account = Account()
        self._save_account()
        logger.info("创建了新的 Olm 账户")

    def _save_account(self):
        """保存 Olm 账户到存储"""
        if self._account:
            pickle = self._account.pickle()
            self.store.save_account_pickle(pickle)

    # ========== 设备密钥 ==========

    def get_identity_keys(self) -> dict[str, str]:
        """获取设备身份密钥"""
        if not self._account:
            raise RuntimeError("Olm 账户未初始化")

        curve25519 = self._account.curve25519_key
        ed25519 = self._account.ed25519_key

        return {
            f"curve25519:{self.device_id}": curve25519,
            f"ed25519:{self.device_id}": ed25519,
        }

    def get_device_keys(self) -> dict[str, Any]:
        """
        获取用于上传的设备密钥

        返回符合 Matrix 规范的设备密钥格式
        """
        if not self._account:
            raise RuntimeError("Olm 账户未初始化")

        keys = self.get_identity_keys()

        device_keys = {
            "user_id": self.user_id,
            "device_id": self.device_id,
            "algorithms": [
                "m.olm.v1.curve25519-aes-sha2-256",
                "m.megolm.v1.aes-sha2",
            ],
            "keys": keys,
        }

        # 生成签名
        device_keys_json = self._canonical_json(device_keys)
        signature = self._account.sign(device_keys_json)

        device_keys["signatures"] = {
            self.user_id: {f"ed25519:{self.device_id}": signature}
        }

        return device_keys

    def generate_one_time_keys(self, count: int = 50) -> dict[str, dict]:
        """
        生成一次性密钥

        Args:
            count: 要生成的密钥数量

        Returns:
            签名的一次性密钥字典
        """
        if not self._account:
            raise RuntimeError("Olm 账户未初始化")

        # 生成新的一次性密钥
        self._account.generate_one_time_keys(count)

        # 获取一次性密钥
        one_time_keys = self._account.one_time_keys

        # 签名每个密钥
        signed_keys = {}
        for key_id, key in one_time_keys.items():
            signed_key = {
                "key": key,
            }

            # 生成签名
            key_json = self._canonical_json(signed_key)
            signature = self._account.sign(key_json)
            signed_key["signatures"] = {
                self.user_id: {f"ed25519:{self.device_id}": signature}
            }

            # 标记为已签名的 curve25519
            signed_keys[f"signed_curve25519:{key_id}"] = signed_key

        return signed_keys

    def mark_keys_as_published(self):
        """标记一次性密钥为已发布"""
        if self._account:
            self._account.mark_keys_as_published()
            self._save_account()

    # ========== Olm 会话 ==========

    def create_outbound_session(
        self, their_identity_key: str, their_one_time_key: str
    ) -> Session:
        """
        创建出站 Olm 会话

        Args:
            their_identity_key: 对方的 curve25519 身份密钥
            their_one_time_key: 对方的一次性密钥

        Returns:
            新的 Olm 会话
        """
        if not self._account:
            raise RuntimeError("Olm 账户未初始化")

        session = self._account.create_outbound_session(
            their_identity_key, their_one_time_key
        )

        # 缓存会话
        if their_identity_key not in self._olm_sessions:
            self._olm_sessions[their_identity_key] = []
        self._olm_sessions[their_identity_key].append(session)

        # 保存会话
        self.store.add_olm_session(their_identity_key, session.pickle())
        self._save_account()

        return session

    def decrypt_olm_message(
        self, sender_key: str, message_type: int, ciphertext: str
    ) -> str:
        """
        解密 Olm 消息

        Args:
            sender_key: 发送者的 curve25519 密钥
            message_type: 消息类型 (0=prekey, 1=normal)
            ciphertext: 密文

        Returns:
            明文
        """
        if not self._account:
            raise RuntimeError("Olm 账户未初始化")

        # 尝试使用现有会话解密
        sessions = self._olm_sessions.get(sender_key, [])
        for i, session in enumerate(sessions):
            try:
                plaintext = session.decrypt(message_type, ciphertext)
                # 更新会话
                self.store.update_olm_session(sender_key, i, session.pickle())
                return plaintext
            except Exception:
                continue

        # 如果是 prekey 消息，创建新的入站会话
        if message_type == 0:
            session = self._account.create_inbound_session(sender_key, ciphertext)
            plaintext = session.decrypt(message_type, ciphertext)

            # 移除已使用的一次性密钥
            self._account.remove_one_time_keys(session)

            # 缓存和保存会话
            if sender_key not in self._olm_sessions:
                self._olm_sessions[sender_key] = []
            self._olm_sessions[sender_key].append(session)
            self.store.add_olm_session(sender_key, session.pickle())
            self._save_account()

            return plaintext

        raise RuntimeError(f"无法解密来自 {sender_key} 的 Olm 消息")

    # ========== Megolm 会话 ==========

    def add_megolm_inbound_session(
        self, room_id: str, session_id: str, session_key: str, sender_key: str
    ):
        """
        添加 Megolm 入站会话 (从 m.room_key 事件)

        Args:
            room_id: 房间 ID
            session_id: 会话 ID
            session_key: 会话密钥
            sender_key: 发送者的 curve25519 密钥
        """
        try:
            session = InboundGroupSession(session_key)
            self._megolm_inbound[session_id] = session
            self.store.save_megolm_inbound(session_id, session.pickle())
            logger.debug(f"添加 Megolm 入站会话: {session_id[:8]}... 房间: {room_id}")
        except Exception as e:
            logger.error(f"添加 Megolm 入站会话失败: {e}")

    def decrypt_megolm(self, session_id: str, ciphertext: str) -> dict | None:
        """
        解密 Megolm 消息

        Args:
            session_id: 会话 ID
            ciphertext: 密文

        Returns:
            解密后的事件内容，或 None
        """
        # 尝试从缓存获取会话
        session = self._megolm_inbound.get(session_id)

        # 尝试从存储加载
        if not session:
            pickle = self.store.get_megolm_inbound(session_id)
            if pickle:
                try:
                    session = InboundGroupSession.from_pickle(pickle)
                    self._megolm_inbound[session_id] = session
                except Exception as e:
                    logger.error(f"加载 Megolm 会话失败: {e}")
                    return None

        if not session:
            logger.warning(f"未找到 Megolm 会话: {session_id[:8]}...")
            return None

        try:
            plaintext = session.decrypt(ciphertext)
            # 解析解密后的 JSON
            return json.loads(plaintext.plaintext)
        except Exception as e:
            logger.error(f"Megolm 解密失败: {e}")
            return None

    def create_megolm_outbound_session(self, room_id: str) -> tuple[str, str]:
        """
        创建 Megolm 出站会话

        Args:
            room_id: 房间 ID

        Returns:
            (session_id, session_key) 元组
        """
        session = OutboundGroupSession()
        self._megolm_outbound[room_id] = session
        self.store.save_megolm_outbound(room_id, session.pickle())

        return session.session_id, session.session_key

    def encrypt_megolm(self, room_id: str, event_type: str, content: dict) -> dict:
        """
        使用 Megolm 加密消息

        Args:
            room_id: 房间 ID
            event_type: 事件类型
            content: 事件内容

        Returns:
            加密后的 m.room.encrypted 内容
        """
        session = self._megolm_outbound.get(room_id)
        if not session:
            raise RuntimeError(f"房间 {room_id} 没有 Megolm 出站会话")

        # 构造要加密的有效载荷
        payload = {
            "type": event_type,
            "content": content,
            "room_id": room_id,
        }
        payload_json = json.dumps(payload, ensure_ascii=False)

        # 加密
        ciphertext = session.encrypt(payload_json)

        # 更新存储
        self.store.save_megolm_outbound(room_id, session.pickle())

        return {
            "algorithm": "m.megolm.v1.aes-sha2",
            "sender_key": self._account.curve25519_key if self._account else "",
            "session_id": session.session_id,
            "ciphertext": ciphertext,
            "device_id": self.device_id,
        }

    # ========== 辅助方法 ==========

    @staticmethod
    def _canonical_json(obj: dict) -> str:
        """生成规范化的 JSON 字符串 (用于签名)"""
        return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    @property
    def curve25519_key(self) -> str:
        """获取本设备的 curve25519 密钥"""
        if not self._account:
            raise RuntimeError("Olm 账户未初始化")
        return self._account.curve25519_key

    @property
    def ed25519_key(self) -> str:
        """获取本设备的 ed25519 密钥"""
        if not self._account:
            raise RuntimeError("Olm 账户未初始化")
        return self._account.ed25519_key
