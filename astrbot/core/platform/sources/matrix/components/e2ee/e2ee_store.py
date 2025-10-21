"""
Matrix E2EE 密钥存储和管理模块
使用 vodozemac 库实现端到端加密支持
"""

import json
from pathlib import Path
from typing import Optional, Dict, Any, List
from astrbot import logger

try:
    from vodozemac import Account
except ImportError:
    logger.warning("vodozemac not installed, E2EE support disabled")
    Account = None


class MatrixE2EEStore:
    """Matrix E2EE 密钥存储和管理"""

    def __init__(self, store_path: str, user_id: str, device_id: str):
        """
        初始化 E2EE 存储

        Args:
            store_path: 存储路径
            user_id: Matrix 用户 ID
            device_id: 设备 ID
        """
        self.store_path = Path(store_path)
        self.user_id = user_id
        self.device_id = device_id
        self.store_path.mkdir(parents=True, exist_ok=True)

        self.account_file = self.store_path / "account.pickle"
        self.device_keys_file = self.store_path / "device_keys.json"
        self.sessions_file = self.store_path / "sessions.json"
        self.verified_devices_file = self.store_path / "verified_devices.json"

        self.account: Optional[Account] = None
        self.device_keys: Dict[str, Any] = {}
        self.sessions: Dict[str, Any] = {}
        self.verified_devices: Dict[str, set] = {}

    async def initialize(self):
        """初始化 E2EE 存储，加载或创建账户"""
        if not Account:
            logger.warning("vodozemac not available, E2EE disabled")
            return False

        try:
            # 尝试加载现有账户
            if self.account_file.exists():
                await self._load_account()
                logger.info(f"Loaded existing E2EE account for {self.user_id}")
            else:
                # 创建新账户
                self.account = Account()
                await self._save_account()
                logger.info(f"Created new E2EE account for {self.user_id}")

            # 加载其他数据
            self._load_device_keys()
            self._load_sessions()
            self._load_verified_devices()

            return True
        except Exception as e:
            logger.error(f"Failed to initialize E2EE store: {e}")
            return False

    async def _load_account(self):
        """从文件加载账户"""
        try:
            with open(self.account_file, "rb") as f:
                pickle_data = f.read()
            # vodozemac 的 from_pickle 接受密钥作为字节和字符串形式的 pickle 数据
            pickle_key = bytes([0] * 32)  # 32 字节的密钥
            # 如果是字节，需要解码为字符串
            if isinstance(pickle_data, bytes):
                pickle_data = pickle_data.decode()
            self.account = Account.from_pickle(pickle_data, pickle_key)
        except Exception as e:
            logger.error(f"Failed to load account: {e}")
            raise

    async def _save_account(self):
        """保存账户到文件"""
        try:
            if not self.account:
                return
            # vodozemac 的 pickle 接受密钥作为字节，返回字符串
            pickle_key = bytes([0] * 32)  # 32 字节的密钥
            pickle_data = self.account.pickle(pickle_key)
            # pickle_data 是字符串，需要编码为字节
            with open(self.account_file, "wb") as f:
                f.write(
                    pickle_data.encode()
                    if isinstance(pickle_data, str)
                    else pickle_data
                )
        except Exception as e:
            logger.error(f"Failed to save account: {e}")

    def _load_device_keys(self):
        """加载设备密钥"""
        try:
            if self.device_keys_file.exists():
                with open(self.device_keys_file, "r") as f:
                    self.device_keys = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load device keys: {e}")

    def _save_device_keys(self):
        """保存设备密钥"""
        try:
            with open(self.device_keys_file, "w") as f:
                json.dump(self.device_keys, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save device keys: {e}")

    def _load_sessions(self):
        """加载会话"""
        try:
            if self.sessions_file.exists():
                with open(self.sessions_file, "r") as f:
                    self.sessions = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load sessions: {e}")

    def _save_sessions(self):
        """保存会话"""
        try:
            with open(self.sessions_file, "w") as f:
                json.dump(self.sessions, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save sessions: {e}")

    def _load_verified_devices(self):
        """加载已验证的设备"""
        try:
            if self.verified_devices_file.exists():
                with open(self.verified_devices_file, "r") as f:
                    data = json.load(f)
                    # 转换列表回集合
                    self.verified_devices = {
                        user_id: set(devices) for user_id, devices in data.items()
                    }
        except Exception as e:
            logger.error(f"Failed to load verified devices: {e}")

    def _save_verified_devices(self):
        """保存已验证的设备"""
        try:
            # 转换集合为列表以便 JSON 序列化
            data = {
                user_id: list(devices)
                for user_id, devices in self.verified_devices.items()
            }
            with open(self.verified_devices_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save verified devices: {e}")

    def get_identity_keys(self) -> Optional[Dict[str, str]]:
        """获取身份密钥"""
        if not self.account:
            return None
        try:
            curve_key = self.account.curve25519_key
            ed_key = self.account.ed25519_key
            return {
                "curve25519": curve_key.to_base64(),
                "ed25519": ed_key.to_base64(),
            }
        except Exception as e:
            logger.error(f"Failed to get identity keys: {e}")
            return None

    def get_one_time_keys(self, count: int = 10) -> Optional[Dict[str, str]]:
        """获取一次性密钥"""
        if not self.account:
            return None
        try:
            self.account.generate_one_time_keys(count)
            # one_time_keys 是一个属性，不是方法
            keys = self.account.one_time_keys
            # vodozemac 返回的是 dict，其中值是 Curve25519PublicKey 对象
            result = {}
            for key_id, key_obj in keys.items():
                result[key_id] = key_obj.to_base64()
            return result
        except Exception as e:
            logger.error(f"Failed to get one-time keys: {e}")
            return None

    def mark_keys_as_published(self):
        """标记密钥为已发布"""
        if self.account:
            try:
                self.account.mark_keys_as_published()
            except Exception as e:
                logger.error(f"Failed to mark keys as published: {e}")

    def add_verified_device(self, user_id: str, device_id: str):
        """添加已验证的设备"""
        if user_id not in self.verified_devices:
            self.verified_devices[user_id] = set()
        self.verified_devices[user_id].add(device_id)
        self._save_verified_devices()

    def is_device_verified(self, user_id: str, device_id: str) -> bool:
        """检查设备是否已验证"""
        return (
            user_id in self.verified_devices
            and device_id in self.verified_devices[user_id]
        )

    def get_verified_devices(self, user_id: str) -> List[str]:
        """获取用户的已验证设备列表"""
        return list(self.verified_devices.get(user_id, set()))

    async def close(self):
        """关闭存储，保存所有数据"""
        await self._save_account()
        self._save_device_keys()
        self._save_sessions()
        self._save_verified_devices()
