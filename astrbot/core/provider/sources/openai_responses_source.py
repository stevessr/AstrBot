import json
from collections.abc import AsyncGenerator
from typing import Any

from openai.types.responses.response import Response

import astrbot.core.message.components as Comp
from astrbot import logger
from astrbot.core.agent.tool import ToolSet
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.provider.entities import LLMResponse, TokenUsage

from ..register import register_provider_adapter
from .openai_source import ProviderOpenAIOfficial


@register_provider_adapter(
    "openai_responses",
    "OpenAI API Responses 提供商适配器",
)
class ProviderOpenAIResponses(ProviderOpenAIOfficial):
    def _convert_openai_tools_to_responses(
        self,
        tools: list[dict] | None,
    ) -> list[dict]:
        if not tools:
            return []
        converted_tools: list[dict] = []
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            if tool.get("type") != "function":
                continue
            function = tool.get("function")
            if not isinstance(function, dict):
                continue
            name = function.get("name")
            if not isinstance(name, str) or not name:
                continue
            converted_tool: dict[str, Any] = {
                "type": "function",
                "name": name,
                "parameters": function.get("parameters")
                or {
                    "type": "object",
                    "properties": {},
                },
                "strict": False,
            }
            description = function.get("description")
            if isinstance(description, str) and description.strip():
                converted_tool["description"] = description
            converted_tools.append(converted_tool)
        return converted_tools

    def _convert_message_content_for_responses(self, content: Any) -> list[dict]:
        if isinstance(content, str):
            if not content:
                return []
            return [{"type": "input_text", "text": content}]
        if not isinstance(content, list):
            if content is None:
                return []
            return [{"type": "input_text", "text": str(content)}]

        converted_content: list[dict] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            part_type = part.get("type")
            if part_type == "text":
                converted_content.append(
                    {
                        "type": "input_text",
                        "text": str(part.get("text") or ""),
                    }
                )
            elif part_type == "image_url":
                image_url = part.get("image_url")
                if isinstance(image_url, dict):
                    image_url = image_url.get("url")
                if isinstance(image_url, str) and image_url:
                    converted_content.append(
                        {
                            "type": "input_image",
                            "image_url": image_url,
                            "detail": "auto",
                        }
                    )
        return converted_content

    def _convert_messages_to_responses_input(self, messages: list[dict]) -> list[dict]:
        responses_input: list[dict] = []

        for message in messages:
            if not isinstance(message, dict):
                continue
            role = message.get("role")
            if role == "assistant":
                content_blocks = self._convert_message_content_for_responses(
                    message.get("content")
                )
                if content_blocks:
                    responses_input.append(
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": content_blocks,
                        }
                    )

                tool_calls = message.get("tool_calls")
                if isinstance(tool_calls, list):
                    for tool_call in tool_calls:
                        if isinstance(tool_call, str):
                            try:
                                tool_call = json.loads(tool_call)
                            except Exception:
                                continue
                        if not isinstance(tool_call, dict):
                            continue
                        if tool_call.get("type") != "function":
                            continue
                        function = tool_call.get("function")
                        if not isinstance(function, dict):
                            continue
                        call_id = tool_call.get("id")
                        name = function.get("name")
                        arguments = function.get("arguments")
                        if not isinstance(call_id, str) or not isinstance(name, str):
                            continue
                        if isinstance(arguments, dict):
                            arguments = json.dumps(arguments, ensure_ascii=False)
                        elif arguments is None:
                            arguments = "{}"
                        elif not isinstance(arguments, str):
                            arguments = str(arguments)
                        responses_input.append(
                            {
                                "type": "function_call",
                                "call_id": call_id,
                                "name": name,
                                "arguments": arguments,
                            }
                        )
                continue

            if role == "tool":
                call_id = message.get("tool_call_id")
                if not isinstance(call_id, str) or not call_id:
                    continue
                output = message.get("content")
                if output is None:
                    output = ""
                elif not isinstance(output, str):
                    output = str(output)
                responses_input.append(
                    {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": output,
                    }
                )
                continue

            if role in {"user", "system", "developer"}:
                content_blocks = self._convert_message_content_for_responses(
                    message.get("content")
                )
                if not content_blocks:
                    continue
                responses_input.append(
                    {
                        "type": "message",
                        "role": role,
                        "content": content_blocks,
                    }
                )

        return responses_input

    def _extract_usage_from_response(self, usage: Any) -> TokenUsage | None:
        if usage is None:
            return None

        input_tokens = getattr(usage, "input_tokens", None)
        output_tokens = getattr(usage, "output_tokens", None)

        input_other = int(input_tokens or 0)
        output = int(output_tokens or 0)
        cached_tokens = 0

        input_tokens_details = getattr(usage, "input_tokens_details", None)
        if input_tokens_details is not None:
            cached_tokens = int(getattr(input_tokens_details, "cached_tokens", 0) or 0)

        return TokenUsage(
            input_other=max(input_other - cached_tokens, 0),
            input_cached=max(cached_tokens, 0),
            output=max(output, 0),
        )

    def _parse_openai_response(
        self, response: Response, tools: ToolSet | None
    ) -> LLMResponse:
        llm_response = LLMResponse("assistant")

        completion_text = self._normalize_content(response.output_text)
        if completion_text:
            llm_response.result_chain = MessageChain().message(completion_text)

        reasoning_segments: list[str] = []
        function_call_args: list[dict[str, Any]] = []
        function_call_names: list[str] = []
        function_call_ids: list[str] = []

        for output_item in response.output:
            output_type = getattr(output_item, "type", None)
            if output_type == "reasoning":
                summary = getattr(output_item, "summary", None)
                if isinstance(summary, list):
                    for summary_item in summary:
                        text = getattr(summary_item, "text", None)
                        if text:
                            reasoning_segments.append(str(text))
                content = getattr(output_item, "content", None)
                if isinstance(content, list):
                    for content_item in content:
                        text = getattr(content_item, "text", None)
                        if text:
                            reasoning_segments.append(str(text))
                encrypted_content = getattr(output_item, "encrypted_content", None)
                if encrypted_content:
                    llm_response.reasoning_signature = str(encrypted_content)
            elif output_type == "function_call":
                call_id = getattr(output_item, "call_id", None)
                name = getattr(output_item, "name", None)
                arguments_raw = getattr(output_item, "arguments", None)
                if (
                    not isinstance(call_id, str)
                    or not isinstance(name, str)
                    or tools is None
                ):
                    continue
                matched_tool = any(tool.name == name for tool in tools.func_list)
                if not matched_tool:
                    continue
                if isinstance(arguments_raw, str):
                    arguments = json.loads(arguments_raw)
                elif isinstance(arguments_raw, dict):
                    arguments = arguments_raw
                else:
                    arguments = {}
                function_call_ids.append(call_id)
                function_call_names.append(name)
                function_call_args.append(arguments)

        llm_response.reasoning_content = "\n".join(reasoning_segments).strip()

        if function_call_ids:
            llm_response.role = "tool"
            llm_response.tools_call_ids = function_call_ids
            llm_response.tools_call_name = function_call_names
            llm_response.tools_call_args = function_call_args

        if response.error is not None:
            raise Exception(f"Responses API 返回错误: {response.error}")

        if not llm_response.completion_text and not llm_response.tools_call_args:
            logger.error(f"Responses API 返回结果无法解析：{response}。")
            raise Exception(f"Responses API 返回结果无法解析：{response}。")

        llm_response.raw_completion = response
        llm_response.id = response.id
        llm_response.usage = self._extract_usage_from_response(response.usage)

        return llm_response

    def _convert_chat_payload_to_responses_request(
        self,
        payloads: dict,
        tools: ToolSet | None,
    ) -> tuple[dict, list[dict]]:
        payloads_copy = payloads.copy()
        messages = payloads_copy.pop("messages", [])
        responses_input = self._convert_messages_to_responses_input(messages)

        request_payload: dict[str, Any] = {
            "model": payloads_copy.get("model"),
            "input": responses_input,
        }

        if "temperature" in payloads_copy:
            request_payload["temperature"] = payloads_copy["temperature"]
        if "top_p" in payloads_copy:
            request_payload["top_p"] = payloads_copy["top_p"]
        if "max_tokens" in payloads_copy:
            request_payload["max_output_tokens"] = payloads_copy["max_tokens"]
        if "max_completion_tokens" in payloads_copy:
            request_payload["max_output_tokens"] = payloads_copy[
                "max_completion_tokens"
            ]

        if tools:
            model_name = request_payload.get("model", "")
            omit_empty_param_field = "gemini" in str(model_name).lower()
            openai_tools = tools.openai_schema(
                omit_empty_parameter_field=omit_empty_param_field,
            )
            converted_tools = self._convert_openai_tools_to_responses(openai_tools)
            if converted_tools:
                request_payload["tools"] = converted_tools

        custom_extra_body = self.provider_config.get("custom_extra_body", {})
        if isinstance(custom_extra_body, dict):
            request_payload.update(custom_extra_body)

        return request_payload, responses_input

    async def _query_responses(
        self, payloads: dict, tools: ToolSet | None
    ) -> LLMResponse:
        request_payload, _ = self._convert_chat_payload_to_responses_request(
            payloads, tools
        )
        completion = await self.client.responses.create(
            **request_payload,
            stream=False,
        )

        if not isinstance(completion, Response):
            raise Exception(
                f"Responses API 返回类型错误：{type(completion)}: {completion}。",
            )

        logger.debug(f"responses completion: {completion}")

        return self._parse_openai_response(completion, tools)

    async def _query_stream_responses(
        self,
        payloads: dict,
        tools: ToolSet | None,
    ) -> AsyncGenerator[LLMResponse, None]:
        request_payload, _ = self._convert_chat_payload_to_responses_request(
            payloads, tools
        )
        stream = await self.client.responses.create(
            **request_payload,
            stream=True,
        )

        async for event in stream:
            event_type = getattr(event, "type", "")
            if event_type == "response.output_text.delta":
                delta_text = getattr(event, "delta", None) or getattr(
                    event, "text", None
                )
                if delta_text:
                    yield LLMResponse(
                        "assistant",
                        result_chain=MessageChain(chain=[Comp.Plain(str(delta_text))]),
                        is_chunk=True,
                        id=getattr(event, "item_id", None),
                    )
            elif event_type in {
                "response.reasoning_summary_text.delta",
                "response.reasoning_summary_text.done",
                "response.reasoning_text.delta",
                "response.reasoning_text.done",
            }:
                reasoning_delta = getattr(event, "delta", None) or getattr(
                    event, "text", None
                )
                if reasoning_delta:
                    yield LLMResponse(
                        "assistant",
                        reasoning_content=str(reasoning_delta),
                        is_chunk=True,
                        id=getattr(event, "item_id", None),
                    )
            elif event_type == "response.completed":
                response_obj = getattr(event, "response", None)
                if isinstance(response_obj, Response):
                    yield self._parse_openai_response(response_obj, tools)
                    return
            elif event_type in {
                "response.failed",
                "response.incomplete",
                "response.error",
            }:
                error_obj = getattr(event, "error", None) or getattr(
                    event, "response", None
                )
                raise Exception(f"Responses stream 失败: {error_obj}")

        raise Exception("Responses stream 未返回最终完成事件。")

    async def _query(self, payloads: dict, tools: ToolSet | None) -> LLMResponse:
        return await self._query_responses(payloads, tools)

    async def _query_stream(
        self,
        payloads: dict,
        tools: ToolSet | None,
    ) -> AsyncGenerator[LLMResponse, None]:
        async for item in self._query_stream_responses(payloads, tools):
            yield item
