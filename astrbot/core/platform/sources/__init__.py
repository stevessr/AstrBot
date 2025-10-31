"""
平台适配器源文件

此模块负责预加载所有平台适配器，确保它们的注册信息在应用启动时就可用。
这样在前端显示平台列表时，所有可用的平台类型都会显示，而不仅仅是已配置的平台。
"""


def register_all_platforms():
    """预加载所有平台适配器，使其注册到 platform_registry"""
    from astrbot.core import logger

    logger.debug("开始预加载所有平台适配器...")

    # 导入所有平台适配器以触发 @register_platform_adapter 装饰器
    try:
        from .aiocqhttp.aiocqhttp_platform_adapter import AiocqhttpAdapter  # noqa: F401

        logger.debug("已加载 aiocqhttp 平台适配器")
    except ImportError:
        pass

    try:
        from .qq_official.qqofficial_platform_adapter import (  # noqa: F401
            QQOfficialPlatformAdapter,
        )
    except ImportError:
        pass

    try:
        from .qq_official_webhook.qo_webhook_adapter import (  # noqa: F401
            QQOfficialWebhookPlatformAdapter,
        )
    except ImportError:
        pass

    try:
        from .wechatpadpro.wechatpadpro_adapter import WeChatPadProAdapter  # noqa: F401
    except ImportError:
        pass

    try:
        from .lark.lark_adapter import LarkPlatformAdapter  # noqa: F401
    except ImportError:
        pass

    try:
        from .dingtalk.dingtalk_adapter import DingtalkPlatformAdapter  # noqa: F401
    except ImportError:
        pass

    try:
        from .telegram.tg_adapter import TelegramPlatformAdapter  # noqa: F401
    except ImportError:
        pass

    try:
        from .wecom.wecom_adapter import WecomPlatformAdapter  # noqa: F401
    except ImportError:
        pass

    try:
        from .wecom_ai_bot.wecomai_adapter import WecomAIBotAdapter  # noqa: F401
    except ImportError:
        pass

    try:
        from .weixin_official_account.weixin_offacc_adapter import (  # noqa: F401
            WeixinOfficialAccountPlatformAdapter,
        )
    except ImportError:
        pass

    try:
        from .discord.discord_platform_adapter import DiscordPlatformAdapter  # noqa: F401
    except ImportError:
        pass

    try:
        from .misskey.misskey_adapter import MisskeyPlatformAdapter  # noqa: F401
    except ImportError:
        pass

    try:
        from .matrix.matrix_adapter import MatrixPlatformAdapter  # noqa: F401

        logger.debug("已加载 matrix 平台适配器")
    except ImportError as e:
        logger.warning(f"无法加载 matrix 平台适配器：{e}")
    except Exception as e:
        logger.error(f"加载 matrix 平台适配器时发生错误：{e}")

    try:
        from .slack.slack_adapter import SlackAdapter  # noqa: F401
    except ImportError:
        pass

    try:
        from .satori.satori_adapter import SatoriPlatformAdapter  # noqa: F401
    except ImportError:
        pass

    try:
        from .webchat.webchat_adapter import WebChatAdapter  # noqa: F401
    except ImportError:
        pass
