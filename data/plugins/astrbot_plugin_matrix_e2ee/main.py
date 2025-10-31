"""
Matrix E2EE 设备验证插件
提供交互式的设备验证和密钥交换功能
"""

from astrbot.api.star import Star, Context, register
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api import logger


@register("astrbot_plugin_matrix_e2ee", "AstrBot", "Matrix E2EE 端到端加密设备验证和密钥恢复插件", "v1.0.0")
class MatrixE2EEVerificationPlugin(Star):
    """Matrix E2EE 设备验证插件"""

    def __init__(self, context: Context):
        super().__init__(context)
        self.e2ee_manager = None

    async def initialize(self):
        """初始化插件"""
        logger.info("Matrix E2EE Verification Plugin initialized")

    def _get_e2ee_manager(self, event: AstrMessageEvent):
        """获取 E2EE 管理器"""
        try:
            # 使用正确的属性名：platform_meta.name
            platform_name = event.platform_meta.name
            if platform_name != "matrix":
                return None

            # 从平台适配器获取 E2EE 管理器
            # 使用 platform_meta.id 来获取特定的适配器实例
            platform_id = event.platform_meta.id
            adapter = self.context.get_platform_inst(platform_id)
            if adapter and hasattr(adapter, "e2ee_manager"):
                return adapter.e2ee_manager
            return None
        except Exception as e:
            logger.error(f"Error getting E2EE manager: {e}")
            return None

    @filter.command("e2ee_verify")
    async def start_verification(self, event: AstrMessageEvent, user_id: str = "", device_id: str = ""):
        """启动 E2EE 设备验证

        需要提供对方的 user_id 和 device_id
        """
        try:
            e2ee_manager = self._get_e2ee_manager(event)
            if not e2ee_manager or not e2ee_manager.is_enabled():
                yield event.plain_result("E2EE 未启用")
                return

            # 如果没有参数，则尝试自动识别并验证发出者的当前设备
            if not user_id or not device_id:
                sender_id = event.get_sender_id()

                # 尝试通过 keys/query 查询对方设备并挑选一个设备自动验证
                try:
                    response = await e2ee_manager.client.query_keys(device_keys={sender_id: []})
                    device_keys = response.get("device_keys", {}).get(sender_id, {})
                except Exception as e:
                    logger.error(f"Failed to query device keys for {sender_id}: {e}")
                    yield event.plain_result(
                        "用法：/e2ee_verify <user_id> <device_id>\n\n"
                        "无法自动识别对方设备（查询 keys 失败）。请手动指定 device_id。"
                    )
                    return

                if not device_keys:
                    # 没有查询到任何设备密钥，提示用户手动指定
                    yield event.plain_result(
                        "未能查询到对方设备信息。请使用：/e2ee_verify <user_id> <device_id> 来指定设备。"
                    )
                    return

                # 选择一个候选设备：优先选第一个非空项
                chosen_device = None
                for did, info in device_keys.items():
                    # 跳过我们的机器人自身设备（如果出现在列表中）
                    try:
                        bot_device = getattr(e2ee_manager, "device_id", None) or getattr(e2ee_manager.store, "device_id", None)
                    except Exception:
                        bot_device = None

                    if bot_device and did == bot_device:
                        continue
                    chosen_device = did
                    break

                # 如果仍然没有可选设备，就退回到任意设备
                if not chosen_device:
                    chosen_device = next(iter(device_keys.keys()))

                user_id = sender_id
                device_id = chosen_device
                logger.info(f"Auto-detected device for verification: {user_id}:{device_id}")

            # 设备验证使用 to-device 消息，不需要房间 ID
            verification_id = await e2ee_manager.start_device_verification(
                user_id, device_id
            )
            if not verification_id:
                yield event.plain_result("启动验证失败")
                return

            # 自动接受验证请求并发送 start 事件
            if await e2ee_manager.accept_device_verification(verification_id):
                logger.info(f"Auto-accepted verification {verification_id}")

                yield event.plain_result(
                    f"✅ 已启动验证会话：{verification_id}\n"
                    f"正在与 {user_id}:{device_id} 进行验证\n\n"
                    f"📱 验证请求已发送到 Matrix 服务器\n"
                    f"📱 请在你的客户端（Element 等）接受验证请求\n"
                    f"📱 客户端接受后，验证将自动进行\n\n"
                    f"➡️ 使用以下命令查看验证状态：\n"
                    f"   /e2ee_status {verification_id}\n\n"
                    f"💡 如需获取 SAS 验证码：\n"
                    f"   /e2ee_sas {verification_id}\n\n"
                    f"⏳ 等待客户端响应..."
                )
            else:
                yield event.plain_result(
                    f"✓ 已启动验证会话：{verification_id}\n"
                    f"正在与 {user_id}:{device_id} 进行验证\n"
                    "⚠️ 自动接受失败，请手动操作"
                )
        except Exception as e:
            logger.error(f"Error in start_verification: {e}")
            yield event.plain_result(f"错误：{str(e)}")

    @filter.command("e2ee_accept")
    async def accept_verification(self, event: AstrMessageEvent, verification_id: str = ""):
        """接受 E2EE 设备验证（已自动接受，此命令保留用于手动操作）"""
        try:
            if not verification_id:
                yield event.plain_result(
                    "用法：/e2ee_accept <verification_id>\n"
                    "注意：设备验证请求已自动接受，通常不需要手动执行此命令"
                )
                return

            e2ee_manager = self._get_e2ee_manager(event)
            if not e2ee_manager or not e2ee_manager.is_enabled():
                yield event.plain_result("E2EE 未启用")
                return

            if not e2ee_manager.accept_device_verification(verification_id):
                yield event.plain_result("接受验证失败（可能已经接受过）")
                return

            yield event.plain_result("✓ 已接受验证请求")
        except Exception as e:
            logger.error(f"Error in accept_verification: {e}")
            yield event.plain_result(f"错误：{str(e)}")

    @filter.command("e2ee_sas")
    async def get_sas_code(self, event: AstrMessageEvent, verification_id: str = ""):
        """获取 SAS 验证码"""
        try:
            if not verification_id:
                yield event.plain_result("用法：/e2ee_sas <verification_id>")
                return

            e2ee_manager = self._get_e2ee_manager(event)
            if not e2ee_manager or not e2ee_manager.is_enabled():
                yield event.plain_result("E2EE 未启用")
                return

            sas_code = e2ee_manager.get_sas_code(verification_id)
            if not sas_code:
                yield event.plain_result("获取 SAS 码失败")
                return

            yield event.plain_result(f"✓ SAS 验证码：{sas_code}\n请与对方比对此验证码")
        except Exception as e:
            logger.error(f"Error in get_sas_code: {e}")
            yield event.plain_result(f"错误：{str(e)}")

    @filter.command("e2ee_confirm")
    async def confirm_sas(self, event: AstrMessageEvent, verification_id: str = "", sas_code: str = ""):
        """确认 SAS 验证码"""
        try:
            if not verification_id or not sas_code:
                yield event.plain_result("用法：/e2ee_confirm <verification_id> <sas_code>")
                return

            e2ee_manager = self._get_e2ee_manager(event)
            if not e2ee_manager or not e2ee_manager.is_enabled():
                yield event.plain_result("E2EE 未启用")
                return

            if not e2ee_manager.confirm_sas_code(verification_id, sas_code):
                yield event.plain_result("SAS 码确认失败")
                return

            yield event.plain_result("✓ SAS 码已确认")
        except Exception as e:
            logger.error(f"Error in confirm_sas: {e}")
            yield event.plain_result(f"错误：{str(e)}")

    @filter.command("e2ee_complete")
    async def complete_verification(self, event: AstrMessageEvent, verification_id: str = ""):
        """完成设备验证"""
        try:
            if not verification_id:
                yield event.plain_result("用法：/e2ee_complete <verification_id>")
                return

            e2ee_manager = self._get_e2ee_manager(event)
            if not e2ee_manager or not e2ee_manager.is_enabled():
                yield event.plain_result("E2EE 未启用")
                return

            if not e2ee_manager.complete_device_verification(verification_id):
                yield event.plain_result("完成验证失败")
                return

            yield event.plain_result("✓ 设备验证已完成")
        except Exception as e:
            logger.error(f"Error in complete_verification: {e}")
            yield event.plain_result(f"错误：{str(e)}")

    @filter.command("e2ee_status")
    async def get_status(self, event: AstrMessageEvent, verification_id: str = ""):
        """查看验证状态"""
        try:
            e2ee_manager = self._get_e2ee_manager(event)
            if not e2ee_manager or not e2ee_manager.is_enabled():
                yield event.plain_result("E2EE 未启用")
                return

            if verification_id:
                status = e2ee_manager.get_verification_status(verification_id)
                if not status:
                    yield event.plain_result("未找到验证会话")
                    return
                
                yield event.plain_result(
                    f"验证 ID：{verification_id}\n"
                    f"状态：{status['state']}\n"
                    f"对方用户：{status.get('other_user_id', 'N/A')}\n"
                    f"对方设备：{status.get('other_device_id', 'N/A')}"
                )
            else:
                verifications = e2ee_manager.get_all_verifications()
                if not verifications:
                    yield event.plain_result("没有进行中的验证会话")
                    return
                
                result = "📋 验证会话列表：\n\n"
                for ver_id, ver_data in verifications.items():
                    result += f"ID: {ver_id}\n"
                    result += f"状态: {ver_data.get('state', 'unknown')}\n"
                    result += f"对方: {ver_data.get('other_user_id', 'N/A')}\n"
                    result += f"设备: {ver_data.get('other_device_id', 'N/A')}\n\n"
                yield event.plain_result(result.strip())
        except Exception as e:
            logger.error(f"Error in get_status: {e}")
            yield event.plain_result(f"错误：{str(e)}")

    @filter.command("e2ee_devices")
    async def list_devices(self, event: AstrMessageEvent, user_id: str = ""):
        """查看已验证设备"""
        try:
            if not user_id:
                yield event.plain_result(
                    "用法：/e2ee_devices <user_id>\n\n"
                    "查看指定用户的已验证设备列表\n\n"
                    "示例：/e2ee_devices @alice:example.com"
                )
                return

            e2ee_manager = self._get_e2ee_manager(event)
            if not e2ee_manager or not e2ee_manager.is_enabled():
                yield event.plain_result("E2EE 未启用")
                return

            devices = e2ee_manager.get_verified_devices(user_id)
            if not devices:
                yield event.plain_result(
                    f"❌ 用户 {user_id} 没有已验证的设备\n\n"
                    f"💡 提示：使用 /e2ee_verify {user_id} <device_id> 来验证设备"
                )
                return

            result = f"✅ 用户 {user_id} 的已验证设备：\n\n"
            for device_id in devices:
                result += f"• {device_id}\n"
            yield event.plain_result(result)
        except Exception as e:
            logger.error(f"Error in list_devices: {e}")
            yield event.plain_result(f"错误：{str(e)}")

    @filter.command("e2ee_keys")
    async def show_keys(self, event: AstrMessageEvent):
        """查看身份密钥"""
        try:
            e2ee_manager = self._get_e2ee_manager(event)
            if not e2ee_manager or not e2ee_manager.is_enabled():
                yield event.plain_result("E2EE 未启用")
                return

            keys = e2ee_manager.get_identity_keys()
            if not keys:
                yield event.plain_result("获取身份密钥失败")
                return

            # 获取设备信息
            platform_id = event.platform_meta.id
            adapter = self.context.get_platform_inst(platform_id)
            device_id = getattr(adapter.config, 'device_id', 'Unknown')
            user_id = getattr(adapter.config, 'user_id', 'Unknown')

            yield event.plain_result(
                f"🔐 本机设备信息：\n\n"
                f"用户 ID：{user_id}\n"
                f"设备 ID：{device_id}\n\n"
                f"身份密钥：\n"
                f"Curve25519：{keys.get('curve25519', 'N/A')}\n"
                f"Ed25519：{keys.get('ed25519', 'N/A')}\n\n"
                f"💡 提示：设备 ID 用于启动验证流程"
            )
        except Exception as e:
            logger.error(f"Error in show_keys: {e}")
            yield event.plain_result(f"错误：{str(e)}")

    @filter.command("e2ee_recovery_request")
    async def request_recovery(self, event: AstrMessageEvent, device_id: str = ""):
        """请求密钥恢复"""
        try:
            if not device_id:
                yield event.plain_result("用法：/e2ee_recovery_request <device_id>")
                return

            e2ee_manager = self._get_e2ee_manager(event)
            if not e2ee_manager or not e2ee_manager.is_enabled():
                yield event.plain_result("E2EE 未启用")
                return

            request_id = e2ee_manager.request_key_recovery(device_id)
            if not request_id:
                yield event.plain_result("请求密钥恢复失败")
                return

            yield event.plain_result(
                f"✓ 已发送密钥恢复请求：{request_id}\n"
                f"目标设备：{device_id}\n"
                "请等待对方接受恢复请求"
            )
        except Exception as e:
            logger.error(f"Error in request_recovery: {e}")
            yield event.plain_result(f"错误：{str(e)}")

    @filter.command("e2ee_recovery_accept")
    async def accept_recovery(self, event: AstrMessageEvent, request_id: str = ""):
        """接受密钥恢复请求"""
        try:
            if not request_id:
                yield event.plain_result("用法：/e2ee_recovery_accept <request_id>")
                return

            e2ee_manager = self._get_e2ee_manager(event)
            if not e2ee_manager or not e2ee_manager.is_enabled():
                yield event.plain_result("E2EE 未启用")
                return

            if not e2ee_manager.accept_recovery_request(request_id):
                yield event.plain_result("接受恢复请求失败")
                return

            yield event.plain_result("✓ 已接受恢复请求")
        except Exception as e:
            logger.error(f"Error in accept_recovery: {e}")
            yield event.plain_result(f"错误：{str(e)}")

    @filter.command("e2ee_recovery_code")
    async def get_recovery_code(self, event: AstrMessageEvent, request_id: str = ""):
        """获取恢复验证码"""
        try:
            if not request_id:
                yield event.plain_result("用法：/e2ee_recovery_code <request_id>")
                return

            e2ee_manager = self._get_e2ee_manager(event)
            if not e2ee_manager or not e2ee_manager.is_enabled():
                yield event.plain_result("E2EE 未启用")
                return

            code = e2ee_manager.generate_recovery_code(request_id)
            if not code:
                yield event.plain_result("获取恢复验证码失败")
                return

            yield event.plain_result(f"✓ 恢复验证码：{code}\n请与对方比对此验证码")
        except Exception as e:
            logger.error(f"Error in get_recovery_code: {e}")
            yield event.plain_result(f"错误：{str(e)}")

    @filter.command("e2ee_recovery_confirm")
    async def confirm_recovery_code(self, event: AstrMessageEvent, request_id: str = "", code: str = ""):
        """确认恢复验证码"""
        try:
            if not request_id or not code:
                yield event.plain_result("用法：/e2ee_recovery_confirm <request_id> <code>")
                return

            e2ee_manager = self._get_e2ee_manager(event)
            if not e2ee_manager or not e2ee_manager.is_enabled():
                yield event.plain_result("E2EE 未启用")
                return

            if not e2ee_manager.confirm_recovery_code(request_id, code):
                yield event.plain_result("恢复验证码确认失败")
                return

            yield event.plain_result("✓ 恢复验证码已确认")
        except Exception as e:
            logger.error(f"Error in confirm_recovery_code: {e}")
            yield event.plain_result(f"错误：{str(e)}")

    @filter.command("e2ee_recovery_share")
    async def share_keys(self, event: AstrMessageEvent, request_id: str = ""):
        """分享密钥"""
        try:
            if not request_id:
                yield event.plain_result("用法：/e2ee_recovery_share <request_id>")
                return

            e2ee_manager = self._get_e2ee_manager(event)
            if not e2ee_manager or not e2ee_manager.is_enabled():
                yield event.plain_result("E2EE 未启用")
                return

            if not e2ee_manager.share_keys(request_id):
                yield event.plain_result("分享密钥失败")
                return

            yield event.plain_result("✓ 密钥已分享")
        except Exception as e:
            logger.error(f"Error in share_keys: {e}")
            yield event.plain_result(f"错误：{str(e)}")

    @filter.command("e2ee_recovery_receive")
    async def receive_keys(self, event: AstrMessageEvent, request_id: str = ""):
        """接收密钥"""
        try:
            if not request_id:
                yield event.plain_result("用法：/e2ee_recovery_receive <request_id>")
                return

            e2ee_manager = self._get_e2ee_manager(event)
            if not e2ee_manager or not e2ee_manager.is_enabled():
                yield event.plain_result("E2EE 未启用")
                return

            keys = e2ee_manager.receive_keys(request_id)
            if not keys:
                yield event.plain_result("接收密钥失败")
                return

            yield event.plain_result("✓ 密钥已接收并导入")
        except Exception as e:
            logger.error(f"Error in receive_keys: {e}")
            yield event.plain_result(f"错误：{str(e)}")

    @filter.command("e2ee_recovery_status")
    async def get_recovery_status(self, event: AstrMessageEvent, request_id: str = ""):
        """查看恢复状态"""
        try:
            e2ee_manager = self._get_e2ee_manager(event)
            if not e2ee_manager or not e2ee_manager.is_enabled():
                yield event.plain_result("E2EE 未启用")
                return

            if request_id:
                status = e2ee_manager.get_recovery_request_status(request_id)
                if not status:
                    yield event.plain_result("未找到恢复请求")
                    return

                yield event.plain_result(
                    f"恢复请求 ID：{request_id}\n"
                    f"状态：{status['state']}\n"
                    f"目标设备：{status.get('target_device_id', 'N/A')}"
                )
            else:
                requests = e2ee_manager.list_recovery_requests()
                if not requests:
                    yield event.plain_result("没有进行中的恢复请求")
                    return

                result = "恢复请求列表：\n"
                for req in requests:
                    result += f"- {req['request_id']}: {req['state']}\n"
                yield event.plain_result(result)
        except Exception as e:
            logger.error(f"Error in get_recovery_status: {e}")
            yield event.plain_result(f"错误：{str(e)}")

    @filter.command("e2ee_info")
    async def show_info(self, event: AstrMessageEvent):
        """显示 E2EE 信息和使用指南"""
        try:
            e2ee_manager = self._get_e2ee_manager(event)
            if not e2ee_manager or not e2ee_manager.is_enabled():
                yield event.plain_result("E2EE 未启用")
                return

            # 获取机器人设备信息
            platform_id = event.platform_meta.id
            adapter = self.context.get_platform_inst(platform_id)
            bot_device_id = getattr(adapter.config, 'device_id', 'Unknown')
            bot_user_id = getattr(adapter.config, 'user_id', 'Unknown')
            
            # 获取用户信息
            user_id = event.get_sender_id()

            yield event.plain_result(
                f"🤖 E2EE 端到端加密信息\n\n"
                f"✅ E2EE 功能已启用！\n\n"
                f"📋 你的信息：\n"
                f"• 用户 ID: {user_id}\n"
                f"• 设备 ID: 请在客户端查看（见下方提示）\n\n"
                f"🤖 机器人信息：\n"
                f"• 用户 ID: {bot_user_id}\n"
                f"• 设备 ID: {bot_device_id}\n\n"
                f"📱 设备验证流程：\n"
                f"1. 在你的客户端（Element 等）查看你的设备 ID：\n"
                f"   设置 → 安全与隐私 → 会话管理 → 当前会话\n\n"
                f"2. 使用以下命令验证你的设备：\n"
                f"   /e2ee_verify {user_id} <你的设备ID>\n\n"
                f"3. 在客户端接受验证请求\n\n"
                f"4. 获取 SAS 验证码进行比对：\n"
                f"   /e2ee_sas <验证ID>\n\n"
                f"💡 快速示例（假设你的设备 ID 是 ABCDEFGH）：\n"
                f"   /e2ee_verify {user_id} ABCDEFGH\n\n"
                f"✨ 已实现功能：\n"
                f"• ✅ 本地密钥生成和存储（vodozemac）\n"
                f"• ✅ 发送验证请求（to-device 消息）\n"
                f"• ✅ SAS 短代码生成\n"
                f"• ✅ 设备验证管理\n\n"
                f"🔧 开发中功能：\n"
                f"• ⏳ 监听验证响应事件\n"
                f"• ⏳ Olm/Megolm 加密解密\n\n"
                f"� 使用 /e2ee_help 查看完整命令列表"
            )
        except Exception as e:
            logger.error(f"Error in show_info: {e}")
            yield event.plain_result(f"错误：{str(e)}")

    @filter.command("e2ee_help")
    async def show_help(self, event: AstrMessageEvent):
        """显示 E2EE 帮助信息"""
        help_text = """Matrix E2EE 端到端加密帮助

� 快速开始：
/e2ee_info - 查看机器人信息和验证示例（推荐先用这个！）
/e2ee_keys - 查看本机设备 ID 和身份密钥

�📱 设备验证流程：
1. /e2ee_verify <user_id> <device_id> - 启动验证
2. /e2ee_sas <verification_id> - 获取 SAS 验证码
3. 与对方比对验证码是否一致
4. /e2ee_confirm <verification_id> <sas_code> - 确认验证码
5. /e2ee_complete <verification_id> - 完成验证

🔑 设备验证命令：
/e2ee_verify <user_id> <device_id> - 启动与指定用户设备的验证
/e2ee_accept <verification_id> - 手动接受验证请求（通常自动接受）
/e2ee_sas <verification_id> - 获取 SAS 验证码
/e2ee_confirm <verification_id> <sas_code> - 确认 SAS 验证码
/e2ee_complete <verification_id> - 完成设备验证

📊 查询命令：
/e2ee_info - 查看机器人信息和验证命令示例
/e2ee_status [verification_id] - 查看验证状态或列出所有验证
/e2ee_devices <user_id> - 查看指定用户的已验证设备
/e2ee_keys - 查看本机设备 ID 和身份密钥

🔄 密钥恢复命令：
/e2ee_recovery_request <device_id> - 向其他设备请求密钥
/e2ee_recovery_accept <request_id> - 接受密钥恢复请求
/e2ee_recovery_code <request_id> - 获取恢复验证码
/e2ee_recovery_confirm <request_id> <code> - 确认恢复验证码
/e2ee_recovery_share <request_id> - 分享密钥给请求设备
/e2ee_recovery_receive <request_id> - 接收恢复的密钥
/e2ee_recovery_status [request_id] - 查看恢复请求状态

💡 提示：
- 先用 /e2ee_info 获取完整的验证命令示例
- 设备 ID 可在 Element 等客户端的设置中查看
- 验证码必须与对方完全一致才能通过验证
- 完成验证后才能安全地发送加密消息"""
        yield event.plain_result(help_text.strip())

    async def terminate(self):
        """插件终止时调用"""
        logger.info("Matrix E2EE Verification Plugin terminated")

