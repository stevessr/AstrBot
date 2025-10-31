"""
Matrix E2EE 命令注册模块
提供命令行接口用于 E2EE 管理
"""

from typing import Callable, Dict
from astrbot import logger


class MatrixE2EECommands:
    """Matrix E2EE 命令处理器"""

    def __init__(self, e2ee_manager):
        """
        初始化命令处理器

        Args:
            e2ee_manager: E2EE 管理器实例
        """
        self.e2ee_manager = e2ee_manager
        self.commands: Dict[str, Callable] = {}
        self._register_commands()

    def _register_commands(self):
        """注册所有命令"""
        self.commands = {
            "verify": self.cmd_verify,
            "accept": self.cmd_accept,
            "sas": self.cmd_sas,
            "confirm": self.cmd_confirm,
            "complete": self.cmd_complete,
            "cancel": self.cmd_cancel,
            "status": self.cmd_status,
            "devices": self.cmd_devices,
            "keys": self.cmd_keys,
            "help": self.cmd_help,
        }

    async def execute(self, command: str, args: list) -> str:
        """
        执行命令

        Args:
            command: 命令名称
            args: 命令参数

        Returns:
            命令执行结果
        """
        if command not in self.commands:
            return f"未知命令：{command}\n使用 'help' 查看可用命令"

        try:
            return await self.commands[command](args)
        except Exception as e:
            logger.error(f"Error executing command {command}: {e}")
            return f"执行命令失败：{str(e)}"

    async def cmd_verify(self, args: list) -> str:
        """启动设备验证"""
        if len(args) < 2:
            return "用法：verify <user_id> <device_id>"

        user_id = args[0]
        device_id = args[1]

        verification_id = self.e2ee_manager.start_device_verification(
            user_id, device_id
        )
        if not verification_id:
            return "启动验证失败"

        return (
            f"✓ 已启动验证会话\n"
            f"验证 ID: {verification_id}\n"
            f"正在与 {user_id}:{device_id} 进行验证\n"
            f"请等待对方接受验证请求"
        )

    async def cmd_accept(self, args: list) -> str:
        """接受设备验证"""
        if len(args) < 1:
            return "用法：accept <verification_id>"

        verification_id = args[0]

        if not self.e2ee_manager.accept_device_verification(verification_id):
            return "接受验证失败"

        return "✓ 已接受验证请求"

    async def cmd_sas(self, args: list) -> str:
        """获取 SAS 验证码"""
        if len(args) < 1:
            return "用法：sas <verification_id>"

        verification_id = args[0]

        sas_code = self.e2ee_manager.get_sas_code(verification_id)
        if not sas_code:
            return "获取 SAS 码失败"

        return (
            f"SAS 验证码：{sas_code}\n"
            f"请与对方比对此验证码\n"
            f"如果相同，请输入：confirm {verification_id} {sas_code}"
        )

    async def cmd_confirm(self, args: list) -> str:
        """确认 SAS 验证码"""
        if len(args) < 2:
            return "用法：confirm <verification_id> <sas_code>"

        verification_id = args[0]
        sas_code = args[1]

        if not self.e2ee_manager.confirm_sas_code(verification_id, sas_code):
            return "✗ SAS 码不匹配，验证失败"

        return "✓ SAS 码匹配，正在完成验证..."

    async def cmd_complete(self, args: list) -> str:
        """完成设备验证"""
        if len(args) < 1:
            return "用法：complete <verification_id>"

        verification_id = args[0]

        if not self.e2ee_manager.complete_device_verification(verification_id):
            return "完成验证失败"

        return "✓ 设备验证完成，设备已标记为已验证"

    async def cmd_cancel(self, args: list) -> str:
        """取消设备验证"""
        if len(args) < 1:
            return "用法：cancel <verification_id> [reason]"

        verification_id = args[0]
        reason = " ".join(args[1:]) if len(args) > 1 else "用户取消"

        if not self.e2ee_manager.cancel_device_verification(verification_id, reason):
            return "取消验证失败"

        return f"✓ 已取消验证：{reason}"

    async def cmd_status(self, args: list) -> str:
        """查看验证状态"""
        if len(args) >= 1:
            # 查看特定验证的状态
            verification_id = args[0]
            status = self.e2ee_manager.get_verification_status(verification_id)
            if not status:
                return "验证会话不存在"

            result = f"验证 ID: {verification_id}\n"
            result += f"状态：{status.get('state', 'unknown')}\n"
            result += (
                f"对方：{status.get('other_user_id')}:{status.get('other_device_id')}\n"
            )
            if status.get("sas_code"):
                result += f"SAS 码：{status['sas_code']}\n"
            return result
        else:
            # 列出所有验证会话
            verifications = self.e2ee_manager.get_all_verifications()
            if not verifications:
                return "没有进行中的验证会话"

            result = "进行中的验证会话:\n"
            for vid, info in verifications.items():
                result += (
                    f"- {vid}: {info.get('state')} ({info.get('other_user_id')})\n"
                )
            return result

    async def cmd_devices(self, args: list) -> str:
        """查看已验证的设备"""
        if len(args) < 1:
            return "用法：devices <user_id>"

        user_id = args[0]
        devices = self.e2ee_manager.get_verified_devices(user_id)

        if not devices:
            return f"用户 {user_id} 没有已验证的设备"

        result = f"用户 {user_id} 的已验证设备:\n"
        for device_id in devices:
            result += f"- {device_id}\n"
        return result

    async def cmd_keys(self, args: list) -> str:
        """查看身份密钥"""
        keys = self.e2ee_manager.get_identity_keys()
        if not keys:
            return "获取身份密钥失败"

        result = "身份密钥:\n"
        result += f"Curve25519: {keys.get('curve25519', 'N/A')}\n"
        result += f"Ed25519: {keys.get('ed25519', 'N/A')}\n"
        return result

    async def cmd_help(self, args: list) -> str:
        """显示帮助信息"""
        help_text = """
Matrix E2EE 命令帮助：

verify <user_id> <device_id>  - 启动设备验证
accept <verification_id>       - 接受设备验证
sas <verification_id>          - 获取 SAS 验证码
confirm <verification_id> <sas_code> - 确认 SAS 验证码
complete <verification_id>     - 完成设备验证
cancel <verification_id> [reason] - 取消设备验证
status [verification_id]       - 查看验证状态
devices <user_id>              - 查看已验证的设备
keys                           - 查看身份密钥
help                           - 显示此帮助信息
"""
        return help_text
