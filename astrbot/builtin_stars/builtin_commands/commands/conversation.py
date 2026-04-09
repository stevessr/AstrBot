import copy
import datetime
import json

from astrbot.api import sp, star
from astrbot.api.event import AstrMessageEvent, MessageEventResult
from astrbot.core import logger
from astrbot.core.agent.context.compressor import LLMSummaryCompressor
from astrbot.core.agent.context.config import ContextConfig
from astrbot.core.agent.context.manager import ContextManager
from astrbot.core.agent.message import Message
from astrbot.core.agent.runners.deerflow.constants import (
    DEERFLOW_AGENT_RUNNER_PROVIDER_ID_KEY,
    DEERFLOW_PROVIDER_TYPE,
    DEERFLOW_THREAD_ID_KEY,
)
from astrbot.core.agent.runners.deerflow.deerflow_api_client import DeerFlowAPIClient
from astrbot.core.platform.astr_message_event import MessageSession
from astrbot.core.platform.message_type import MessageType
from astrbot.core.provider import Provider
from astrbot.core.utils.active_event_registry import active_event_registry
from astrbot.core.utils.llm_metadata import LLM_METADATAS

from .utils.rst_scene import RstScene

THIRD_PARTY_AGENT_RUNNER_KEY = {
    "dify": "dify_conversation_id",
    "coze": "coze_conversation_id",
    "dashscope": "dashscope_conversation_id",
    DEERFLOW_PROVIDER_TYPE: DEERFLOW_THREAD_ID_KEY,
}
THIRD_PARTY_AGENT_RUNNER_STR = ", ".join(THIRD_PARTY_AGENT_RUNNER_KEY.keys())


async def _cleanup_deerflow_thread_if_present(
    context: star.Context,
    umo: str,
) -> None:
    try:
        thread_id = await sp.get_async(
            scope="umo",
            scope_id=umo,
            key=DEERFLOW_THREAD_ID_KEY,
            default="",
        )
        if not thread_id:
            return

        cfg = context.get_config(umo=umo)
        provider_id = cfg["provider_settings"].get(
            DEERFLOW_AGENT_RUNNER_PROVIDER_ID_KEY,
            "",
        )
        if not provider_id:
            return

        merged_provider_config = context.provider_manager.get_provider_config_by_id(
            provider_id,
            merged=True,
        )
        if not merged_provider_config:
            logger.warning(
                "Failed to resolve DeerFlow provider config for remote thread cleanup: provider_id=%s",
                provider_id,
            )
            return

        client = DeerFlowAPIClient(
            api_base=merged_provider_config.get(
                "deerflow_api_base",
                "http://127.0.0.1:2026",
            ),
            api_key=merged_provider_config.get("deerflow_api_key", ""),
            auth_header=merged_provider_config.get("deerflow_auth_header", ""),
            proxy=merged_provider_config.get("proxy", ""),
        )
        try:
            await client.delete_thread(thread_id)
        finally:
            try:
                await client.close()
            except Exception as e:
                logger.warning(
                    "Failed to close DeerFlow API client after thread cleanup: %s",
                    e,
                )
    except Exception as e:
        logger.warning(
            "Failed to clean up DeerFlow thread for session %s: %s",
            umo,
            e,
        )


async def _clear_third_party_agent_runner_state(
    context: star.Context,
    umo: str,
    agent_runner_type: str,
) -> None:
    session_key = THIRD_PARTY_AGENT_RUNNER_KEY.get(agent_runner_type)
    if not session_key:
        return

    if agent_runner_type == DEERFLOW_PROVIDER_TYPE:
        await _cleanup_deerflow_thread_if_present(context, umo)

    await sp.remove_async(
        scope="umo",
        scope_id=umo,
        key=session_key,
    )


