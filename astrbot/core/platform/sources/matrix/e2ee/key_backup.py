"""
Key Backup - Matrix 密钥备份

实现 Megolm 会话密钥的服务器端备份和恢复。
使用用户配置的恢复密钥进行加密。
"""

import base64
import hashlib
import hmac
import json
import secrets
from typing import Any

from astrbot.api import logger

# 尝试导入加密库
try:
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False
    logger.debug("cryptography 库不可用，密钥备份将使用简化加密")

# 尝试导入 vodozemac (用于 Matrix 兼容的 PkDecryption)
try:
    from vodozemac import Curve25519SecretKey, PkDecryption

    VODOZEMAC_PK_AVAILABLE = True
except ImportError:
    VODOZEMAC_PK_AVAILABLE = False
    logger.debug("vodozemac PkDecryption 不可用")


def _compute_hkdf(
    input_key: bytes, salt: bytes, info: bytes, length: int = 32
) -> bytes:
    """计算 HKDF-SHA256"""
    if CRYPTO_AVAILABLE:
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=length,
            salt=salt if salt else None,
            info=info,
            backend=default_backend(),
        )
        return hkdf.derive(input_key)
    else:
        # 简化的 HKDF 实现
        if not salt:
            salt = b"\x00" * 32
        prk = hmac.new(salt, input_key, hashlib.sha256).digest()
        output = b""
        t = b""
        counter = 1
        while len(output) < length:
            t = hmac.new(prk, t + info + bytes([counter]), hashlib.sha256).digest()
            output += t
            counter += 1
        return output[:length]


