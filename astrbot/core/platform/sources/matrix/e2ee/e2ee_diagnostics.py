"""
E2EE 诊断工具 - 帮助诊断端到端加密问题
"""

import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger("astrbot")


def _log(level: str, message: str):
    """统一的日志输出"""
    extra = {"plugin_tag": "matrix", "short_levelname": level.upper()[:4]}
    getattr(logger, level)(message, extra=extra)


class MatrixE2EEDiagnostics:
    """E2EE 诊断工具"""

    def __init__(self, client, e2ee_manager, user_id: str, device_id: str):
        """
        初始化诊断工具

        Args:
            client: MatrixHTTPClient 实例
            e2ee_manager: MatrixE2EEManager 实例
            user_id: 当前用户 ID
            device_id: 当前设备 ID
        """
        self.client = client
        self.e2ee_manager = e2ee_manager
        self.user_id = user_id
        self.device_id = device_id

    async def run_full_diagnostics(self) -> Dict[str, Any]:
        """
        运行完整的 E2EE 诊断

        Returns:
            诊断结果字典
        """
        _log("info", "🔍 Running E2EE diagnostics...")

        results = {
            "devices": await self.diagnose_devices(),
            "sessions": self.diagnose_sessions(),
            "verified_devices": self.diagnose_verified_devices(),
            "group_sessions": self.diagnose_group_sessions(),
        }

        # 生成诊断报告
        self.print_diagnostics_report(results)

        return results

    async def diagnose_devices(self) -> Dict[str, Any]:
        """诊断设备状态"""
        try:
            # 获取设备列表
            response = await self.client.get_devices()
            devices = response.get("devices", [])

            # 查询设备密钥
            device_ids = [d.get("device_id") for d in devices if d.get("device_id")]
            keys_response = await self.client.query_keys(
                device_keys={self.user_id: device_ids}
            )
            device_keys = keys_response.get("device_keys", {}).get(self.user_id, {})

            # 分析设备
            devices_with_keys = []
            devices_without_keys = []

            for device in devices:
                device_id = device.get("device_id")
                device_info = {
                    "device_id": device_id,
                    "display_name": device.get("display_name", "Unknown"),
                    "last_seen_ts": device.get("last_seen_ts"),
                    "is_current": device_id == self.device_id,
                }

                if device_id in device_keys:
                    device_info["has_keys"] = True
                    device_info["keys"] = device_keys[device_id].get("keys", {})
                    devices_with_keys.append(device_info)
                else:
                    device_info["has_keys"] = False
                    devices_without_keys.append(device_info)

            return {
                "total": len(devices),
                "with_keys": len(devices_with_keys),
                "without_keys": len(devices_without_keys),
                "devices_with_keys": devices_with_keys,
                "devices_without_keys": devices_without_keys,
            }

        except Exception as e:
            _log("error", f"Failed to diagnose devices: {e}")
            return {"error": str(e)}

    def diagnose_sessions(self) -> Dict[str, Any]:
        """诊断 Olm 会话状态"""
        try:
            sessions = self.e2ee_manager.crypto.sessions
            session_count = len(sessions)

            session_details = []
            for session_key, session in sessions.items():
                user_id, device_id = session_key.split(":", 1)
                session_details.append(
                    {
                        "user_id": user_id,
                        "device_id": device_id,
                        "session_id": session.session_id(),
                    }
                )

            return {
                "total": session_count,
                "sessions": session_details,
            }

        except Exception as e:
            _log("error", f"Failed to diagnose sessions: {e}")
            return {"error": str(e)}

    def diagnose_verified_devices(self) -> Dict[str, Any]:
        """诊断已验证设备"""
        try:
            verified_devices = self.e2ee_manager.store.get_verified_devices(
                self.user_id
            )

            # 检查哪些已验证设备有 Olm 会话
            devices_with_sessions = []
            devices_without_sessions = []

            for device_id in verified_devices:
                if self.e2ee_manager.crypto.has_olm_session(self.user_id, device_id):
                    devices_with_sessions.append(device_id)
                else:
                    devices_without_sessions.append(device_id)

            return {
                "total": len(verified_devices),
                "with_sessions": len(devices_with_sessions),
                "without_sessions": len(devices_without_sessions),
                "devices_with_sessions": devices_with_sessions,
                "devices_without_sessions": devices_without_sessions,
            }

        except Exception as e:
            _log("error", f"Failed to diagnose verified devices: {e}")
            return {"error": str(e)}

    def diagnose_group_sessions(self) -> Dict[str, Any]:
        """诊断群组会话（Megolm）"""
        try:
            # 获取所有群组会话
            group_sessions = self.e2ee_manager.crypto.inbound_group_sessions
            session_count = len(group_sessions)

            # 按房间分组
            sessions_by_room = {}
            for session_id, session in group_sessions.items():
                # 从 store 中获取房间信息
                # 注意：这里需要遍历 store 的群组会话来获取房间 ID
                pass

            return {
                "total": session_count,
                "sessions": list(group_sessions.keys()),
            }

        except Exception as e:
            _log("error", f"Failed to diagnose group sessions: {e}")
            return {"error": str(e)}

    def print_diagnostics_report(self, results: Dict[str, Any]):
        """打印诊断报告"""
        _log("info", "")
        _log("info", "=" * 60)
        _log("info", "📊 E2EE Diagnostics Report")
        _log("info", "=" * 60)

        # 设备诊断
        devices = results.get("devices", {})
        if "error" not in devices:
            _log("info", "")
            _log("info", "🔧 Devices:")
            _log("info", f"  Total devices: {devices.get('total', 0)}")
            _log("info", f"  Devices with E2EE keys: {devices.get('with_keys', 0)}")
            _log(
                "info", f"  Devices without E2EE keys: {devices.get('without_keys', 0)}"
            )

            if devices.get("devices_without_keys"):
                _log("info", "")
                _log("warning", "  ⚠️  Devices without E2EE keys:")
                for device in devices["devices_without_keys"]:
                    _log(
                        "warning",
                        f"    - {device['device_id']} ({device['display_name']})",
                    )
                _log("info", "")
                _log(
                    "info",
                    "  💡 These devices cannot participate in E2EE communication.",
                )
                _log(
                    "info",
                    "     They may be using clients that don't support E2EE (e.g., some web clients).",
                )
                _log(
                    "info",
                    "     Consider logging in with Element or another E2EE-capable client.",
                )

        # Olm 会话诊断
        sessions = results.get("sessions", {})
        if "error" not in sessions:
            _log("info", "")
            _log("info", "🔐 Olm Sessions:")
            _log("info", f"  Total sessions: {sessions.get('total', 0)}")

            if sessions.get("total", 0) == 0:
                _log("warning", "  ⚠️  No Olm sessions established!")
                _log(
                    "info",
                    "     Cannot send encrypted messages or request room keys.",
                )
            else:
                for session in sessions.get("sessions", []):
                    _log(
                        "info",
                        f"    - {session['device_id']} (session: {session['session_id'][:16]}...)",
                    )

        # 已验证设备诊断
        verified = results.get("verified_devices", {})
        if "error" not in verified:
            _log("info", "")
            _log("info", "✅ Verified Devices:")
            _log("info", f"  Total verified: {verified.get('total', 0)}")
            _log(
                "info",
                f"  With Olm sessions: {verified.get('with_sessions', 0)}",
            )
            _log(
                "info",
                f"  Without Olm sessions: {verified.get('without_sessions', 0)}",
            )

            if verified.get("devices_without_sessions"):
                _log("info", "")
                _log("warning", "  ⚠️  Verified devices without Olm sessions:")
                for device_id in verified["devices_without_sessions"]:
                    _log("warning", f"    - {device_id}")
                _log("info", "")
                _log(
                    "info",
                    "  💡 These devices are marked as verified but have no encryption sessions.",
                )
                _log(
                    "info",
                    "     This usually means they don't support E2EE or haven't uploaded keys.",
                )
                _log(
                    "info",
                    "     You cannot request room keys from these devices.",
                )

        # 群组会话诊断
        group_sessions = results.get("group_sessions", {})
        if "error" not in group_sessions:
            _log("info", "")
            _log("info", "🔑 Group Sessions (Megolm):")
            _log("info", f"  Total sessions: {group_sessions.get('total', 0)}")

            if group_sessions.get("total", 0) == 0:
                _log("warning", "  ⚠️  No group sessions available!")
                _log("info", "     Cannot decrypt encrypted room messages.")
                _log("info", "")
                _log("info", "  💡 To receive group sessions, you need:")
                _log(
                    "info",
                    "     1. At least one other device with E2EE support and Olm session",
                )
                _log(
                    "info",
                    "     2. That device must have the room keys and share them with you",
                )
                _log(
                    "info",
                    "     3. Or join the encrypted room and receive new messages",
                )

        _log("info", "")
        _log("info", "=" * 60)
        _log("info", "")

