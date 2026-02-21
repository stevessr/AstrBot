import asyncio
from typing import Any

import pytest
from openai.types.responses.response import Response
from openai.types.responses.response_completed_event import ResponseCompletedEvent
from openai.types.responses.response_function_tool_call import ResponseFunctionToolCall
from openai.types.responses.response_output_message import ResponseOutputMessage
from openai.types.responses.response_output_text import ResponseOutputText
from openai.types.responses.response_reasoning_item import (
    Content as ReasoningContent,
)
from openai.types.responses.response_reasoning_item import (
    ResponseReasoningItem,
)
from openai.types.responses.response_reasoning_item import (
    Summary as ReasoningSummary,
)
from openai.types.responses.response_reasoning_summary_text_delta_event import (
    ResponseReasoningSummaryTextDeltaEvent,
)
from openai.types.responses.response_text_delta_event import ResponseTextDeltaEvent
from openai.types.responses.response_usage import (
    InputTokensDetails,
    OutputTokensDetails,
    ResponseUsage,
)

from astrbot.core.agent.tool import FunctionTool, ToolSet
from astrbot.core.provider.entities import LLMResponse
from astrbot.core.provider.sources.openai_responses_source import (
    ProviderOpenAIResponses,
)


def _make_provider(overrides: dict | None = None) -> ProviderOpenAIResponses:
    provider_config = {
        "id": "test-openai-responses",
        "type": "openai_responses",
        "model": "gpt-4o-mini",
        "key": ["test-key"],
    }
    if overrides:
        provider_config.update(overrides)
    return ProviderOpenAIResponses(
        provider_config=provider_config,
        provider_settings={},
    )


def _make_tool_set() -> ToolSet:
    return ToolSet(
        tools=[
            FunctionTool(
                name="weather",
                description="Get weather",
                parameters={
                    "type": "object",
                    "properties": {
                        "city": {"type": "string"},
                    },
                    "required": ["city"],
                },
            )
        ]
    )


def _make_responses_completion(
    *,
    with_text: bool = True,
    with_reasoning: bool = False,
    with_function_call: bool = False,
    function_name: str = "weather",
    function_args: str = '{"city":"beijing"}',
    with_usage: bool = True,
) -> Response:
    output_items: list[Any] = []
    if with_text:
        output_items.append(
            ResponseOutputMessage.model_construct(
                id="msg_1",
                content=[
                    ResponseOutputText.model_construct(
                        annotations=[],
                        text="hello from responses",
                        type="output_text",
                    )
                ],
                role="assistant",
                status="completed",
                type="message",
            )
        )

    if with_reasoning:
        output_items.append(
            ResponseReasoningItem.model_construct(
                id="rs_1",
                summary=[
                    ReasoningSummary.model_construct(
                        text="reason summary",
                        type="summary_text",
                    )
                ],
                type="reasoning",
                content=[
                    ReasoningContent.model_construct(
                        text="reason content",
                        type="reasoning_text",
                    )
                ],
                encrypted_content="signature-1",
                status="completed",
            )
        )

    if with_function_call:
        output_items.append(
            ResponseFunctionToolCall.model_construct(
                arguments=function_args,
                call_id="call_1",
                name=function_name,
                type="function_call",
                id="fc_1",
                status="completed",
            )
        )

    usage = None
    if with_usage:
        usage = ResponseUsage.model_construct(
            input_tokens=120,
            input_tokens_details=InputTokensDetails.model_construct(cached_tokens=20),
            output_tokens=40,
            output_tokens_details=OutputTokensDetails.model_construct(
                reasoning_tokens=0
            ),
            total_tokens=160,
        )

    return Response.model_construct(
        id="resp_1",
        created_at=0,
        error=None,
        incomplete_details=None,
        instructions=None,
        metadata=None,
        model="gpt-4o-mini",
        object="response",
        output=output_items,
        parallel_tool_calls=True,
        temperature=1.0,
        tool_choice="auto",
        tools=[],
        top_p=1.0,
        background=False,
        completed_at=0,
        conversation=None,
        max_output_tokens=None,
        max_tool_calls=None,
        previous_response_id=None,
        prompt=None,
        prompt_cache_key=None,
        prompt_cache_retention=None,
        reasoning=None,
        safety_identifier=None,
        service_tier="default",
        status="completed",
        text=None,
        top_logprobs=0,
        truncation="disabled",
        usage=usage,
        user=None,
    )


class _AsyncEventStream:
    def __init__(self, events: list[Any]):
        self._events = events

    def __aiter__(self):
        self._iter = iter(self._events)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


@pytest.mark.asyncio
async def test_query_prefers_responses(monkeypatch):
    provider = _make_provider()
    try:
        called = {"responses": 0}

        async def fake_responses(payloads, tools):
            called["responses"] += 1
            return LLMResponse("assistant", completion_text="responses")

        monkeypatch.setattr(provider, "_query_responses", fake_responses)

        resp = await provider._query({"model": "gpt-4o-mini", "messages": []}, None)

        assert resp.completion_text == "responses"
        assert called == {"responses": 1}
    finally:
        await provider.terminate()