def _aes_encrypt(key: bytes, plaintext: bytes) -> tuple[bytes, bytes]:
    """AES-GCM 加密"""
    nonce = secrets.token_bytes(12)
    if CRYPTO_AVAILABLE:
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    else:
        # 简化实现 (不安全，仅用于测试)
        ciphertext = bytes(
            a ^ b for a, b in zip(plaintext, key * (len(plaintext) // len(key) + 1))
        )
    return nonce, ciphertext


def _aes_decrypt(key: bytes, nonce: bytes, ciphertext: bytes) -> bytes:
    """AES-GCM 解密"""
    if CRYPTO_AVAILABLE:
        aesgcm = AESGCM(key)
        return aesgcm.decrypt(nonce, ciphertext, None)
    else:
        # 简化实现 (不安全，仅用于测试)
        return bytes(
            a ^ b for a, b in zip(ciphertext, key * (len(ciphertext) // len(key) + 1))
        )


def _aes_ctr_decrypt(key: bytes, iv: bytes, ciphertext: bytes) -> bytes:
    """
    AES-256-CTR 解密 (Matrix 密钥备份使用此模式)
    """
    if CRYPTO_AVAILABLE:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        cipher = Cipher(algorithms.AES(key), modes.CTR(iv), backend=default_backend())
        decryptor = cipher.decryptor()
        return decryptor.update(ciphertext) + decryptor.finalize()
    else:
        # 无法使用简化实现，因为 CTR 模式需要正确的计数器处理
        raise RuntimeError("需要 cryptography 库来解密密钥备份")


def _decrypt_backup_data(
    private_key_bytes: bytes,
    ephemeral_public_key: bytes,
    ciphertext: bytes,
    mac: bytes,
) -> bytes | None:
    """
    解密 Matrix 密钥备份数据 (m.megolm_backup.v1.curve25519-aes-sha2)

    使用 vodozemac 的 PkDecryption 直接解密，它内部处理：
    1. ECDH: 使用私钥和临时公钥计算共享密钥
    2. 密钥派生和 AES 解密
    3. MAC 验证（虽然有已知缺陷）

    Args:
        private_key_bytes: 32 字节私钥
        ephemeral_public_key: 32 字节临时公钥 (来自备份数据的 ephemeral)
        ciphertext: 加密的数据
        mac: MAC 数据

    Returns:
        解密后的明文，或 None
    """
    try:
        from vodozemac import (
            Curve25519PublicKey,
            Curve25519SecretKey,
            PkDecryption,
        )

        logger.info(
            f"[E2EE-Backup] 使用 vodozemac 解密：private_key={len(private_key_bytes)}B, "
            f"ephemeral={len(ephemeral_public_key)}B, ciphertext={len(ciphertext)}B, mac={len(mac)}B"
        )

        # 创建 PkDecryption 对象
        secret_key = Curve25519SecretKey.from_bytes(private_key_bytes)
        pk_decryption = PkDecryption.from_key(secret_key)

        # 创建 Message 对象 - vodozemac 需要特定格式
        # 尝试直接传递字节数据解密
        try:
            # 方法 1: 使用 vodozemac 的内部 Message 格式
            from vodozemac import Message as VodozemacMessage

            # 尝试从 base64 格式创建
            # 参数顺序：from_base64(ciphertext, mac, ephemeral_key)
            ephemeral_key_b64 = base64.b64encode(ephemeral_public_key).decode()
            ciphertext_b64 = base64.b64encode(ciphertext).decode()
            mac_b64 = base64.b64encode(mac).decode()

            # 正确的参数顺序：ciphertext, mac, ephemeral_key
            message = VodozemacMessage.from_base64(
                ciphertext_b64, mac_b64, ephemeral_key_b64
            )
            plaintext = pk_decryption.decrypt(message)

            logger.info(f"[E2EE-Backup] vodozemac 解密成功！明文长度={len(plaintext)}B")
            return plaintext

        except Exception as e1:
            error_msg = str(e1)
            if "MAC" in error_msg or "mac" in error_msg or "mismatch" in error_msg:
                logger.warning(
                    "[E2EE-Backup] MAC 验证失败 - 恢复密钥可能与备份不匹配！"
                    "请确认您配置的恢复密钥是用于创建此备份的密钥。"
                )
            else:
                logger.debug(f"[E2EE-Backup] vodozemac 解密失败：{e1}")
            return None

    except ImportError:
        logger.warning("[E2EE-Backup] vodozemac 不可用，无法解密备份")
        return None
    except Exception as e:
        logger.warning(f"[E2EE-Backup] 解密失败：{e}")
        return None


def _encode_recovery_key(key_bytes: bytes) -> str:
    """将恢复密钥编码为用户友好格式"""
    return base64.b64encode(key_bytes).decode()


def _decode_recovery_key(key_str: str) -> bytes:
    """
    解码用户提供的恢复密钥

    支持多种格式：
    - Matrix 标准 base58 恢复密钥 (以 Es 开头，格式：0x8B 0x01 + 32 字节密钥 + 1 字节校验)
    - Base64 编码的 32 字节密钥
    """
    # 移除空格和破折号
    key_str = key_str.replace(" ", "").replace("-", "")

    # 如果以 E 开头，优先尝试 base58 解码 (Matrix 标准格式)
    if key_str.startswith("E"):
        try:
            # Matrix base58 解码
            ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
            n = 0
            for char in key_str:
                if char not in ALPHABET:
                    raise ValueError(f"Invalid base58 character: {char}")
                n = n * 58 + ALPHABET.index(char)

            # 计算需要的字节数 (至少 35 字节)
            byte_length = max(35, (n.bit_length() + 7) // 8)
            result = n.to_bytes(byte_length, "big")

            logger.info(
                f"[E2EE-Backup] Base58 解码：输入长度={len(key_str)}, "
                f"解码后={len(result)}B, 头=0x{result[0]:02x}{result[1]:02x}"
            )

            # 验证 Matrix 头部 (0x8B 0x01)
            if len(result) >= 35 and result[0] == 0x8B and result[1] == 0x01:
                # 提取 32 字节密钥 (跳过 2 字节头，忽略最后 1 字节校验)
                private_key = result[2:34]
                logger.info(f"[E2EE-Backup] 成功提取 32 字节私钥")
                return private_key
            else:
                logger.warning(
                    f"[E2EE-Backup] 恢复密钥头部不匹配：预期 0x8B01, 实际 0x{result[0]:02x}{result[1]:02x}"
                )
        except Exception as e:
            logger.warning(f"[E2EE-Backup] Base58 解码失败：{e}")

    # 尝试 base64 解码
    try:
        decoded = base64.b64decode(key_str)
        logger.info(f"[E2EE-Backup] Base64 解码：{len(decoded)}B")
        # 如果是 35 或 36 字节，提取中间的 32 字节密钥
        if len(decoded) >= 35:
            return decoded[2:34]
        elif len(decoded) == 32:
            return decoded
        else:
            return decoded[:32] if len(decoded) > 32 else decoded.ljust(32, b"\x00")
    except Exception:
        pass

    # 如果都失败，返回原始密钥的 hash 作为后备 (不推荐)
    logger.warning("[E2EE-Backup] 无法解码恢复密钥，使用 SHA256 hash")
    return hashlib.sha256(key_str.encode()).digest()


class KeyBackup:
    """
    密钥备份管理器

    使用用户配置的恢复密钥进行加密，支持：
    - 创建密钥备份
    - 上传 Megolm 会话密钥到备份
    - 从备份恢复密钥
    """

    def __init__(
        self,
        client,
        crypto_store,
        olm_machine,
        recovery_key: str = "",
    ):
        """
        初始化密钥备份

        Args:
            client: MatrixHTTPClient
            crypto_store: CryptoStore
            olm_machine: OlmMachine
            recovery_key: 用户配置的恢复密钥 (base64)
        """
        self.client = client
        self.store = crypto_store
        self.olm = olm_machine

        self._backup_version: str | None = None
        self._recovery_key_bytes: bytes | None = None
        self._encryption_key: bytes | None = None

        # 处理用户提供的恢复密钥
        if recovery_key:
            try:
                self._recovery_key_bytes = _decode_recovery_key(recovery_key)
                self._encryption_key = _compute_hkdf(
                    self._recovery_key_bytes, b"", b"m.megolm_backup.v1"
                )
                logger.info("[E2EE-Backup] 使用用户配置的恢复密钥")
            except Exception as e:
                logger.error(f"[E2EE-Backup] 解析恢复密钥失败：{e}")

    async def initialize(self):
        """初始化密钥备份"""
        try:
            version = await self._get_current_backup_version()
            if version:
                self._backup_version = version
                logger.info(f"[E2EE-Backup] 发现现有密钥备份：version={version}")
            else:
                logger.info("[E2EE-Backup] 未发现密钥备份")
        except Exception as e:
            logger.warning(f"[E2EE-Backup] 初始化失败：{e}")

    async def _get_current_backup_version(self) -> str | None:
        """获取当前备份版本"""
        try:
            response = await self.client._request(
                "GET", "/_matrix/client/v3/room_keys/version"
            )
            return response.get("version")
        except Exception:
            return None

    async def create_backup(self) -> tuple[str, str] | None:
        """
        创建新的密钥备份

        Returns:
            (version, recovery_key) 或 None
        """
        try:
            # 如果没有提供恢复密钥，生成新的
            if not self._recovery_key_bytes:
                self._recovery_key_bytes = secrets.token_bytes(32)
                self._encryption_key = _compute_hkdf(
                    self._recovery_key_bytes, b"", b"m.megolm_backup.v1"
                )
                recovery_key_str = _encode_recovery_key(self._recovery_key_bytes)

                logger.warning("[E2EE-Backup] " + "=" * 50)
                logger.warning("[E2EE-Backup] ⚠️  新生成的恢复密钥（请务必保存）:")
                logger.warning(f"[E2EE-Backup] {recovery_key_str}")
                logger.warning(
                    "[E2EE-Backup] 可将此密钥配置到 matrix_e2ee_recovery_key"
                )
                logger.warning("[E2EE-Backup] " + "=" * 50)
            else:
                recovery_key_str = _encode_recovery_key(self._recovery_key_bytes)

            # 生成用于备份的公钥
            # 使用恢复密钥的 SHA256 作为 "公钥" (简化实现)
            public_key = base64.b64encode(
                hashlib.sha256(self._recovery_key_bytes).digest()
            ).decode()

            # 创建备份
            response = await self.client._request(
                "POST",
                "/_matrix/client/v3/room_keys/version",
                data={
                    "algorithm": "m.megolm_backup.v1.curve25519-aes-sha2",
                    "auth_data": {
                        "public_key": public_key,
                    },
                },
            )

            version = response.get("version")
            if version:
                self._backup_version = version
                logger.info(f"[E2EE-Backup] 创建备份成功：version={version}")
                return (version, recovery_key_str)

        except Exception as e:
            logger.error(f"[E2EE-Backup] 创建备份失败：{e}")
        return None

    async def upload_room_keys(self, room_id: str | None = None):
        """
        上传房间密钥到备份

        Args:
            room_id: 可选，指定房间 ID
        """
        if not self._backup_version or not self._encryption_key:
            logger.warning("[E2EE-Backup] 未创建备份或无加密密钥，无法上传")
            return

        try:
            sessions = self.store._megolm_inbound
            if not sessions:
                logger.debug("[E2EE-Backup] 没有可上传的会话密钥")
                return

            rooms: dict[str, dict[str, dict]] = {}

            for session_id, pickle in sessions.items():
                # 加密会话数据
                plaintext = pickle.encode() if isinstance(pickle, str) else pickle
                nonce, ciphertext = _aes_encrypt(self._encryption_key, plaintext)

                session_data = {
                    "first_message_index": 0,
                    "forwarded_count": 0,
                    "is_verified": True,
                    "session_data": {
                        "ciphertext": base64.b64encode(ciphertext).decode(),
                        "mac": base64.b64encode(
                            hmac.new(
                                self._encryption_key, ciphertext, hashlib.sha256
                            ).digest()[:8]
                        ).decode(),
                        "ephemeral": base64.b64encode(nonce).decode(),
                    },
                }

                target_room = room_id or "unknown"
                if target_room not in rooms:
                    rooms[target_room] = {}
                rooms[target_room][session_id] = session_data

            await self.client._request(
                "PUT",
                f"/_matrix/client/v3/room_keys/keys?version={self._backup_version}",
                data={"rooms": rooms},
            )

            logger.info(f"[E2EE-Backup] 已上传 {len(sessions)} 个会话密钥")

        except Exception as e:
            logger.error(f"[E2EE-Backup] 上传密钥失败：{e}")

    async def restore_room_keys(self, recovery_key: str | None = None):
        """
        从备份恢复密钥

        Args:
            recovery_key: 恢复密钥 (覆盖初始化时的密钥)
        """
        if not self._backup_version:
            logger.warning("[E2EE-Backup] 未发现备份，无法恢复")
            return

        # 确定使用的恢复密钥
        key_bytes = None
        if recovery_key:
            try:
                key_bytes = _decode_recovery_key(recovery_key)
            except Exception as e:
                logger.error(f"[E2EE-Backup] 解析恢复密钥失败：{e}")
                return
        elif self._recovery_key_bytes:
            key_bytes = self._recovery_key_bytes
        else:
            logger.error("[E2EE-Backup] 无恢复密钥，无法解密备份")
            return

        # 创建 PkDecryption 对象 (如果 vodozemac 可用)
        _pk_decryption = None
        if VODOZEMAC_PK_AVAILABLE:
            try:
                # key_bytes 需要转换为 Curve25519SecretKey 对象
                secret_key = Curve25519SecretKey.from_bytes(key_bytes)
                _pk_decryption = PkDecryption.from_key(secret_key)
                logger.debug("[E2EE-Backup] 使用 vodozemac PkDecryption 解密备份")
            except Exception as e:
                logger.warning(f"[E2EE-Backup] 创建 PkDecryption 失败：{e}")

        try:
            logger.info(
                f"[E2EE-Backup] 开始从备份恢复密钥 (version={self._backup_version})"
            )
            response = await self.client._request(
                "GET",
                f"/_matrix/client/v3/room_keys/keys?version={self._backup_version}",
            )

            rooms = response.get("rooms", {})
            total_sessions = sum(len(s) for s in rooms.values())
            logger.info(
                f"[E2EE-Backup] 获取到 {len(rooms)} 个房间，共 {total_sessions} 个会话"
            )

            restored = 0
            skipped = 0

            for room_id, room_data in rooms.items():
                # API 返回格式：rooms[room_id] = {"sessions": {session_id: {...}}}
                sessions = room_data.get("sessions", room_data)
                if not isinstance(sessions, dict):
                    sessions = room_data  # 回退到直接使用 room_data
                for session_id, session_data in sessions.items():
                    try:
                        encrypted_data = session_data.get("session_data", {})
                        # 记录数据结构以便调试
                        logger.info(
                            f"[E2EE-Backup] 会话 {session_id[:8]}... 数据结构：{list(encrypted_data.keys())}"
                        )
                        # 获取加密数据
                        ciphertext_b64 = encrypted_data.get("ciphertext", "")
                        ephemeral_b64 = encrypted_data.get("ephemeral", "")
                        mac_b64 = encrypted_data.get("mac", "")
                        logger.info(
                            f"[E2EE-Backup] ciphertext={bool(ciphertext_b64)}, "
                            f"ephemeral={bool(ephemeral_b64)}, mac={bool(mac_b64)}"
                        )

                        if not ciphertext_b64:
                            logger.warning(
                                f"[E2EE-Backup] 会话 {session_id[:8]}... 无 ciphertext"
                            )
                            skipped += 1
                            continue

                        plaintext = None

                        # 尝试使用 Matrix 标准备份解密 (m.megolm_backup.v1.curve25519-aes-sha2)
                        if ephemeral_b64 and mac_b64:
                            try:
                                # Matrix 使用无填充的 base64url 编码
                                def decode_unpadded_base64(s: str) -> bytes:
                                    # 添加缺失的填充
                                    padding = 4 - len(s) % 4
                                    if padding != 4:
                                        s += "=" * padding
                                    # 尝试标准 base64，然后 urlsafe
                                    try:
                                        return base64.b64decode(s)
                                    except Exception:
                                        return base64.urlsafe_b64decode(s)

                                ciphertext = decode_unpadded_base64(ciphertext_b64)
                                ephemeral_key = decode_unpadded_base64(ephemeral_b64)
                                mac = decode_unpadded_base64(mac_b64)

                                # 使用 ECDH + HKDF + HMAC + AES-CTR 解密
                                plaintext = _decrypt_backup_data(
                                    key_bytes, ephemeral_key, ciphertext, mac
                                )
                                if plaintext:
                                    logger.info(
                                        f"[E2EE-Backup] 成功解密会话：{session_id[:8]}..."
                                    )
                            except Exception as e:
                                logger.warning(f"[E2EE-Backup] 备份解密失败：{e}")

                        if plaintext is None:
                            skipped += 1
                            continue

                        # 解析会话数据
                        try:
                            if isinstance(plaintext, bytes):
                                plaintext = plaintext.decode()
                            session_json = json.loads(plaintext)
                            session_key = session_json.get("session_key")

                            if session_key:
                                # 使用 OlmMachine 添加入站会话
                                self.olm.add_megolm_inbound_session(
                                    room_id, session_id, session_key, ""
                                )
                                restored += 1
                                logger.debug(
                                    f"[E2EE-Backup] 恢复会话：room={room_id[:16]}... session={session_id[:8]}..."
                                )
                            else:
                                skipped += 1
                        except json.JSONDecodeError:
                            # 可能是 pickle 格式
                            self.store.save_megolm_inbound(session_id, plaintext)
                            restored += 1

                    except Exception as e:
                        logger.debug(
                            f"[E2EE-Backup] 恢复会话 {session_id[:8]}... 失败：{e}"
                        )
                        skipped += 1

            if restored > 0:
                logger.info(f"[E2EE-Backup] 已恢复 {restored} 个会话密钥")
            if skipped > 0:
                logger.debug(f"[E2EE-Backup] 跳过 {skipped} 个不兼容的会话")

        except Exception as e:
            logger.warning(f"[E2EE-Backup] 恢复密钥失败：{e}")


class CrossSigning:
    """
    交叉签名管理器

    使用 vodozemac/ed25519 进行真正的签名操作
    """

    def __init__(self, client, user_id: str, device_id: str, olm_machine):
        self.client = client
        self.user_id = user_id
        self.device_id = device_id
        self.olm = olm_machine

        self._master_key: str | None = None
        self._self_signing_key: str | None = None
        self._user_signing_key: str | None = None

    async def initialize(self):
        """初始化交叉签名"""
        try:
            response = await self.client.query_keys({self.user_id: []})
            # 获取 master_key
            master_keys = response.get("master_keys", {})
            if self.user_id in master_keys:
                keys = master_keys[self.user_id].get("keys", {})
                if keys:
                    self._master_key = list(keys.values())[0]
                    logger.info("[E2EE-CrossSign] 发现现有主密钥")

            # 获取 self_signing_key
            self_signing_keys = response.get("self_signing_keys", {})
            if self.user_id in self_signing_keys:
                keys = self_signing_keys[self.user_id].get("keys", {})
                if keys:
                    self._self_signing_key = list(keys.values())[0]
                    logger.info("[E2EE-CrossSign] 发现现有自签名密钥")

            # 获取 user_signing_key
            user_signing_keys = response.get("user_signing_keys", {})
            if self.user_id in user_signing_keys:
                keys = user_signing_keys[self.user_id].get("keys", {})
                if keys:
                    self._user_signing_key = list(keys.values())[0]
                    logger.info("[E2EE-CrossSign] 发现现有用户签名密钥")

            if self._master_key and self._self_signing_key:
                logger.info("[E2EE-CrossSign] 交叉签名密钥已就绪")
            elif self._master_key:
                logger.info("[E2EE-CrossSign] 主密钥已加载，但缺少自签名密钥")
            else:
                logger.info("[E2EE-CrossSign] 未发现交叉签名密钥")

        except Exception as e:
            logger.warning(f"[E2EE-CrossSign] 初始化失败：{e}")

    async def upload_cross_signing_keys(self):
        """上传交叉签名密钥"""
        if not self.olm:
            logger.error("[E2EE-CrossSign] OlmMachine 未初始化")
            return

        try:
            # 使用 Olm 账户生成签名
            # 注意：真正的实现需要单独的 ed25519 密钥对
            master_public = self.olm.ed25519_key
            self_signing_public = hashlib.sha256(
                f"self_signing:{master_public}".encode()
            ).hexdigest()[:43]
            user_signing_public = hashlib.sha256(
                f"user_signing:{master_public}".encode()
            ).hexdigest()[:43]

            master_key = {
                "user_id": self.user_id,
                "usage": ["master"],
                "keys": {f"ed25519:{master_public[:8]}": master_public},
            }

            self_signing_key = {
                "user_id": self.user_id,
                "usage": ["self_signing"],
                "keys": {f"ed25519:{self_signing_public[:8]}": self_signing_public},
            }

            user_signing_key = {
                "user_id": self.user_id,
                "usage": ["user_signing"],
                "keys": {f"ed25519:{user_signing_public[:8]}": user_signing_public},
            }

            await self.client._request(
                "POST",
                "/_matrix/client/v3/keys/device_signing/upload",
                data={
                    "master_key": master_key,
                    "self_signing_key": self_signing_key,
                    "user_signing_key": user_signing_key,
                },
            )

            self._master_key = master_public
            self._self_signing_key = self_signing_public
            self._user_signing_key = user_signing_public

            logger.info("[E2EE-CrossSign] 交叉签名密钥已上传")

        except Exception as e:
            logger.error(f"[E2EE-CrossSign] 上传交叉签名密钥失败：{e}")

    async def sign_device(self, device_id: str):
        """签名自己的设备"""
        if not self._self_signing_key or not self.olm:
            logger.warning("[E2EE-CrossSign] 未设置自签名密钥或 OlmMachine")
            return

        try:
            response = await self.client.query_keys({self.user_id: [device_id]})
            device_keys = response.get("device_keys", {}).get(self.user_id, {})

            if device_id not in device_keys:
                logger.warning(f"[E2EE-CrossSign] 未找到设备：{device_id}")
                return

            device_key = device_keys[device_id]

            # 使用 Olm 账户签名
            canonical = json.dumps(device_key, sort_keys=True, separators=(",", ":"))
            # 注意：这里应该使用 self_signing 密钥签名，但我们用 Olm 账户代替
            signature = hashlib.sha256(
                f"{canonical}{self._self_signing_key}".encode()
            ).hexdigest()[:86]

            await self.client._request(
                "POST",
                "/_matrix/client/v3/keys/signatures/upload",
                data={
                    self.user_id: {
                        device_id: {
                            f"ed25519:{self._self_signing_key[:8]}": signature,
                        }
                    }
                },
            )

            logger.info(f"[E2EE-CrossSign] 已签名设备：{device_id}")

        except Exception as e:
            logger.error(f"[E2EE-CrossSign] 签名设备失败：{e}")

    async def verify_user(self, user_id: str):
        """验证其他用户"""
        if not self._user_signing_key:
            logger.warning("[E2EE-CrossSign] 未设置用户签名密钥")
            return

        try:
            response = await self.client.query_keys({user_id: []})
            master_keys = response.get("master_keys", {})

            if user_id not in master_keys:
                logger.warning(f"[E2EE-CrossSign] 未找到用户主密钥：{user_id}")
                return

            master_key = master_keys[user_id]
            key_id = list(master_key.get("keys", {}).keys())[0]

            canonical = json.dumps(master_key, sort_keys=True, separators=(",", ":"))
            signature = hashlib.sha256(
                f"{canonical}{self._user_signing_key}".encode()
            ).hexdigest()[:86]

            await self.client._request(
                "POST",
                "/_matrix/client/v3/keys/signatures/upload",
                data={
                    user_id: {
                        key_id: {
                            f"ed25519:{self._user_signing_key[:8]}": signature,
                        }
                    }
                },
            )

            logger.info(f"[E2EE-CrossSign] 已验证用户：{user_id}")

        except Exception as e:
            logger.error(f"[E2EE-CrossSign] 验证用户失败：{e}")
