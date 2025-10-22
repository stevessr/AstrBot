"""
Matrix E2EE 自动设置模块
自动获取用户设备列表、交换密钥、验证设备
"""

import asyncio
import logging
from typing import Optional, Dict, Any, List, Set
from datetime import datetime

logger = logging.getLogger("astrbot.matrix.e2ee.auto_setup")

# 导入诊断工具
try:
    from .e2ee_diagnostics import MatrixE2EEDiagnostics
    DIAGNOSTICS_AVAILABLE = True
except ImportError:
    DIAGNOSTICS_AVAILABLE = False


def _log(level: str, msg: str):
    """Helper function to log messages with required AstrBot extra fields"""
    extra = {"plugin_tag": "matrix", "short_levelname": level[:4].upper()}
    if level == "info":
        logger.info(msg, extra=extra)
    elif level == "error":
        logger.error(msg, extra=extra)
    elif level == "warning":
        logger.warning(msg, extra=extra)
    elif level == "debug":
        logger.debug(msg, extra=extra)


class MatrixE2EEAutoSetup:
    """Matrix E2EE 自动设置管理器"""

    def __init__(self, client, e2ee_manager, user_id: str, device_id: str):
        """
        初始化自动设置管理器

        Args:
            client: Matrix HTTP 客户端
            e2ee_manager: E2EE 管理器实例
            user_id: 当前用户 ID
            device_id: 当前设备 ID
        """
        self.client = client
        self.e2ee_manager = e2ee_manager
        self.user_id = user_id
        self.device_id = device_id
        
        # 跟踪已处理的设备
        self.known_devices: Set[str] = set()
        self.verified_devices: Set[str] = set()
        
        # 自动验证配置
        self.auto_verify_own_devices = True  # 自动验证自己的其他设备
        self.auto_accept_verifications = True  # 自动接受验证请求（谨慎使用）

    async def setup_e2ee(self) -> bool:
        """
        执行完整的 E2EE 自动设置流程
        
        Returns:
            是否成功设置
        """
        try:
            _log("info", "🔐 Starting automatic E2EE setup...")
            
            # 1. 获取当前用户的所有设备
            devices = await self.get_user_devices()
            if not devices:
                _log("warning", "No devices found for current user")
                return False
            
            _log("info", f"Found {len(devices)} device(s) for user {self.user_id}")
            
            # 2. 查询所有设备的密钥
            device_keys = await self.query_device_keys(devices)

            # 3. 为有密钥的设备建立 Olm 会话
            sessions_from_keys = 0
            if device_keys:
                sessions_from_keys = await self.establish_olm_sessions(device_keys)
            else:
                _log("warning", "No device keys returned from query")

            # 4. 尝试为没有密钥的设备直接声明一次性密钥
            # 这可以处理使用 cross-signing 的设备
            sessions_from_claim = await self.try_claim_keys_for_all_devices(devices)

            total_sessions = sessions_from_keys + sessions_from_claim
            _log("info", f"📊 Total Olm sessions established: {total_sessions}")

            # 5. 如果启用了自动验证，验证自己的设备
            if self.auto_verify_own_devices:
                await self.auto_verify_own_devices_func(devices)

            _log("info", "✅ E2EE automatic setup completed successfully")

            # 运行诊断以显示当前状态
            if DIAGNOSTICS_AVAILABLE:
                try:
                    diagnostics = MatrixE2EEDiagnostics(
                        self.client, self.e2ee_manager, self.user_id, self.device_id
                    )
                    await diagnostics.run_full_diagnostics()
                except Exception as diag_err:
                    _log("warning", f"Failed to run diagnostics: {diag_err}")

            return True

        except Exception as e:
            _log("error", f"❌ Failed to setup E2EE automatically: {e}")
            return False

    async def get_user_devices(self) -> List[Dict[str, Any]]:
        """
        获取当前用户的所有设备列表
        
        Returns:
            设备列表
        """
        try:
            response = await self.client.get_devices()
            devices = response.get("devices", [])
            
            for device in devices:
                device_id = device.get("device_id")
                display_name = device.get("display_name", "Unknown")
                last_seen_ts = device.get("last_seen_ts")
                
                if device_id:
                    self.known_devices.add(device_id)
                    
                    # 格式化最后在线时间
                    last_seen = "Never"
                    if last_seen_ts:
                        last_seen = datetime.fromtimestamp(last_seen_ts / 1000).strftime("%Y-%m-%d %H:%M:%S")
                    
                    is_current = " (current)" if device_id == self.device_id else ""
                    _log("info", f"  📱 Device: {device_id}{is_current}")
                    _log("info", f"     Name: {display_name}")
                    _log("info", f"     Last seen: {last_seen}")
            
            return devices
            
        except Exception as e:
            _log("error", f"Failed to get user devices: {e}")
            return []

    async def query_device_keys(self, devices: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        查询设备的加密密钥
        
        Args:
            devices: 设备列表
            
        Returns:
            设备密钥信息
        """
        try:
            # 构建查询请求
            device_ids = [d.get("device_id") for d in devices if d.get("device_id")]
            
            if not device_ids:
                return {}
            
            _log("info", f"🔍 Querying keys for {len(device_ids)} device(s)...")
            
            # 查询密钥
            response = await self.client.query_keys(
                device_keys={self.user_id: device_ids}
            )

            # 调试：打印完整响应
            import json
            _log("debug", f"Keys query response: {json.dumps(response, indent=2)}")

            device_keys = response.get("device_keys", {}).get(self.user_id, {})

            _log("info", f"✅ Retrieved keys for {len(device_keys)} device(s)")

            # 检查哪些设备没有上传密钥
            devices_without_keys = set(device_ids) - set(device_keys.keys())
            if devices_without_keys:
                _log("warning", f"⚠️  {len(devices_without_keys)} device(s) have not uploaded E2EE keys:")
                for device_id in devices_without_keys:
                    # 查找设备名称
                    device_name = "Unknown"
                    for device in devices:
                        if device.get("device_id") == device_id:
                            device_name = device.get("display_name", "Unknown")
                            break
                    _log("warning", f"    - {device_id} ({device_name})")
                _log("info", "💡 Possible reasons:")
                _log("info", "   1. These devices haven't uploaded keys via /keys/upload API")
                _log("info", "   2. They may be using cross-signing instead of device keys")
                _log("info", "   3. Try requesting room keys directly - they might still work!")

            # 显示密钥信息
            for device_id, keys in device_keys.items():
                algorithms = keys.get("algorithms", [])
                key_dict = keys.get("keys", {})

                curve25519_key = key_dict.get(f"curve25519:{device_id}", "N/A")
                ed25519_key = key_dict.get(f"ed25519:{device_id}", "N/A")

                _log("debug", f"  Device {device_id}:")
                _log("debug", f"    Algorithms: {', '.join(algorithms)}")
                _log("debug", f"    Curve25519: {curve25519_key[:16]}...")
                _log("debug", f"    Ed25519: {ed25519_key[:16]}...")

            return device_keys
            
        except Exception as e:
            _log("error", f"Failed to query device keys: {e}")
            return {}

    async def establish_olm_sessions(self, device_keys: Dict[str, Any]) -> int:
        """
        为所有设备建立 Olm 会话
        
        Args:
            device_keys: 设备密钥信息
            
        Returns:
            成功建立的会话数量
        """
        try:
            sessions_created = 0
            
            for device_id, keys in device_keys.items():
                # 跳过当前设备
                if device_id == self.device_id:
                    continue
                
                # 检查是否已有会话
                if self.e2ee_manager.crypto.has_olm_session(self.user_id, device_id):
                    _log("debug", f"Olm session already exists for device {device_id}")
                    continue
                
                # 获取设备的 Curve25519 密钥
                key_dict = keys.get("keys", {})
                identity_key = key_dict.get(f"curve25519:{device_id}")
                
                if not identity_key:
                    _log("warning", f"No Curve25519 key found for device {device_id}")
                    continue
                
                # 声明一次性密钥
                _log("info", f"🔑 Claiming one-time key for device {device_id}...")
                
                try:
                    claim_response = await self.client.claim_keys(
                        one_time_keys={
                            self.user_id: {
                                device_id: "signed_curve25519"
                            }
                        }
                    )
                    
                    # 提取一次性密钥
                    one_time_keys = claim_response.get("one_time_keys", {}).get(
                        self.user_id, {}
                    ).get(device_id, {})
                    
                    if not one_time_keys:
                        _log("warning", f"No one-time keys available for device {device_id}")
                        continue
                    
                    # 获取第一个可用的一次性密钥
                    otk_id, otk_data = next(iter(one_time_keys.items()))
                    one_time_key = otk_data.get("key") if isinstance(otk_data, dict) else otk_data
                    
                    # 创建 Olm 会话
                    _log("info", f"🔗 Creating Olm session with device {device_id}...")

                    success = self.e2ee_manager.crypto.create_outbound_session(
                        user_id=self.user_id,
                        device_id=device_id,
                        identity_key=identity_key,
                        one_time_key=one_time_key
                    )

                    if success:
                        sessions_created += 1
                        _log("info", f"✅ Olm session created for device {device_id}")
                    else:
                        _log("error", f"Failed to create Olm session for device {device_id}")
                        
                except Exception as e:
                    _log("error", f"Failed to establish session with device {device_id}: {e}")
                    continue
            
            _log("info", f"✅ Created {sessions_created} Olm session(s)")
            return sessions_created

        except Exception as e:
            _log("error", f"Failed to establish Olm sessions: {e}")
            return 0

    async def try_claim_keys_for_all_devices(self, devices: List[Dict[str, Any]]) -> int:
        """
        尝试为所有设备声明一次性密钥（即使 /keys/query 返回空）

        这个方法用于处理使用 cross-signing 的设备，它们可能没有通过
        /keys/query 返回密钥，但仍然有一次性密钥可用。

        Args:
            devices: 设备列表

        Returns:
            成功创建的会话数量
        """
        sessions_created = 0

        try:
            _log("info", "🔄 Attempting to claim keys for devices without uploaded keys...")

            for device in devices:
                device_id = device.get("device_id")

                # 跳过当前设备
                if device_id == self.device_id:
                    continue

                # 跳过已有会话的设备
                if self.e2ee_manager.crypto.has_olm_session(self.user_id, device_id):
                    continue

                try:
                    _log("info", f"🔑 Trying to claim one-time key for {device_id}...")

                    # 尝试声明一次性密钥
                    claim_response = await self.client.claim_keys(
                        one_time_keys={
                            self.user_id: {
                                device_id: "signed_curve25519"
                            }
                        }
                    )

                    # 检查是否成功获取到一次性密钥
                    one_time_keys = claim_response.get("one_time_keys", {}).get(
                        self.user_id, {}
                    ).get(device_id, {})

                    if not one_time_keys:
                        _log("debug", f"No one-time keys available for {device_id}")
                        continue

                    # 获取第一个可用的一次性密钥
                    otk_id, otk_data = next(iter(one_time_keys.items()))
                    one_time_key = otk_data.get("key") if isinstance(otk_data, dict) else otk_data

                    # 现在需要获取设备的 identity key
                    # 尝试从 claim 响应中获取
                    if "failures" in claim_response:
                        _log("debug", f"Claim failures: {claim_response['failures']}")

                    # 再次查询这个特定设备的密钥
                    query_response = await self.client.query_keys(
                        device_keys={self.user_id: [device_id]}
                    )

                    device_keys = query_response.get("device_keys", {}).get(
                        self.user_id, {}
                    ).get(device_id, {})

                    if not device_keys:
                        _log("warning", f"Could not get identity key for {device_id} even after claiming OTK")
                        continue

                    identity_key = device_keys.get("keys", {}).get(f"curve25519:{device_id}")

                    if not identity_key:
                        _log("warning", f"No Curve25519 key in device keys for {device_id}")
                        continue

                    # 创建 Olm 会话
                    _log("info", f"🔗 Creating Olm session with {device_id}...")

                    success = self.e2ee_manager.crypto.create_outbound_session(
                        user_id=self.user_id,
                        device_id=device_id,
                        identity_key=identity_key,
                        one_time_key=one_time_key
                    )

                    if success:
                        sessions_created += 1
                        _log("info", f"✅ Successfully created Olm session with {device_id}!")
                    else:
                        _log("error", f"Failed to create Olm session with {device_id}")

                except Exception as e:
                    _log("debug", f"Could not establish session with {device_id}: {e}")
                    continue

            if sessions_created > 0:
                _log("info", f"✅ Created {sessions_created} additional Olm session(s) via direct claim")
            else:
                _log("info", "ℹ️  No additional sessions could be established")

            return sessions_created

        except Exception as e:
            _log("error", f"Failed to claim keys for devices: {e}")
            return 0

    async def auto_verify_own_devices_func(self, devices: List[Dict[str, Any]]):
        """
        自动验证自己的其他设备

        Args:
            devices: 设备列表
        """
        try:
            _log("info", "🔐 Auto-verifying own devices...")

            verified_count = 0
            for device in devices:
                device_id = device.get("device_id")

                # 跳过当前设备
                if device_id == self.device_id:
                    continue

                # 跳过已验证的设备
                if device_id in self.verified_devices:
                    continue

                # 检查是否已在 store 中标记为已验证
                if self.e2ee_manager.store.is_device_verified(self.user_id, device_id):
                    self.verified_devices.add(device_id)
                    continue

                # 标记为已验证（在实际应用中，这里应该进行真正的验证）
                # 对于自己的设备，可以使用交叉签名或其他自动验证机制
                self.e2ee_manager.store.add_verified_device(self.user_id, device_id)
                self.verified_devices.add(device_id)
                verified_count += 1
                _log("info", f"✅ Auto-verified device {device_id}")

            if verified_count > 0:
                _log("info", f"✅ Auto-verified {verified_count} device(s)")
            else:
                _log("info", "ℹ️  All devices were already verified")

        except Exception as e:
            _log("error", f"Failed to auto-verify devices: {e}")

    async def handle_verification_request(
        self, sender_user_id: str, sender_device_id: str, transaction_id: str
    ) -> bool:
        """
        处理收到的验证请求
        
        Args:
            sender_user_id: 发送者用户 ID
            sender_device_id: 发送者设备 ID
            transaction_id: 事务 ID
            
        Returns:
            是否接受验证
        """
        try:
            # 如果是自己的设备且启用了自动验证
            if sender_user_id == self.user_id and self.auto_verify_own_devices:
                _log("info", f"Auto-accepting verification from own device {sender_device_id}")
                return True
            
            # 如果启用了自动接受所有验证
            if self.auto_accept_verifications:
                _log("warning", f"Auto-accepting verification from {sender_user_id}:{sender_device_id}")
                return True
            
            # 否则需要手动确认
            _log("info", f"Verification request from {sender_user_id}:{sender_device_id} requires manual confirmation")
            return False
            
        except Exception as e:
            _log("error", f"Failed to handle verification request: {e}")
            return False

