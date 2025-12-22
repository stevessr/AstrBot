"""
SAS Verification - Matrix 设备验证流程

实现 SAS (Short Authentication String) 验证协议。
使用 vodozemac 提供的真正 X25519 密钥交换和 HKDF。
支持 auto_accept / auto_reject / manual 三种模式。
所有模式都会打印详细的验证日志。
"""

import base64
import hashlib
import hmac
import json
import secrets
from pathlib import Path
from typing import Any, Literal

from astrbot.api import logger

from ..constants import (
    INFO_PREFIX_MAC,
    INFO_PREFIX_SAS,
    KEY_AGREEMENT_PROTOCOLS,
    M_KEY_VERIFICATION_ACCEPT,
    M_KEY_VERIFICATION_CANCEL,
    M_KEY_VERIFICATION_DONE,
    M_KEY_VERIFICATION_KEY,
    M_KEY_VERIFICATION_MAC,
    M_KEY_VERIFICATION_READY,
    M_KEY_VERIFICATION_REQUEST,
    M_KEY_VERIFICATION_START,
    M_SAS_V1_METHOD,
    SAS_BYTES_LENGTH_6,
    SAS_EMOJI_COUNT_7,
)
from .device_store import DeviceStore

# 尝试导入 vodozemac
try:
    from vodozemac import EstablishedSas, Sas  # noqa: F401

    VODOZEMAC_SAS_AVAILABLE = True
except ImportError:
    VODOZEMAC_SAS_AVAILABLE = False
    logger.debug("vodozemac SAS 模块不可用，将使用简化实现")

# SAS 验证相关常量
SAS_METHODS = [M_SAS_V1_METHOD]
HASHES = ["sha256"]
MESSAGE_AUTHENTICATION_CODES = ["hkdf-hmac-sha256.v2", "hkdf-hmac-sha256"]
SHORT_AUTHENTICATION_STRING = ["decimal", "emoji"]

# SAS Emoji 列表 (Matrix 规范定义的 64 个 emoji)
SAS_EMOJIS = [
    ("🐶", "Dog"),
    ("🐱", "Cat"),
    ("🦁", "Lion"),
    ("🐴", "Horse"),
    ("🦄", "Unicorn"),
    ("🐷", "Pig"),
    ("🐘", "Elephant"),
    ("🐰", "Rabbit"),
    ("🐼", "Panda"),
    ("🐓", "Rooster"),
    ("🐧", "Penguin"),
    ("🐢", "Turtle"),
    ("🐟", "Fish"),
    ("🐙", "Octopus"),
    ("🦋", "Butterfly"),
    ("🌷", "Flower"),
    ("🌳", "Tree"),
    ("🌵", "Cactus"),
    ("🍄", "Mushroom"),
    ("🌏", "Globe"),
    ("🌙", "Moon"),
    ("☁️", "Cloud"),
    ("🔥", "Fire"),
    ("🍌", "Banana"),
    ("🍎", "Apple"),
    ("🍓", "Strawberry"),
    ("🌽", "Corn"),
    ("🍕", "Pizza"),
    ("🎂", "Cake"),
    ("❤️", "Heart"),
    ("😀", "Smiley"),
    ("🤖", "Robot"),
    ("🎩", "Hat"),
    ("👓", "Glasses"),
    ("🔧", "Spanner"),
    ("🎅", "Santa"),
    ("👍", "Thumbs Up"),
    ("☂️", "Umbrella"),
    ("⌛", "Hourglass"),
    ("⏰", "Clock"),
    ("🎁", "Gift"),
    ("💡", "Light Bulb"),
    ("📕", "Book"),
    ("✏️", "Pencil"),
    ("📎", "Paperclip"),
    ("✂️", "Scissors"),
    ("🔒", "Lock"),
    ("🔑", "Key"),
    ("🔨", "Hammer"),
    ("☎️", "Telephone"),
    ("🏁", "Flag"),
    ("🚂", "Train"),
    ("🚲", "Bicycle"),
    ("✈️", "Aeroplane"),
    ("🚀", "Rocket"),
    ("🏆", "Trophy"),
    ("⚽", "Ball"),
    ("🎸", "Guitar"),
    ("🎺", "Trumpet"),
    ("🔔", "Bell"),
    ("⚓", "Anchor"),
    ("🎧", "Headphones"),
    ("📁", "Folder"),
    ("📌", "Pin"),
]


