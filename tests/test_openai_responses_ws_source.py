import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
import websockets
from openai.types.responses import Response
from websockets.exceptions import ConnectionClosed

from astrbot.core.config.default import CONFIG_METADATA_2
from astrbot.core.provider.sources.openai_responses_ws_source import (
    ProviderOpenAIResponsesWS,
)


def _make_provider(
    overrides: dict | None = None,
    base_override: str | None = None,
) -> ProviderOpenAIResponsesWS:
    provider_config = {
        "id": "test-responses-ws",
        "provider": "openai",
        "type": "openai_responses_ws",
        "model": "gpt-test",
        "key": ["test-key"],
        "api_base": base_override or "https://api.openai.com/v1",
    }
    if overrides:
        provider_config.update(overrides)
    return ProviderOpenAIResponsesWS(provider_config, {})


def _make_response(output: list[dict], **overrides) -> Response:
    payload = {
        "id": "resp_1",
        "object": "response",
        "created_at": 1,
        "status": "completed",
        "model": "gpt-test",
        "output": output,
        "usage": {
            "input_tokens": 10,
            "input_tokens_details": {
                "cached_tokens": 3,
                "cache_write_tokens": 0,
            },
            "output_tokens": 4,
            "output_tokens_details": {"reasoning_tokens": 2},
            "total_tokens": 14,
        },
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
    }
    payload.update(overrides)
    return Response.model_validate(payload)


def _as_dict(response: Response) -> dict:
    return response.model_dump(mode="json", exclude_none=True)


@asynccontextmanager
async def _serve_events(events: list[dict]):
    """Run a mock Responses WebSocket server.

    Args:
        events: Events sent after every received ``response.create`` request.

    Yields:
        The server port and mutable connection/request statistics.
    """
    stats: dict = {"authorization": [], "connections": 0, "received": []}

    async def handler(websocket) -> None:
        stats["connections"] += 1
        stats["authorization"].append(websocket.request.headers["Authorization"])
        try:
            while True:
                raw = await websocket.recv()
                request = json.loads(raw)
                stats["received"].append(request)
                for event in events:
                    response_event = dict(event)
                    response_event["stream_id"] = request.get("stream_id")
                    await websocket.send(json.dumps(response_event))
        except ConnectionClosed:
            return

    server = await websockets.serve(handler, "127.0.0.1", 0)
    try:
        port = server.sockets[0].getsockname()[1]
        yield port, stats
    finally:
        server.close()
        await server.wait_closed()


def test_responses_ws_provider_template_is_registered():
    templates = CONFIG_METADATA_2["provider_group"]["metadata"]["provider"][
        "config_template"
    ]

    assert templates["OpenAI Responses WS"]["type"] == "openai_responses_ws"
    assert templates["OpenAI Responses WS"]["api_base"] == "https://api.openai.com/v1"


@pytest.mark.asyncio
async def test_text_chat_continues_incrementally_and_reuses_websocket():
    final = _make_response(
        [
            {
                "type": "message",
                "id": "msg_1",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": "hello ws", "annotations": []},
                ],
            }
        ]
    )
    events = [
        {"type": "response.created", "response": {"id": "resp_1"}},
        {"type": "response.completed", "response": _as_dict(final)},
    ]

    async with _serve_events(events) as (port, stats):
        provider = _make_provider(base_override=f"http://127.0.0.1:{port}/v1")
        try:
            first = await provider.text_chat(prompt="first", session_id="session-1")
            second = await provider.text_chat(
                prompt="second",
                session_id="session-1",
                contexts=[
                    {"role": "user", "content": "first"},
                    {"role": "assistant", "content": "hello ws"},
                ],
            )

            assert first.completion_text == "hello ws"
            assert first.usage is not None
            assert first.usage.output == 4
            assert second.completion_text == "hello ws"
            assert stats["connections"] == 1
            assert stats["authorization"] == ["Bearer test-key"]
            assert len(stats["received"]) == 2
            payload = stats["received"][0]
            assert payload["type"] == "response.create"
            assert payload["stream_id"].startswith("astrbot_")
            assert payload["store"] is False
            assert payload["model"] == "gpt-test"
            assert payload["input"] == [
                {"type": "message", "role": "user", "content": "first"}
            ]
            continuation = stats["received"][1]
            assert continuation["stream_id"] == payload["stream_id"]
            assert continuation["previous_response_id"] == "resp_1"
            assert continuation["input"] == [
                {"type": "message", "role": "user", "content": "second"}
            ]
        finally:
            await provider.terminate()