class ConversationCommands:
    def __init__(self, context: star.Context) -> None:
        self.context = context

    async def _get_current_persona_id(self, session_id):
        curr = await self.context.conversation_manager.get_curr_conversation_id(
            session_id,
        )
        if not curr:
            return None
        conv = await self.context.conversation_manager.get_conversation(
            session_id,
            curr,
        )
        if not conv:
            return None
        return conv.persona_id

    def _resolve_dequeue_context_length(self, provider_settings: dict) -> int:
        max_context_length = provider_settings.get("max_context_length", -1)
        dequeue_context_length = provider_settings.get("dequeue_context_length", 1)
        dequeue_context_length = min(
            max(1, dequeue_context_length),
            max_context_length - 1,
        )
        if dequeue_context_length <= 0:
            dequeue_context_length = 1
        return dequeue_context_length

    def _resolve_manual_compress_provider(
        self,
        provider_settings: dict,
    ) -> Provider | None:
        if provider_settings.get("context_limit_reached_strategy") != "llm_compress":
            return None

        provider_id = provider_settings.get("llm_compress_provider_id", "")
        if not provider_id:
            return None

        provider = self.context.get_provider_by_id(provider_id)
        if not isinstance(provider, Provider):
            return None

        return provider

    def _build_context_manager(
        self,
        message: AstrMessageEvent,
        provider: Provider,
    ) -> ContextManager:
        provider_settings = self.context.get_config(message.unified_msg_origin).get(
            "provider_settings",
            {},
        )

        if provider.provider_config.get("max_context_tokens", 0) <= 0:
            model = provider.get_model()
            if model_info := LLM_METADATAS.get(model):
                provider.provider_config["max_context_tokens"] = model_info["limit"][
                    "context"
                ]

        context_config = ContextConfig(
            max_context_tokens=provider.provider_config.get("max_context_tokens", 0),
            enforce_max_turns=provider_settings.get("max_context_length", -1),
            truncate_turns=self._resolve_dequeue_context_length(provider_settings),
            llm_compress_instruction=provider_settings.get(
                "llm_compress_instruction",
                "",
            ),
            llm_compress_keep_recent=provider_settings.get(
                "llm_compress_keep_recent",
                4,
            ),
            llm_compress_provider=self._resolve_manual_compress_provider(
                provider_settings,
            ),
        )
        return ContextManager(context_config)

    def _summarize_compression_type(self, context_manager: ContextManager) -> str:
        if isinstance(context_manager.compressor, LLMSummaryCompressor):
            return "LLM 摘要压缩"
        return "基于轮次的截断压缩"

    def _render_history_lines(self, contexts: list[str]) -> str:
        parts = []
        for context in contexts:
            if len(context) > 150:
                context = context[:150] + "..."
            parts.append(f"{context}\n")
        return "".join(parts)

    async def reset(self, message: AstrMessageEvent) -> None:
        """重置 LLM 会话"""
        umo = message.unified_msg_origin
        cfg = self.context.get_config(umo=message.unified_msg_origin)
        is_unique_session = cfg["platform_settings"]["unique_session"]
        is_group = bool(message.get_group_id())

        scene = RstScene.get_scene(is_group, is_unique_session)

        alter_cmd_cfg = await sp.get_async("global", "global", "alter_cmd", {})
        plugin_config = alter_cmd_cfg.get("astrbot", {})
        reset_cfg = plugin_config.get("reset", {})

        required_perm = reset_cfg.get(
            scene.key,
            "admin" if is_group and not is_unique_session else "member",
        )

        if required_perm == "admin" and message.role != "admin":
            message.set_result(
                MessageEventResult().message(
                    f"Reset command requires admin permission in {scene.name} scenario, "
                    f"you (ID {message.get_sender_id()}) are not admin, cannot perform this action.",
                ),
            )
            return

        agent_runner_type = cfg["provider_settings"]["agent_runner_type"]
        if agent_runner_type in THIRD_PARTY_AGENT_RUNNER_KEY:
            active_event_registry.stop_all(umo, exclude=message)
            await _clear_third_party_agent_runner_state(
                self.context,
                umo,
                agent_runner_type,
            )
            message.set_result(
                MessageEventResult().message("✅ Conversation reset successfully.")
            )
            return

        if not self.context.get_using_provider(umo):
            message.set_result(
                MessageEventResult().message(
                    "😕 Cannot find any LLM provider. Configure one first."
                ),
            )
            return

        cid = await self.context.conversation_manager.get_curr_conversation_id(umo)

        if not cid:
            message.set_result(
                MessageEventResult().message(
                    "😕 You are not in a conversation. Use /new to create one.",
                ),
            )
            return

        active_event_registry.stop_all(umo, exclude=message)

        await self.context.conversation_manager.update_conversation(
            umo,
            cid,
            [],
        )

        ret = "✅ Conversation reset successfully."

        message.set_extra("_clean_ltm_session", True)

        message.set_result(MessageEventResult().message(ret))

    async def stop(self, message: AstrMessageEvent) -> None:
        """停止当前会话正在运行的 Agent"""
        cfg = self.context.get_config(umo=message.unified_msg_origin)
        agent_runner_type = cfg["provider_settings"]["agent_runner_type"]
        umo = message.unified_msg_origin

        if agent_runner_type in THIRD_PARTY_AGENT_RUNNER_KEY:
            stopped_count = active_event_registry.stop_all(umo, exclude=message)
        else:
            stopped_count = active_event_registry.request_agent_stop_all(
                umo,
                exclude=message,
            )

        if stopped_count > 0:
            message.set_result(
                MessageEventResult().message(
                    f"✅ Requested to stop {stopped_count} running tasks."
                )
            )
            return

        message.set_result(MessageEventResult().message("当前会话没有运行中的任务。"))

    async def compact(self, message: AstrMessageEvent) -> None:
        """Manually compress the current conversation context."""
        umo = message.unified_msg_origin
        provider = self.context.get_using_provider(umo)
        if not provider:
            message.set_result(
                MessageEventResult().message("未找到任何 LLM 提供商。请先配置。"),
            )
            return

        conv_mgr = self.context.conversation_manager
        session_curr_cid = await conv_mgr.get_curr_conversation_id(umo)
        if not session_curr_cid:
            message.set_result(
                MessageEventResult().message(
                    "当前未处于对话状态，请 /switch 切换或者 /new 创建。",
                ),
            )
            return

        conversation = await conv_mgr.get_conversation(umo, session_curr_cid)
        if not conversation:
            message.set_result(
                MessageEventResult().message(
                    "未找到当前对话。请 /switch 切换或者 /new 创建。"
                ),
            )
            return

        history_records = json.loads(conversation.history)
        history = [Message.model_validate(record) for record in history_records]
        if not history_records:
            message.set_result(
                MessageEventResult().message("当前对话没有可压缩的历史记录。"),
            )
            return

        context_manager = self._build_context_manager(message, provider)
        await conv_mgr.save_compression_snapshot(
            umo,
            session_curr_cid,
            copy.deepcopy(history_records),
        )

        compressed_messages = await context_manager.manual_compress(
            history,
            trusted_token_usage=conversation.token_usage,
        )
        compressed_history = [
            msg.model_dump(exclude_none=True) for msg in compressed_messages
        ]
        token_usage = context_manager.token_counter.count_tokens(compressed_messages)
        await conv_mgr.update_conversation(
            umo,
            session_curr_cid,
            compressed_history,
            token_usage=token_usage,
        )

        compression_type = self._summarize_compression_type(context_manager)
        if compressed_history == history_records:
            ret = (
                f"已保存压缩前快照，但当前上下文未发生变化（{compression_type}）。\n"
                f"*输入 /history snapshot 1 查看最近一次压缩前内容"
            )
        else:
            ret = (
                f"已完成手动上下文压缩（{compression_type}）。\n"
                f"压缩前 {len(history_records)} 条消息，压缩后 {len(compressed_history)} 条消息。\n"
                f"*输入 /history snapshot 1 查看最近一次压缩前内容"
            )

        message.set_extra("_clean_ltm_session", True)
        message.set_result(MessageEventResult().message(ret).use_t2i(False))

    async def his(
        self,
        message: AstrMessageEvent,
        scope_or_page: str | int | None = None,
        snapshot_index: int | None = None,
        page: int | None = None,
    ) -> None:
        """查看对话记录"""
        if not self.context.get_using_provider(message.unified_msg_origin):
            message.set_result(
                MessageEventResult().message("未找到任何 LLM 提供商。请先配置。"),
            )
            return

        size_per_page = 6

        conv_mgr = self.context.conversation_manager
        umo = message.unified_msg_origin
        if isinstance(scope_or_page, str):
            scope = scope_or_page.lower()
            if scope != "snapshot":
                message.set_result(
                    MessageEventResult().message(
                        "用法错误。/history [页码] 或 /history snapshot <快照序号> [页码]",
                    ),
                )
                return

            session_curr_cid = await conv_mgr.get_curr_conversation_id(umo)
            if not session_curr_cid:
                message.set_result(
                    MessageEventResult().message(
                        "当前未处于对话状态，请 /switch 切换或者 /new 创建。",
                    ),
                )
                return

            normalized_snapshot_index = max(1, snapshot_index or 1)
            normalized_page = max(1, page or 1)
            (
                contexts,
                total_pages,
                snapshot,
            ) = await conv_mgr.get_human_readable_snapshot_context(
                umo,
                session_curr_cid,
                normalized_snapshot_index,
                normalized_page,
                size_per_page,
            )
            if snapshot is None:
                message.set_result(
                    MessageEventResult().message(
                        f"未找到第 {normalized_snapshot_index} 个压缩快照。",
                    ),
                )
                return

            history = self._render_history_lines(contexts)
            snapshot_time = snapshot.created_at.astimezone().strftime("%m-%d %H:%M")
            ret = (
                f"压缩前快照 #{normalized_snapshot_index} ({snapshot_time})："
                f"{history or '无历史记录'}\n\n"
                f"第 {normalized_page} 页 | 共 {total_pages} 页\n"
                f"*输入 /history snapshot {normalized_snapshot_index} 2 跳转到第 2 页"
            )
            message.set_result(MessageEventResult().message(ret).use_t2i(False))
            return

        normalized_page = max(1, scope_or_page if isinstance(scope_or_page, int) else 1)
        if snapshot_index is not None or page is not None:
            message.set_result(
                MessageEventResult().message(
                    "用法错误。/history [页码] 或 /history snapshot <快照序号> [页码]",
                ),
            )
            return

        session_curr_cid = await conv_mgr.get_curr_conversation_id(umo)

        if not session_curr_cid:
            session_curr_cid = await conv_mgr.new_conversation(
                umo,
                message.get_platform_id(),
            )

        contexts, total_pages = await conv_mgr.get_human_readable_context(
            umo,
            session_curr_cid,
            normalized_page,
            size_per_page,
        )

        history = self._render_history_lines(contexts)
        ret = (
            f"当前对话历史记录："
            f"{history or '无历史记录'}\n\n"
            f"第 {normalized_page} 页 | 共 {total_pages} 页\n"
            f"*输入 /history 2 跳转到第 2 页"
        )

        message.set_result(MessageEventResult().message(ret).use_t2i(False))

    async def convs(self, message: AstrMessageEvent, page: int = 1) -> None:
        """查看对话列表"""
        cfg = self.context.get_config(umo=message.unified_msg_origin)
        agent_runner_type = cfg["provider_settings"]["agent_runner_type"]
        if agent_runner_type in THIRD_PARTY_AGENT_RUNNER_KEY:
            message.set_result(
                MessageEventResult().message(
                    f"{THIRD_PARTY_AGENT_RUNNER_STR} 对话列表功能暂不支持。",
                ),
            )
            return

        size_per_page = 6
        """获取所有对话列表"""
        conversations_all = await self.context.conversation_manager.get_conversations(
            message.unified_msg_origin,
        )
        """计算总页数"""
        total_pages = (len(conversations_all) + size_per_page - 1) // size_per_page
        """确保页码有效"""
        page = max(1, min(page, total_pages))
        """分页处理"""
        start_idx = (page - 1) * size_per_page
        end_idx = start_idx + size_per_page
        conversations_paged = conversations_all[start_idx:end_idx]

        parts = ["对话列表：\n---\n"]
        """全局序号从当前页的第一个开始"""
        global_index = start_idx + 1

        """生成所有对话的标题字典"""
        _titles = {}
        for conv in conversations_all:
            title = conv.title if conv.title else "新对话"
            _titles[conv.cid] = title

        """遍历分页后的对话生成列表显示"""
        provider_settings = cfg.get("provider_settings", {})
        platform_name = message.get_platform_name()
        for conv in conversations_paged:
            (
                persona_id,
                _,
                force_applied_persona_id,
                _,
            ) = await self.context.persona_manager.resolve_selected_persona(
                umo=message.unified_msg_origin,
                conversation_persona_id=conv.persona_id,
                platform_name=platform_name,
                provider_settings=provider_settings,
            )
            if persona_id == "[%None]":
                persona_name = "无"
            elif persona_id:
                persona_name = persona_id
            else:
                persona_name = "无"

            if force_applied_persona_id:
                persona_name = f"{persona_name} (自定义规则)"

            title = _titles.get(conv.cid, "新对话")
            parts.append(
                f"{global_index}. {title}({conv.cid[:4]})\n  人格情景: {persona_name}\n  上次更新: {datetime.datetime.fromtimestamp(conv.updated_at).strftime('%m-%d %H:%M')}\n"
            )
            global_index += 1

        parts.append("---\n")
        ret = "".join(parts)
        curr_cid = await self.context.conversation_manager.get_curr_conversation_id(
            message.unified_msg_origin,
        )
        if curr_cid:
            """从所有对话的标题字典中获取标题"""
            title = _titles.get(curr_cid, "新对话")
            ret += f"\n当前对话: {title}({curr_cid[:4]})"
        else:
            ret += "\n当前对话: 无"

        cfg = self.context.get_config(umo=message.unified_msg_origin)
        unique_session = cfg["platform_settings"]["unique_session"]
        if unique_session:
            ret += "\n会话隔离粒度: 个人"
        else:
            ret += "\n会话隔离粒度: 群聊"

        ret += f"\n第 {page} 页 | 共 {total_pages} 页"
        ret += "\n*输入 /ls 2 跳转到第 2 页"

        message.set_result(MessageEventResult().message(ret).use_t2i(False))
        return

    async def new_conv(self, message: AstrMessageEvent) -> None:
        """创建新对话"""
        cfg = self.context.get_config(umo=message.unified_msg_origin)
        agent_runner_type = cfg["provider_settings"]["agent_runner_type"]
        if agent_runner_type in THIRD_PARTY_AGENT_RUNNER_KEY:
            active_event_registry.stop_all(message.unified_msg_origin, exclude=message)
            await _clear_third_party_agent_runner_state(
                self.context,
                message.unified_msg_origin,
                agent_runner_type,
            )
            message.set_result(
                MessageEventResult().message("✅ New conversation created.")
            )
            return

        active_event_registry.stop_all(message.unified_msg_origin, exclude=message)
        cpersona = await self._get_current_persona_id(message.unified_msg_origin)
        cid = await self.context.conversation_manager.new_conversation(
            message.unified_msg_origin,
            message.get_platform_id(),
            persona_id=cpersona,
        )

        message.set_extra("_clean_ltm_session", True)

        message.set_result(
            MessageEventResult().message(
                f"✅ Switched to new conversation: {cid[:4]}。"
            ),
        )
