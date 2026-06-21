from __future__ import annotations

import asyncio
from collections.abc import Sequence

from astrbot import logger
from astrbot.api import star
from astrbot.api.event import AstrMessageEvent, MessageEventResult
from astrbot.core.provider.entities import ProviderType
from astrbot.core.provider.provider import Provider
from astrbot.core.utils.error_redaction import safe_error


class ProviderCommands:
    def __init__(self, context: star.Context) -> None:
        self.context = context

    def _log_reachability_failure(
        self,
        provider,
        provider_capability_type: ProviderType | None,
        err_code: str,
        err_reason: str,
    ) -> None:
        meta = provider.meta()
        logger.warning(
            "Provider reachability check failed: id=%s type=%s code=%s reason=%s",
            meta.id,
            provider_capability_type.name if provider_capability_type else "unknown",
            err_code,
            err_reason,
        )

    async def _test_provider_capability(self, provider):
        meta = provider.meta()
        provider_capability_type = meta.provider_type

        try:
            await provider.test()
            return True, None, None
        except Exception as e:
            err_code = "TEST_FAILED"
            err_reason = safe_error("", e)
            self._log_reachability_failure(
                provider, provider_capability_type, err_code, err_reason
            )
            return False, err_code, err_reason

    async def _build_provider_display_data(
        self,
        providers,
        provider_type: str,
        reachability_check_enabled: bool,
    ) -> list[dict]:
        if not providers:
            return []

        if reachability_check_enabled:
            check_results = await asyncio.gather(
                *[self._test_provider_capability(provider) for provider in providers],
                return_exceptions=True,
            )
        else:
            check_results = [None for _ in providers]

        display_data = []
        for provider, reachable in zip(providers, check_results):
            meta = provider.meta()
            id_ = meta.id
            error_code = None

            if isinstance(reachable, asyncio.CancelledError):
                raise reachable
            if isinstance(reachable, Exception):
                self._log_reachability_failure(
                    provider,
                    None,
                    reachable.__class__.__name__,
                    safe_error("", reachable),
                )
                reachable_flag = False
                error_code = reachable.__class__.__name__
            elif isinstance(reachable, tuple):
                reachable_flag, error_code, _ = reachable
            else:
                reachable_flag = reachable

            if provider_type == "llm":
                info = f"{id_} ({meta.model})"
            else:
                info = f"{id_}"

            if reachable_flag is True:
                mark = " ✅"
            elif reachable_flag is False:
                if error_code:
                    mark = f" ❌(errcode: {error_code})"
                else:
                    mark = " ❌"
            else:
                mark = ""

            display_data.append(
                {
                    "info": info,
                    "mark": mark,
                    "provider": provider,
                }
            )

        return display_data

    def _resolve_model_name(
        self,
        model_name: str,
        models: Sequence[str],
    ) -> str | None:
        requested = model_name.strip()
        if not requested:
            return None

        requested_norm = requested.casefold()
        for candidate in models:
            if candidate == requested or candidate.casefold() == requested_norm:
                return candidate

        for candidate in models:
            candidate_norm = candidate.casefold()
            if candidate_norm.endswith(f"/{requested_norm}") or candidate_norm.endswith(
                f":{requested_norm}"
            ):
                return candidate

        return None

    async def _get_models_or_reply_error(
        self,
        message: AstrMessageEvent,
        provider: Provider,
    ) -> list[str] | None:
        try:
            return list(await provider.get_models())
        except asyncio.CancelledError:
            raise
        except Exception as e:
            message.set_result(
                MessageEventResult().message(safe_error("获取模型列表失败：", e))
            )
            return None

    def _apply_model(self, provider: Provider, model_name: str) -> str:
        provider.set_model(model_name)
        meta = provider.meta()
        return f"✅ 成功切换模型。当前提供商：[{meta.id}] 当前模型：[{provider.get_model()}]"

    async def _find_provider_for_model(
        self,
        model_name: str,
        *,
        exclude_provider_id: str | None,
    ) -> tuple[Provider | None, str | None]:
        for provider in self.context.get_all_providers():
            meta = provider.meta()
            if meta.id == exclude_provider_id:
                continue
            if meta.provider_type != ProviderType.CHAT_COMPLETION:
                continue
            try:
                models = list(await provider.get_models())
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.debug(
                    "获取提供商 %s 模型列表失败，跳过跨提供商查找：%s",
                    meta.id,
                    safe_error("", e),
                )
                continue
            matched_model = self._resolve_model_name(model_name, models)
            if matched_model is not None:
                return provider, matched_model
        return None, None

    async def _switch_model_by_name(
        self,
        message: AstrMessageEvent,
        model_name: str,
        provider: Provider,
    ) -> None:
        model_name = model_name.strip()
        if not model_name:
            message.set_result(MessageEventResult().message("模型名不能为空。"))
            return

        umo = message.unified_msg_origin
        current_provider_id = provider.meta().id
        models = await self._get_models_or_reply_error(message, provider)
        if models is None:
            return

        matched_model = self._resolve_model_name(model_name, models)
        if matched_model is not None:
            message.set_result(
                MessageEventResult().message(self._apply_model(provider, matched_model))
            )
            return

        target_provider, target_model = await self._find_provider_for_model(
            model_name,
            exclude_provider_id=current_provider_id,
        )
        if target_provider is None or target_model is None:
            message.set_result(
                MessageEventResult().message(
                    f"模型 [{model_name}] 未在任何已配置的提供商中找到，请检查配置或网络后重试。"
                )
            )
            return

        target_provider_id = target_provider.meta().id
        try:
            await self.context.provider_manager.set_provider(
                provider_id=target_provider_id,
                provider_type=ProviderType.CHAT_COMPLETION,
                umo=umo,
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            message.set_result(
                MessageEventResult().message(safe_error("切换提供商失败：", e))
            )
            return

        self._apply_model(target_provider, target_model)
        message.set_result(
            MessageEventResult().message(
                f"✅ 检测到模型 [{target_model}] 属于提供商 [{target_provider_id}]，已自动切换提供商并设置模型。"
            )
        )

    async def model_ls(
        self,
        message: AstrMessageEvent,
        idx_or_name: int | str | None = None,
    ) -> None:
        """查看或者切换模型"""
        provider = self.context.get_using_provider(message.unified_msg_origin)
        if not provider:
            message.set_result(
                MessageEventResult().message("未找到任何 LLM 提供商。请先配置。")
            )
            return

        if idx_or_name is None:
            models = await self._get_models_or_reply_error(message, provider)
            if models is None:
                return

            parts = ["## Models\n"]
            for i, model in enumerate(models, 1):
                line = f"{i}. {model}"
                if model == provider.get_model():
                    line += " 👈"
                parts.append(line + "\n")
            parts.append(f"\nCurrent model: {provider.get_model() or 'None'}")
            parts.append("\nUse /model <idx_or_name> to switch models.")
            message.set_result(
                MessageEventResult().message("".join(parts)).use_t2i(False)
            )
            return

        if isinstance(idx_or_name, int):
            models = await self._get_models_or_reply_error(message, provider)
            if models is None:
                return
            if idx_or_name > len(models) or idx_or_name < 1:
                message.set_result(
                    MessageEventResult().message("❌ Invalid model index.")
                )
                return
            message.set_result(
                MessageEventResult().message(
                    self._apply_model(provider, models[idx_or_name - 1])
                )
            )
            return

        await self._switch_model_by_name(message, idx_or_name, provider)

    async def provider(
        self,
        event: AstrMessageEvent,
        idx: str | int | None = None,
        idx2: int | None = None,
    ) -> None:
        """查看或者切换 LLM Provider"""
        umo = event.unified_msg_origin
        cfg = self.context.get_config(umo).get("provider_settings", {})
        reachability_check_enabled = cfg.get("reachability_check", True)

        if idx is None:
            parts = ["## LLM Providers\n"]

            llms = list(self.context.get_all_providers())
            ttss = self.context.get_all_tts_providers()
            stts = self.context.get_all_stt_providers()

            if reachability_check_enabled and (llms or ttss or stts):
                await event.send(
                    MessageEventResult().message("👀 Testing provider reachability...")
                )

            llm_data, tts_data, stt_data = await asyncio.gather(
                self._build_provider_display_data(
                    llms,
                    "llm",
                    reachability_check_enabled,
                ),
                self._build_provider_display_data(
                    ttss,
                    "tts",
                    reachability_check_enabled,
                ),
                self._build_provider_display_data(
                    stts,
                    "stt",
                    reachability_check_enabled,
                ),
            )

            provider_using = self.context.get_using_provider(umo=umo)
            for i, d in enumerate(llm_data):
                line = f"{i + 1}. {d['info']}{d['mark']}"
                if (
                    provider_using
                    and provider_using.meta().id == d["provider"].meta().id
                ):
                    line += " 👈"
                parts.append(line + "\n")

            if tts_data:
                parts.append("\n## TTS Providers\n")
                tts_using = self.context.get_using_tts_provider(umo=umo)
                for i, d in enumerate(tts_data):
                    line = f"{i + 1}. {d['info']}{d['mark']}"
                    if tts_using and tts_using.meta().id == d["provider"].meta().id:
                        line += " 👈"
                    parts.append(line + "\n")

            if stt_data:
                parts.append("\n## STT Providers\n")
                stt_using = self.context.get_using_stt_provider(umo=umo)
                for i, d in enumerate(stt_data):
                    line = f"{i + 1}. {d['info']}{d['mark']}"
                    if stt_using and stt_using.meta().id == d["provider"].meta().id:
                        line += " 👈"
                    parts.append(line + "\n")

            parts.append("\nUse /provider <idx> to switch LLM providers.")
            ret = "".join(parts)

            if ttss:
                ret += "\nUse /provider tts <idx> to switch TTS providers."
            if stts:
                ret += "\nUse /provider stt <idx> to switch STT providers."

            event.set_result(MessageEventResult().message(ret))
        elif idx == "tts":
            if idx2 is None:
                event.set_result(
                    MessageEventResult().message("Please enter the index.")
                )
                return
            if idx2 > len(self.context.get_all_tts_providers()) or idx2 < 1:
                event.set_result(
                    MessageEventResult().message("❌ Invalid provider index.")
                )
                return
            provider = self.context.get_all_tts_providers()[idx2 - 1]
            id_ = provider.meta().id
            await self.context.provider_manager.set_provider(
                provider_id=id_,
                provider_type=ProviderType.TEXT_TO_SPEECH,
                umo=umo,
            )
            event.set_result(
                MessageEventResult().message(f"✅ Successfully switched to {id_}.")
            )
        elif idx == "stt":
            if idx2 is None:
                event.set_result(
                    MessageEventResult().message("Please enter the index.")
                )
                return
            if idx2 > len(self.context.get_all_stt_providers()) or idx2 < 1:
                event.set_result(
                    MessageEventResult().message("❌ Invalid provider index.")
                )
                return
            provider = self.context.get_all_stt_providers()[idx2 - 1]
            id_ = provider.meta().id
            await self.context.provider_manager.set_provider(
                provider_id=id_,
                provider_type=ProviderType.SPEECH_TO_TEXT,
                umo=umo,
            )
            event.set_result(
                MessageEventResult().message(f"✅ Successfully switched to {id_}.")
            )
        elif isinstance(idx, int):
            if idx > len(self.context.get_all_providers()) or idx < 1:
                event.set_result(
                    MessageEventResult().message("❌ Invalid provider index.")
                )
                return
            provider = self.context.get_all_providers()[idx - 1]
            id_ = provider.meta().id
            await self.context.provider_manager.set_provider(
                provider_id=id_,
                provider_type=ProviderType.CHAT_COMPLETION,
                umo=umo,
            )
            event.set_result(
                MessageEventResult().message(f"✅ Successfully switched to {id_}.")
            )
        else:
            event.set_result(MessageEventResult().message("❌ Invalid parameter."))