@pytest.mark.asyncio
async def test_text_chat_stream_yields_deltas_then_final_response():
    final = _make_response(
        [
            {
                "type": "message",
                "id": "msg_1",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": "hello", "annotations": []},
                ],
            }
        ]
    )
    events = [
        {"type": "response.created", "response": {"id": "resp_1"}},
        {"type": "response.reasoning_text.delta", "delta": "think"},
        {"type": "response.output_text.delta", "delta": "hel"},
        {"type": "response.output_text.delta", "delta": "lo"},
        {"type": "response.completed", "response": _as_dict(final)},
    ]

    async with _serve_events(events) as (port, _):
        provider = _make_provider(base_override=f"http://127.0.0.1:{port}/v1")
        try:
            results = [
                result async for result in provider.text_chat_stream(prompt="hi")
            ]
        finally:
            await provider.terminate()

    assert len(results) == 4
    assert results[0].is_chunk is True
    assert results[0].reasoning_content == "think"
    assert results[1].is_chunk is True
    assert results[1].completion_text == "hel"
    assert results[2].completion_text == "lo"
    assert results[3].is_chunk is False
    assert results[3].completion_text == "hello"
    assert results[3].usage.output == 4


@pytest.mark.asyncio
async def test_concurrent_sessions_are_multiplexed_on_one_connection():
    final = _make_response(
        [
            {
                "type": "message",
                "id": "msg_1",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": "hello ws", "annotations": []},
                ],
            }
        ]
    )
    events = [{"type": "response.completed", "response": _as_dict(final)}]

    async with _serve_events(events) as (port, stats):
        provider = _make_provider(base_override=f"http://127.0.0.1:{port}/v1")
        try:
            results = await asyncio.gather(
                provider.text_chat(prompt="one", session_id="session-one"),
                provider.text_chat(prompt="two", session_id="session-two"),
            )
        finally:
            await provider.terminate()

    assert [result.completion_text for result in results] == ["hello ws", "hello ws"]
    assert stats["connections"] == 1
    assert len(stats["received"]) == 2
    assert {payload["stream_id"] for payload in stats["received"]} == {
        provider._stream_id_for_session("session-one"),
        provider._stream_id_for_session("session-two"),
    }


@pytest.mark.asyncio
async def test_query_flattens_tools_and_parses_function_call():
    final = _make_response(
        [
            {
                "type": "function_call",
                "id": "fc_1",
                "call_id": "call_1",
                "name": "weather",
                "arguments": '{"city":"Shenzhen"}',
                "status": "completed",
            }
        ]
    )
    events = [{"type": "response.completed", "response": _as_dict(final)}]
    tools = SimpleNamespace(
        empty=lambda: False,
        openai_schema=lambda: [
            {
                "type": "function",
                "function": {
                    "name": "weather",
                    "description": "Get weather",
                    "parameters": {
                        "type": "object",
                        "properties": {"city": {"type": "string"}},
                    },
                },
            }
        ],
    )

    async with _serve_events(events) as (port, stats):
        provider = _make_provider(base_override=f"http://127.0.0.1:{port}/v1")
        try:
            result = await provider._query(
                {"model": "gpt-test", "input": "weather", "store": False},
                tools,
            )
        finally:
            await provider.terminate()

    assert stats["received"][0]["tools"] == [
        {
            "type": "function",
            "name": "weather",
            "description": "Get weather",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
            },
        }
    ]
    assert result.role == "tool"
    assert result.tools_call_name == ["weather"]
    assert result.tools_call_args == [{"city": "Shenzhen"}]
    assert result.tools_call_ids == ["call_1"]


@pytest.mark.asyncio
async def test_tool_continuation_keeps_tool_output_but_omits_old_function_call():
    tool_response = _make_response(
        [
            {
                "type": "function_call",
                "id": "fc_1",
                "call_id": "call_1",
                "name": "weather",
                "arguments": '{"city":"Shenzhen"}',
                "status": "completed",
            }
        ]
    )
    events = [{"type": "response.completed", "response": _as_dict(tool_response)}]
    tools = SimpleNamespace(
        empty=lambda: False,
        openai_schema=lambda: [
            {
                "type": "function",
                "function": {
                    "name": "weather",
                    "description": "Get weather",
                    "parameters": {"type": "object"},
                },
            }
        ],
    )

    async with _serve_events(events) as (port, stats):
        provider = _make_provider(base_override=f"http://127.0.0.1:{port}/v1")
        try:
            await provider.text_chat(
                prompt="call weather",
                session_id="tool-session",
                func_tool=tools,
            )
            await provider.text_chat(
                prompt="what did it say?",
                session_id="tool-session",
                func_tool=tools,
                contexts=[
                    {"role": "user", "content": "call weather"},
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "weather",
                                    "arguments": '{"city":"Shenzhen"}',
                                },
                            }
                        ],
                    },
                    {
                        "role": "tool",
                        "tool_call_id": "call_1",
                        "content": "sunny",
                    },
                ],
            )
        finally:
            await provider.terminate()

    continuation = stats["received"][1]
    assert continuation["previous_response_id"] == "resp_1"
    assert continuation["input"] == [
        {"type": "function_call_output", "call_id": "call_1", "output": "sunny"},
        {
            "type": "message",
            "role": "user",
            "content": "what did it say?",
        },
    ]