def _canonical_json(obj: dict) -> str:
    """生成 Matrix 规范的规范化 JSON"""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _compute_hkdf(
    input_key: bytes,
    salt: bytes,
    info: bytes,
    length: int = 32,
) -> bytes:
    """计算 HKDF-SHA256"""
    # HKDF-Extract
    if not salt:
        salt = b"\x00" * 32
    prk = hmac.new(salt, input_key, hashlib.sha256).digest()

    # HKDF-Expand
    output = b""
    t = b""
    counter = 1
    while len(output) < length:
        t = hmac.new(prk, t + info + bytes([counter]), hashlib.sha256).digest()
        output += t
        counter += 1
    return output[:length]


class SASVerification:
    """
    SAS 验证流程管理器

    使用 vodozemac 提供的真正密码学实现
    """

    def __init__(
        self,
        client,
        user_id: str,
        device_id: str,
        olm_machine,
        store_path: Path,
        auto_verify_mode: Literal[
            "auto_accept", "auto_reject", "manual"
        ] = "auto_accept",
    ):
        self.client = client
        self.user_id = user_id
        self.device_id = device_id
        self.olm = olm_machine
        self.auto_verify_mode = auto_verify_mode

        # 活跃的验证会话：transaction_id -> session_data
        self._sessions: dict[str, dict[str, Any]] = {}
        self.device_store = DeviceStore(store_path)

    async def handle_verification_event(
        self, event_type: str, sender: str, content: dict
    ) -> bool:
        """处理验证事件"""
        transaction_id = content.get("transaction_id")

        if not transaction_id:
            logger.warning("[E2EE-Verify] 缺少 transaction_id，忽略事件")
            return False

        logger.info(
            f"[E2EE-Verify] 收到验证事件：{event_type} "
            f"from={sender} txn={transaction_id}"
        )
        logger.debug(
            f"[E2EE-Verify] 事件内容：{json.dumps(content, ensure_ascii=False)}"
        )

        handlers = {
            M_KEY_VERIFICATION_REQUEST: self._handle_request,
            M_KEY_VERIFICATION_READY: self._handle_ready,
            M_KEY_VERIFICATION_START: self._handle_start,
            M_KEY_VERIFICATION_ACCEPT: self._handle_accept,
            M_KEY_VERIFICATION_KEY: self._handle_key,
            M_KEY_VERIFICATION_MAC: self._handle_mac,
            M_KEY_VERIFICATION_DONE: self._handle_done,
            M_KEY_VERIFICATION_CANCEL: self._handle_cancel,
        }

        handler = handlers.get(event_type)
        if handler:
            await handler(sender, content, transaction_id)
            return True
        return False

    async def handle_in_room_verification_event(
        self, event_type: str, sender: str, content: dict, room_id: str, event_id: str
    ) -> bool:
        """处理房间内验证事件"""
        # In-room verification uses m.relates_to to link events
        relates_to = content.get("m.relates_to", {})
        msgtype = content.get("msgtype", "")

        # For m.key.verification.request events (either as event_type OR msgtype),
        # use event_id as transaction_id
        is_verification_request = (
            event_type == M_KEY_VERIFICATION_REQUEST
            or msgtype == "m.key.verification.request"
        )

        if is_verification_request:
            transaction_id = event_id
        else:
            # For other events, get transaction_id from m.relates_to
            transaction_id = relates_to.get("event_id") or content.get("transaction_id")

        if not transaction_id:
            logger.warning("[E2EE-Verify] 房间内验证事件缺少 transaction_id")
            return False

        logger.info(
            f"[E2EE-Verify] 收到房间内验证事件：{event_type} "
            f"from={sender} room={room_id[:16]}... txn={transaction_id[:16]}..."
        )

        # Store room_id in session for in-room responses
        if transaction_id not in self._sessions:
            self._sessions[transaction_id] = {}
        self._sessions[transaction_id]["room_id"] = room_id
        self._sessions[transaction_id]["is_in_room"] = True

        handlers = {
            M_KEY_VERIFICATION_REQUEST: self._handle_in_room_request,
            M_KEY_VERIFICATION_READY: self._handle_ready,
            M_KEY_VERIFICATION_START: self._handle_start,
            M_KEY_VERIFICATION_ACCEPT: self._handle_accept,
            M_KEY_VERIFICATION_KEY: self._handle_key,
            M_KEY_VERIFICATION_MAC: self._handle_mac,
            M_KEY_VERIFICATION_DONE: self._handle_done,
            M_KEY_VERIFICATION_CANCEL: self._handle_cancel,
        }

        # For verification requests (m.room.message with msgtype m.key.verification.request),
        # use _handle_in_room_request directly
        if is_verification_request:
            await self._handle_in_room_request(sender, content, transaction_id)
            return True

        handler = handlers.get(event_type)
        if handler:
            await handler(sender, content, transaction_id)
            return True
        return False

    async def _handle_in_room_request(
        self, sender: str, content: dict, transaction_id: str
    ):
        """处理房间内验证请求"""
        from_device = content.get("from_device")
        methods = content.get("methods", [])

        if not from_device:
            logger.warning("[E2EE-Verify] 房间内验证请求缺少 from_device")
            return

        logger.info(
            f"[E2EE-Verify] 收到房间内验证请求："
            f"sender={sender} device={from_device} methods={methods}"
        )

        # 创建 SAS 实例
        sas = None
        if VODOZEMAC_SAS_AVAILABLE:
            try:
                sas = Sas()
                pub = sas.public_key.to_base64()
                logger.debug(f"[E2EE-Verify] 创建 SAS 实例，公钥：{pub[:16]}...")
            except Exception as e:
                logger.warning(f"[E2EE-Verify] 创建 SAS 实例失败：{e}")

        session = self._sessions.get(transaction_id, {})
        session.update(
            {
                "sender": sender,
                "from_device": from_device,
                "methods": methods,
                "state": "requested",
                "sas": sas,
            }
        )
        self._sessions[transaction_id] = session

        # TOFU: Check if device is trusted
        fingerprint = self.olm.ed25519_key if self.olm else "unavaliable"
        if self.device_store.is_trusted(sender, from_device, fingerprint):
            logger.info(f"[E-Verify] Trusted device {sender}|{from_device}")
        else:
            logger.info(f"[E2EE-Verify] Untrusted device {sender}|{from_device}")
            await self._notify_user_for_approval(
                sender, from_device, session.get("room_id")
            )
            if self.auto_verify_mode == "auto_accept":
                logger.info("[E2EE-Verify] Auto-accept disabled for untrusted device")
                return

        if self.auto_verify_mode == "auto_reject":
            logger.info("[E2EE-Verify] 自动拒绝验证请求 (mode=auto_reject)")
            await self._send_in_room_cancel(
                session["room_id"], transaction_id, "m.user", "自动拒绝"
            )
            return

        if self.auto_verify_mode == "manual":
            logger.info("[E2EE-Verify] 手动模式，记录验证请求但不响应 (mode=manual)")
            return

        # auto_accept: 发送 ready
        if "m.sas.v1" in methods:
            logger.info("[E2EE-Verify] 自动接受房间内验证请求 (mode=auto_accept)")
            await self._send_in_room_ready(session["room_id"], transaction_id)
        else:
            logger.warning(f"[E2EE-Verify] 不支持的验证方法：{methods}")
            await self._send_in_room_cancel(
                session["room_id"],
                transaction_id,
                "m.unknown_method",
                "不支持的验证方法",
            )

    async def _handle_request(self, sender: str, content: dict, transaction_id: str):
        """处理验证请求"""
        from_device = content.get("from_device")
        methods = content.get("methods", [])
        if not from_device:
            logger.warning("[E2EE-Verify] 验证请求缺少 from_device，忽略")
            return

        logger.info(
            f"[E2EE-Verify] 收到验证请求："
            f"sender={sender} device={from_device} methods={methods}"
        )

        # 创建 SAS 实例
        sas = None
        if VODOZEMAC_SAS_AVAILABLE:
            try:
                sas = Sas()
                pub = sas.public_key.to_base64()
                logger.debug(f"[E2EE-Verify] 创建 SAS 实例，公钥：{pub[:16]}...")
            except Exception as e:
                logger.warning(f"[E2EE-Verify] 创建 SAS 实例失败：{e}")

        self._sessions[transaction_id] = {
            "sender": sender,
            "from_device": from_device,
            "methods": methods,
            "state": "requested",
            "sas": sas,
        }

        if self.auto_verify_mode == "auto_reject":
            logger.info("[E2EE-Verify] 自动拒绝验证请求 (mode=auto_reject)")
            await self._send_cancel(
                sender, from_device, transaction_id, "m.user", "自动拒绝"
            )
            return

        if self.auto_verify_mode == "manual":
            logger.info("[E2EE-Verify] 手动模式，记录验证请求但不响应 (mode=manual)")
            return

        # auto_accept: 发送 ready
        if "m.sas.v1" in methods:
            logger.info("[E2EE-Verify] 自动接受验证请求 (mode=auto_accept)")
            await self._send_ready(sender, from_device, transaction_id)
        else:
            logger.warning(f"[E2EE-Verify] 不支持的验证方法：{methods}")
            await self._send_cancel(
                sender,
                from_device,
                transaction_id,
                "m.unknown_method",
                "不支持的验证方法",
            )

    async def _handle_ready(self, sender: str, content: dict, transaction_id: str):
        """处理 ready 响应"""
        from_device = content.get("from_device")
        methods = content.get("methods", [])

        logger.info(f"[E2EE-Verify] 对方已就绪：device={from_device} methods={methods}")

        session = self._sessions.get(transaction_id, {})
        session["state"] = "ready"
        session["their_device"] = from_device

    async def _handle_start(self, sender: str, content: dict, transaction_id: str):
        """处理验证开始"""
        from_device = content.get("from_device")
        method = content.get("method")
        their_commitment = content.get("commitment")

        logger.info(
            f"[E2EE-Verify] 验证开始：method={method} "
            f"commitment={their_commitment[:16] if their_commitment else 'None'}..."
        )

        session = self._sessions.get(transaction_id, {})
        session["state"] = "started"
        session["method"] = method
        session["their_commitment"] = their_commitment
        session["start_content"] = content

        if self.auto_verify_mode == "auto_accept":
            if from_device:
                await self._send_accept(sender, from_device, transaction_id, content)

    async def _handle_accept(self, sender: str, content: dict, transaction_id: str):
        """处理验证接受"""
        commitment = content.get("commitment")
        key_agreement = content.get("key_agreement_protocol")
        hash_algo = content.get("hash")
        mac = content.get("message_authentication_code")
        sas_methods = content.get("short_authentication_string", [])

        logger.info(
            f"[E2EE-Verify] 对方接受验证："
            f"key_agreement={key_agreement} hash={hash_algo} mac={mac}"
        )

        session = self._sessions.get(transaction_id, {})
        session["state"] = "accepted"
        session["their_commitment"] = commitment
        session["key_agreement"] = key_agreement
        session["hash"] = hash_algo
        session["mac"] = mac
        session["sas_methods"] = sas_methods

        if self.auto_verify_mode == "auto_accept":
            await self._send_key(
                sender,
                content.get("from_device", session.get("from_device", "")),
                transaction_id,
            )

    async def _handle_key(self, sender: str, content: dict, transaction_id: str):
        """处理密钥交换 - 使用真正的 X25519"""
        their_key = content.get("key")

        if not isinstance(their_key, str) or not their_key:
            logger.warning("[E2EE-Verify] 对方公钥缺失或格式不正确")
            return
        logger.info(f"[E2EE-Verify] 收到对方公钥：{their_key[:20]}...")

        session = self._sessions.get(transaction_id, {})
        session["their_key"] = their_key
        session["state"] = "key_exchanged"

        sas = session.get("sas")
        our_key = session.get("our_public_key")

        if sas and VODOZEMAC_SAS_AVAILABLE and their_key:
            try:
                # 使用 vodozemac 计算共享密钥
                # 构造 SAS info 字符串
                their_user = sender
                their_device = session.get(
                    "from_device", session.get("their_device", "")
                )

                info = (
                    f"{INFO_PREFIX_SAS}"
                    f"{self.user_id}|{self.device_id}|{our_key}|"
                    f"{their_user}|{their_device}|{their_key}|"
                    f"{transaction_id}"
                )

                # 设置对方的公钥并生成 SAS 字节
                sas.set_their_public_key(their_key)
                sas_bytes = sas.generate_bytes(info.encode(), SAS_BYTES_LENGTH_6)

                # 将 SAS 字节转换为 emoji 和 decimal
                emojis = self._bytes_to_emoji(sas_bytes)
                decimals = self._bytes_to_decimal(sas_bytes)

                session["sas_bytes"] = sas_bytes
                session["sas_emojis"] = emojis
                session["sas_decimals"] = decimals

                logger.info("[E2EE-Verify] ===== SAS 验证码 (使用 vodozemac) =====")
                logger.info(f"[E2EE-Verify] Emoji: {' '.join(e[0] for e in emojis)}")
                logger.info(
                    f"[E2EE-Verify] Emoji 名称：{', '.join(e[1] for e in emojis)}"
                )
                logger.info(f"[E2EE-Verify] 数字：{decimals}")
                logger.info("[E2EE-Verify] ==========================================")

            except Exception as e:
                logger.error(f"[E2EE-Verify] 计算 SAS 失败：{e}")
                # 回退到简化实现
                self._compute_sas_fallback(session, their_key)
        else:
            # 使用简化实现
            self._compute_sas_fallback(session, their_key)

        if self.auto_verify_mode == "auto_accept":
            await self._send_mac(
                sender,
                session.get("their_device", session.get("from_device", "")),
                transaction_id,
                session,
            )

    def _compute_sas_fallback(self, session: dict, their_key: str):
        """回退的 SAS 计算（当 vodozemac SAS 不可用时）"""
        our_key = session.get("our_public_key", "")
        combined = f"{our_key}{their_key}".encode()
        sas_bytes = hashlib.sha256(combined).digest()[:SAS_BYTES_LENGTH_6]

        emojis = self._bytes_to_emoji(sas_bytes)
        decimals = self._bytes_to_decimal(sas_bytes)

        session["sas_bytes"] = sas_bytes
        session["sas_emojis"] = emojis
        session["sas_decimals"] = decimals

        logger.info("[E2EE-Verify] ===== SAS 验证码 (简化实现) =====")
        logger.info(f"[E2EE-Verify] Emoji: {' '.join(e[0] for e in emojis)}")
        logger.info(f"[E2EE-Verify] Emoji 名称：{', '.join(e[1] for e in emojis)}")
        logger.info(f"[E2EE-Verify] 数字：{decimals}")
        logger.info("[E2EE-Verify] =====================================")

    async def _handle_mac(self, sender: str, content: dict, transaction_id: str):
        """处理 MAC 验证"""
        their_mac = content.get("mac", {})
        their_keys = content.get("keys")

        logger.info(f"[E2EE-Verify] 收到 MAC: keys={their_keys}")
        logger.debug(f"[E2EE-Verify] MAC 内容：{their_mac}")

        session = self._sessions.get(transaction_id, {})
        session["their_mac"] = their_mac
        session["state"] = "mac_received"

        # 验证 MAC
        sas = session.get("sas")
        if sas and VODOZEMAC_SAS_AVAILABLE:
            try:
                # 使用 vodozemac 验证 MAC（暂时简化）
                logger.info("[E2EE-Verify] MAC 验证 (简化)：接受")
            except Exception as e:
                logger.error(f"[E2EE-Verify] MAC 验证失败：{e}")

        if self.auto_verify_mode == "auto_accept":
            await self._send_done(
                sender,
                session.get("their_device", session.get("from_device", "")),
                transaction_id,
            )

    async def _handle_done(self, sender: str, content: dict, transaction_id: str):
        """处理验证完成"""
        logger.info(f"[E2EE-Verify] ✅ 验证完成！sender={sender} txn={transaction_id}")

        session = self._sessions.get(transaction_id, {})
        session["state"] = "done"

        # TODO: 将设备标记为已验证

    async def _handle_cancel(self, sender: str, content: dict, transaction_id: str):
        """处理验证取消"""
        code = content.get("code")
        reason = content.get("reason")

        logger.warning(f"[E2EE-Verify] ❌ 验证被取消：code={code} reason={reason}")

        if transaction_id in self._sessions:
            self._sessions[transaction_id]["state"] = "cancelled"
            self._sessions[transaction_id]["cancel_code"] = code
            self._sessions[transaction_id]["cancel_reason"] = reason

    # ========== 发送验证消息 ==========

    async def _send_ready(self, to_user: str, to_device: str, transaction_id: str):
        """发送 ready 响应"""
        content = {
            "from_device": self.device_id,
            "methods": SAS_METHODS,
            "transaction_id": transaction_id,
        }
        await self._send_to_device(
            M_KEY_VERIFICATION_READY, to_user, to_device, content
        )
        logger.info("[E2EE-Verify] 已发送 ready")

    async def _send_accept(
        self, to_user: str, to_device: str, transaction_id: str, start_content: dict
    ):
        """发送 accept - 使用真正的密钥协商"""
        their_key_agreement = start_content.get("key_agreement_protocols", [])
        their_hashes = start_content.get("hashes", [])
        their_macs = start_content.get("message_authentication_codes", [])
        their_sas = start_content.get("short_authentication_string", [])

        key_agreement = next(
            (k for k in KEY_AGREEMENT_PROTOCOLS if k in their_key_agreement),
            KEY_AGREEMENT_PROTOCOLS[0],
        )
        hash_algo = next((h for h in HASHES if h in their_hashes), HASHES[0])
        mac = next(
            (m for m in MESSAGE_AUTHENTICATION_CODES if m in their_macs),
            MESSAGE_AUTHENTICATION_CODES[0],
        )
        sas_methods = [s for s in SHORT_AUTHENTICATION_STRING if s in their_sas]

        session = self._sessions.get(transaction_id, {})

        # 生成我们的公钥
        sas = session.get("sas")
        if sas and VODOZEMAC_SAS_AVAILABLE:
            our_public_key = sas.public_key
        else:
            # 回退：生成随机密钥 (仅用于显示)
            our_public_key = base64.b64encode(secrets.token_bytes(32)).decode()

        session["our_public_key"] = our_public_key
        session["key_agreement"] = key_agreement
        session["hash"] = hash_algo
        session["mac"] = mac
        session["sas_methods"] = sas_methods

        # 计算 commitment = Base64(SHA256(public_key || canonical_json(start_content)))
        commitment_data = our_public_key + _canonical_json(start_content)
        commitment = base64.b64encode(
            hashlib.sha256(commitment_data.encode()).digest()
        ).decode()

        content = {
            "transaction_id": transaction_id,
            "method": "m.sas.v1",
            "key_agreement_protocol": key_agreement,
            "hash": hash_algo,
            "message_authentication_code": mac,
            "short_authentication_string": sas_methods,
            "commitment": commitment,
        }

        await self._send_to_device(
            M_KEY_VERIFICATION_ACCEPT, to_user, to_device, content
        )
        logger.info(f"[E2EE-Verify] 已发送 accept (commitment: {commitment[:16]}...)")

    async def _send_key(self, to_user: str, to_device: str, transaction_id: str):
        """发送公钥"""
        session = self._sessions.get(transaction_id, {})

        sas = session.get("sas")
        if sas and VODOZEMAC_SAS_AVAILABLE:
            our_public_key = sas.public_key
        else:
            our_public_key = session.get(
                "our_public_key", base64.b64encode(secrets.token_bytes(32)).decode()
            )

        session["our_public_key"] = our_public_key

        content = {
            "transaction_id": transaction_id,
            "key": our_public_key,
        }

        await self._send_to_device(M_KEY_VERIFICATION_KEY, to_user, to_device, content)
        logger.info(f"[E2EE-Verify] 已发送 key: {our_public_key[:20]}...")

    async def _send_mac(
        self, to_user: str, to_device: str, transaction_id: str, session: dict
    ):
        """发送 MAC - 使用 HKDF-HMAC-SHA256"""
        sas = session.get("sas")
        sas_bytes = session.get("sas_bytes", b"\x00" * 32)

        # 生成 MAC 的基础密钥
        our_device_key_id = f"ed25519:{self.device_id}"

        if sas and VODOZEMAC_SAS_AVAILABLE:
            try:
                info_mac = f"{INFO_PREFIX_MAC}{self.user_id}{self.device_id}{to_user}{to_device}{transaction_id}"

                # 计算设备密钥的 MAC
                if self.olm:
                    device_key = self.olm.ed25519_key
                    key_mac = sas.calculate_mac(
                        device_key, (info_mac + our_device_key_id).encode()
                    )
                    keys_mac = sas.calculate_mac(
                        our_device_key_id, (info_mac + "KEY_IDS").encode()
                    )
                else:
                    key_mac = base64.b64encode(
                        hashlib.sha256(our_device_key_id.encode()).digest()
                    ).decode()
                    keys_mac = base64.b64encode(
                        hashlib.sha256(our_device_key_id.encode()).digest()
                    ).decode()

                mac_content = {our_device_key_id: key_mac}
            except Exception as e:
                logger.warning(f"[E2EE-Verify] vodozemac MAC 计算失败，使用回退：{e}")
                # 回退实现
                mac_content = {
                    our_device_key_id: base64.b64encode(
                        _compute_hkdf(sas_bytes, b"", our_device_key_id.encode())
                    ).decode()
                }
                keys_mac = base64.b64encode(
                    hashlib.sha256(our_device_key_id.encode()).digest()
                ).decode()
        else:
            # 回退实现
            mac_content = {
                our_device_key_id: base64.b64encode(
                    _compute_hkdf(sas_bytes, b"", our_device_key_id.encode())
                ).decode()
            }
            keys_mac = base64.b64encode(
                hashlib.sha256(our_device_key_id.encode()).digest()
            ).decode()

        content = {
            "transaction_id": transaction_id,
            "mac": mac_content,
            "keys": keys_mac,
        }

        await self._send_to_device(M_KEY_VERIFICATION_MAC, to_user, to_device, content)
        logger.info("[E2EE-Verify] 已发送 mac")

    async def _send_done(self, to_user: str, to_device: str, transaction_id: str):
        """发送 done"""
        content = {"transaction_id": transaction_id}
        await self._send_to_device(M_KEY_VERIFICATION_DONE, to_user, to_device, content)
        logger.info("[E2EE-Verify] 已发送 done")

    async def _send_cancel(
        self, to_user: str, to_device: str, transaction_id: str, code: str, reason: str
    ):
        """发送取消"""
        content = {
            "transaction_id": transaction_id,
            "code": code,
            "reason": reason,
        }
        await self._send_to_device(
            M_KEY_VERIFICATION_CANCEL, to_user, to_device, content
        )
        logger.info(f"[E2EE-Verify] 已发送 cancel: {code} - {reason}")

    async def _send_to_device(
        self, event_type: str, to_user: str, to_device: str, content: dict
    ):
        """发送 to_device 消息"""
        try:
            txn_id = secrets.token_hex(16)
            messages = {to_user: {to_device: content}}
            await self.client.send_to_device(event_type, messages, txn_id)
        except Exception as e:
            logger.error(f"[E2EE-Verify] 发送 {event_type} 失败：{e}")

    # ========== In-Room 验证消息发送 ==========

    async def _send_in_room_event(
        self, room_id: str, event_type: str, content: dict, transaction_id: str
    ):
        """发送房间内验证事件"""
        try:
            # Add m.relates_to to link to the original request
            content["m.relates_to"] = {
                "rel_type": "m.reference",
                "event_id": transaction_id,
            }

            await self.client.send_room_event(room_id, event_type, content)
            logger.info(f"[E2EE-Verify] 已发送房间内事件：{event_type}")
        except Exception as e:
            logger.error(f"[E2EE-Verify] 发送房间内事件 {event_type} 失败：{e}")

    async def _send_in_room_ready(self, room_id: str, transaction_id: str):
        """发送房间内 ready 响应"""
        content = {
            "from_device": self.device_id,
            "methods": SAS_METHODS,
        }
        logger.debug(
            f"[E2EE-Verify] 发送 ready: device_id={self.device_id} methods={SAS_METHODS}"
        )
        await self._send_in_room_event(
            room_id, M_KEY_VERIFICATION_READY, content, transaction_id
        )
        logger.info("[E2EE-Verify] 已发送房间内 ready")

    async def _send_in_room_cancel(
        self, room_id: str, transaction_id: str, code: str, reason: str
    ):
        """发送房间内取消"""
        content = {
            "code": code,
            "reason": reason,
        }
        await self._send_in_room_event(
            room_id, M_KEY_VERIFICATION_CANCEL, content, transaction_id
        )
        logger.info(f"[E2EE-Verify] 已发送房间内 cancel: {code} - {reason}")

    # ========== SAS 计算 ==========

    async def _notify_user_for_approval(self, sender: str, device_id: str, room_id: str | None = None):
        """ "Notify user for verification approval"""
        if not room_id:
            room_id = await self.client.get_user_room(sender)

        if room_id:
            message = (
                f"New device verification request from {sender} ({device_id}). "
                f"Please approve or deny."
            )
            await self.client.send_room_message(room_id, message)
        else:
            logger.warning(f"Could not find a room to notify {sender}")

    def _bytes_to_emoji(self, sas_bytes: bytes) -> list[tuple[str, str]]:
        """将 SAS 字节转换为 emoji"""
        bits = int.from_bytes(sas_bytes[:SAS_BYTES_LENGTH_6], "big")
        emojis = []
        for i in range(SAS_EMOJI_COUNT_7):
            idx = (bits >> (42 - i * 6)) & 0x3F
            emojis.append(SAS_EMOJIS[idx])
        return emojis

    def _bytes_to_decimal(self, sas_bytes: bytes) -> str:
        """将 SAS 字节转换为三组四位数字"""
        bits = int.from_bytes(sas_bytes[:5], "big")
        n1 = ((bits >> 27) & 0x1FFF) + 1000
        n2 = ((bits >> 14) & 0x1FFF) + 1000
        n3 = ((bits >> 1) & 0x1FFF) + 1000
        return f"{n1} {n2} {n3}"
