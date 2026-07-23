from dataclasses import dataclass

BUILTIN_ACTIVE_REPLY_METHODS = ("possibility_reply",)


@dataclass
class ActiveReplyContext:
    """主动回复 hook 的上下文。

    插件可以根据 ``method`` 判断是否处理当前主动回复方法，并将
    ``should_reply`` 设置为 ``True`` 或 ``False``。保持为 ``None`` 时，
    AstrBot 会继续使用内置的主动回复逻辑。
    """

    method: str
    should_reply: bool | None = None


def refresh_active_reply_method_options() -> None:
    """将当前已注册的主动回复方法同步到核心配置元数据。"""
    from astrbot.core.config.default import CONFIG_METADATA_3
    from astrbot.core.star.star import star_map
    from astrbot.core.star.star_handler import EventType, star_handlers_registry

    methods = set(BUILTIN_ACTIVE_REPLY_METHODS)
    for handler in star_handlers_registry:
        if handler.event_type != EventType.OnActiveReplyEvent:
            continue
        method = handler.extras_configs.get("active_reply_method")
        plugin = star_map.get(handler.handler_module_path)
        if isinstance(method, str) and method and (plugin is None or plugin.activated):
            methods.add(method)

    options = list(BUILTIN_ACTIVE_REPLY_METHODS)
    options.extend(sorted(method for method in methods if method not in options))

    ltm_metadata = CONFIG_METADATA_3["ext_group"]["metadata"]["ltm"]["items"]
    ltm_metadata["provider_ltm_settings.active_reply.method"]["options"] = options