@pytest.mark.asyncio
async def test_reconnect_replays_full_context_without_previous_response_id():
    final = _make_response(
        [
            {
                "type": "message",
                "id": "msg_1",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": "hello ws", "annotations": []},
                ],
            }
        ]
    )
    events = [{"type": "response.completed", "response": _as_dict(final)}]

    async with _serve_events(events) as (port, stats):
        provider = _make_provider(base_override=f"http://127.0.0.1:{port}/v1")
        try:
            await provider.text_chat(prompt="first", session_id="reconnect-session")
            connection = next(iter(provider._connections.values()))[0]
            await provider._drop_connection(connection)
            await provider.text_chat(
                prompt="second",
                session_id="reconnect-session",
                contexts=[
                    {"role": "user", "content": "first"},
                    {"role": "assistant", "content": "hello ws"},
                ],
            )
        finally:
            await provider.terminate()

    assert stats["connections"] == 2
    replay = stats["received"][1]
    assert "previous_response_id" not in replay
    assert replay["input"] == [
        {"type": "message", "role": "user", "content": "first"},
        {"type": "message", "role": "assistant", "content": "hello ws"},
        {"type": "message", "role": "user", "content": "second"},
    ]


@pytest.mark.asyncio
async def test_official_nested_error_event_raises_runtime_error():
    events = [
        {
            "type": "error",
            "status": 400,
            "stream_id": "main",
            "error": {
                "type": "invalid_request_error",
                "code": "previous_response_not_found",
                "message": "Previous response not found",
                "param": "previous_response_id",
            },
        }
    ]

    async with _serve_events(events) as (port, _):
        provider = _make_provider(base_override=f"http://127.0.0.1:{port}/v1")
        try:
            with pytest.raises(RuntimeError, match="previous_response_not_found"):
                await provider._query(
                    {"model": "gpt-test", "input": "hi", "store": False},
                    tools=None,
                )
        finally:
            await provider.terminate()


@pytest.mark.asyncio
async def test_query_times_out_when_server_sends_no_events():
    async with _serve_events([]) as (port, _):
        provider = _make_provider(
            overrides={"timeout": 0.05},
            base_override=f"http://127.0.0.1:{port}/v1",
        )
        try:
            with pytest.raises(TimeoutError):
                await provider._query(
                    {"model": "gpt-test", "input": "hi", "store": False},
                    tools=None,
                )
            assert provider._connections == {}
        finally:
            await provider.terminate()


def test_ws_url_derivation():
    provider = _make_provider(base_override="https://api.openai.com/v1")
    assert provider._get_ws_url() == "wss://api.openai.com/v1/responses"

    provider = _make_provider(base_override="http://localhost:8000/v1")
    assert provider._get_ws_url() == "ws://localhost:8000/v1/responses"

    provider = _make_provider(
        base_override="https://api.openai.com/v1",
        overrides={"ws_api_base": "wss://proxy.example.com/v1/responses"},
    )
    assert provider._get_ws_url() == "wss://proxy.example.com/v1/responses"


def test_prepare_ws_payload_merges_extra_body_and_normalises():
    provider = _make_provider(
        overrides={
            "custom_extra_body": {
                "metadata": {"k": "v"},
                "background": True,
                "extra_headers": {"X-Body-Header": "invalid"},
                "stream_options": {"include_obfuscation": False},
            }
        }
    )
    payload = {
        "input": [{"type": "message", "role": "user", "content": "hi"}],
        "model": "gpt-test",
        "store": True,
        "max_tokens": 100,
        "reasoning_effort": "high",
        "stream": True,
        "timeout": 10,
        "extra_body": {"generate": False},
    }
    out = provider._prepare_ws_payload(payload)
    assert out["type"] == "response.create"
    assert out["stream_id"].startswith("request_")
    assert out["store"] is False
    assert "background" not in out
    assert "extra_headers" not in out
    assert "stream" not in out
    assert "stream_options" not in out
    assert "timeout" not in out
    assert out["generate"] is False
    assert out["max_output_tokens"] == 100
    assert "max_tokens" not in out
    assert out["reasoning"] == {"effort": "high"}
    assert "reasoning_effort" not in out
    assert out["metadata"] == {"k": "v"}