@pytest.mark.asyncio
async def test_query_errors_when_responses_unsupported(monkeypatch):
    provider = _make_provider()
    try:
        called = {"responses": 0}

        async def fake_responses(payloads, tools):
            called["responses"] += 1
            raise Exception("unsupported responses endpoint")

        monkeypatch.setattr(provider, "_query_responses", fake_responses)

        with pytest.raises(Exception, match="unsupported responses endpoint"):
            await provider._query({"model": "gpt-4o-mini", "messages": []}, None)

        assert called == {"responses": 1}
    finally:
        await provider.terminate()


@pytest.mark.asyncio
async def test_query_stream_errors_when_responses_unsupported(monkeypatch):
    provider = _make_provider()
    try:
        called = {"responses": 0}

        async def fake_responses_stream(payloads, tools):
            called["responses"] += 1
            raise Exception("responses endpoint not found")
            yield  # pragma: no cover

        monkeypatch.setattr(provider, "_query_stream_responses", fake_responses_stream)

        with pytest.raises(Exception, match="responses endpoint not found"):
            async for _ in provider._query_stream(
                {"model": "gpt-4o-mini", "messages": []}, None
            ):
                pass

        assert called == {"responses": 1}
    finally:
        await provider.terminate()


@pytest.mark.asyncio
async def test_responses_provider_registered():
    provider = _make_provider()
    try:
        meta = provider.meta()
        assert meta.type == "openai_responses"
    finally:
        await provider.terminate()


@pytest.mark.asyncio
async def test_parse_openai_response_maps_function_call_and_usage():
    provider = _make_provider()
    try:
        completion = _make_responses_completion(
            with_text=False,
            with_reasoning=False,
            with_function_call=True,
            with_usage=True,
        )
        llm_resp = provider._parse_openai_response(completion, _make_tool_set())

        assert llm_resp.role == "tool"
        assert llm_resp.tools_call_name == ["weather"]
        assert llm_resp.tools_call_ids == ["call_1"]
        assert llm_resp.tools_call_args == [{"city": "beijing"}]
        assert llm_resp.usage is not None
        assert llm_resp.usage.input_other == 100
        assert llm_resp.usage.input_cached == 20
        assert llm_resp.usage.output == 40
    finally:
        await provider.terminate()


@pytest.mark.asyncio
async def test_parse_openai_response_maps_text_and_reasoning():
    provider = _make_provider()
    try:
        completion = _make_responses_completion(
            with_text=True,
            with_reasoning=True,
            with_function_call=False,
            with_usage=False,
        )

        llm_resp = provider._parse_openai_response(completion, _make_tool_set())

        assert llm_resp.role == "assistant"
        assert llm_resp.completion_text == "hello from responses"
        assert "reason summary" in llm_resp.reasoning_content
        assert "reason content" in llm_resp.reasoning_content
        assert llm_resp.reasoning_signature == "signature-1"
    finally:
        await provider.terminate()


@pytest.mark.asyncio
async def test_query_stream_responses_yields_chunks_and_final(monkeypatch):
    provider = _make_provider()
    try:
        final_response = _make_responses_completion(
            with_text=True,
            with_reasoning=True,
            with_function_call=False,
            with_usage=False,
        )
        events = [
            ResponseTextDeltaEvent.model_construct(
                content_index=0,
                delta="hel",
                item_id="msg_1",
                logprobs=[],
                output_index=0,
                sequence_number=1,
                type="response.output_text.delta",
            ),
            ResponseReasoningSummaryTextDeltaEvent.model_construct(
                delta="think",
                item_id="rs_1",
                output_index=1,
                sequence_number=2,
                summary_index=0,
                type="response.reasoning_summary_text.delta",
            ),
            ResponseCompletedEvent.model_construct(
                response=final_response,
                sequence_number=3,
                type="response.completed",
            ),
        ]

        async def fake_create(**kwargs):
            assert kwargs["stream"] is True
            return _AsyncEventStream(events)

        monkeypatch.setattr(provider.client.responses, "create", fake_create)

        payloads = {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hello"}],
        }
        chunks = []
        async for item in provider._query_stream_responses(payloads, _make_tool_set()):
            chunks.append(item)

        assert len(chunks) == 3
        assert chunks[0].is_chunk is True
        assert chunks[0].completion_text == "hel"
        assert chunks[1].is_chunk is True
        assert chunks[1].reasoning_content == "think"
        assert chunks[2].is_chunk is False
        assert chunks[2].completion_text == "hello from responses"
    finally:
        await provider.terminate()


@pytest.mark.asyncio
async def test_convert_messages_to_responses_input_handles_tool_history():
    provider = _make_provider()
    try:
        messages = [
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "calling tool"}],
                "tool_calls": [
                    {
                        "type": "function",
                        "id": "call_1",
                        "function": {
                            "name": "weather",
                            "arguments": '{"city":"beijing"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "content": "晴天",
            },
        ]

        converted = provider._convert_messages_to_responses_input(messages)

        assert converted[0]["type"] == "message"
        assert converted[0]["role"] == "assistant"
        assert converted[1] == {
            "type": "function_call",
            "call_id": "call_1",
            "name": "weather",
            "arguments": '{"city":"beijing"}',
        }
        assert converted[2] == {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": "晴天",
        }
    finally:
        await provider.terminate()


def test_no_fallback_helpers_in_responses_provider():
    provider = _make_provider()
    try:
        assert not hasattr(provider, "_is_responses_unsupported_error")
    finally:
        asyncio.run(provider.terminate())
