"""OpenAI Responses API WebSocket provider adapter.

The adapter uses the official WebSocket Mode protocol: one persistent
connection per API key, named ``stream_id`` lanes, and incremental
continuations through ``previous_response_id``.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

import websockets
from openai.types.responses import Response
from websockets.asyncio.client import ClientConnection

import astrbot.core.message.components as Comp
from astrbot.core.agent.tool import ToolSet
from astrbot.core.exceptions import EmptyModelOutputError
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.provider.entities import LLMResponse

from ..register import register_provider_adapter
from .openai_responses_source import ProviderOpenAIResponses

_ACTIVE_SESSION_ID: ContextVar[str | None] = ContextVar(
    "astrbot_openai_responses_ws_session_id",
    default=None,
)


@dataclass(slots=True)
class _WebSocketConnection:
    """Connection-local state used to route multiplexed response events."""

    api_key: str
    socket: ClientConnection
    pending: dict[str, asyncio.Queue[dict | BaseException]] = field(
        default_factory=dict,
    )
    stream_ids: set[str] = field(default_factory=set)
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    reader_task: asyncio.Task[None] | None = None


@dataclass(slots=True)
class _ConversationState:
    """Incremental continuation state for one AstrBot session."""

    stream_id: str
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    response_id: str | None = None
    last_input: list[dict] = field(default_factory=list)
    pending_input: list[dict] | None = None
    connection: _WebSocketConnection | None = None


@register_provider_adapter(
    "openai_responses_ws",
    "OpenAI-compatible Responses API WebSocket provider adapter",
)
class ProviderOpenAIResponsesWS(ProviderOpenAIResponses):
    """OpenAI Responses API adapter using the official WebSocket protocol.

    A connection is shared by all sessions using the same API key. Each
    session gets a stable ``stream_id`` and is serialized by its own lane lock,
    while a background reader routes events from concurrent lanes safely.
    Successful responses are continued incrementally: the next request sends
    only input items added after the previous request and references its
    ``previous_response_id``. The server-side cache is connection-local, so a
    reconnect automatically falls back to a complete replay.
    """

    _RESPONSE_OUTPUT_ITEM_TYPES = frozenset(
        {
            "reasoning",
            "message",
            "compaction",
            "function_call",
            "computer_call",
            "file_search_call",
            "web_search_call",
            "code_interpreter_call",
            "mcp_call",
            "mcp_list_tools",
            "mcp_approval_request",
            "custom_tool_call",
            "apply_patch_call",
            "shell_call",
            "local_shell_call",
            "tool_search_call",
            "image_generation_call",
        }
    )
    _MAX_NAMED_STREAMS_PER_CONNECTION = 32

    def __init__(self, provider_config: dict, provider_settings: dict) -> None:
        """Initialize the Responses WebSocket adapter.

        Args:
            provider_config: Provider source and model configuration.
            provider_settings: Global provider settings.
        """
        super().__init__(provider_config, provider_settings)
        self._connections: dict[str, list[_WebSocketConnection]] = {}
        self._connections_lock = asyncio.Lock()
        self._conversation_states: dict[tuple[str, str], _ConversationState] = {}
        self._state_lock = asyncio.Lock()

    async def text_chat(self, *args: Any, session_id: str | None = None, **kwargs: Any):
        """Run chat while associating the request with an incremental session.

        Args:
            *args: Positional arguments accepted by the parent provider.
            session_id: AstrBot session identifier used for continuation.
            **kwargs: Keyword arguments accepted by the parent provider.

        Returns:
            The normalized AstrBot response.
        """
        active_session_id = session_id
        if active_session_id is None and len(args) > 1:
            active_session_id = args[1]
        token = _ACTIVE_SESSION_ID.set(
            None if active_session_id is None else str(active_session_id),
        )
        try:
            if session_id is None:
                return await super().text_chat(*args, **kwargs)
            return await super().text_chat(
                *args,
                session_id=session_id,
                **kwargs,
            )
        finally:
            _ACTIVE_SESSION_ID.reset(token)

    async def text_chat_stream(
        self,
        *args: Any,
        session_id: str | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[LLMResponse, None]:
        """Stream chat while associating the request with an incremental session.

        Args:
            *args: Positional arguments accepted by the parent provider.
            session_id: AstrBot session identifier used for continuation.
            **kwargs: Keyword arguments accepted by the parent provider.

        Yields:
            Streaming and final normalized responses.
        """
        active_session_id = session_id
        if active_session_id is None and len(args) > 1:
            active_session_id = args[1]
        token = _ACTIVE_SESSION_ID.set(
            None if active_session_id is None else str(active_session_id),
        )
        try:
            if session_id is None:
                async for response in super().text_chat_stream(*args, **kwargs):
                    yield response
            else:
                async for response in super().text_chat_stream(
                    *args,
                    session_id=session_id,
                    **kwargs,
                ):
                    yield response
        finally:
            _ACTIVE_SESSION_ID.reset(token)

    def _get_ws_url(self) -> str:
        """Derive the Responses WebSocket endpoint.

        Returns:
            The configured or derived WebSocket endpoint URL.
        """
        api_base = self.provider_config.get("ws_api_base")
        if not api_base:
            api_base = self.provider_config.get("api_base", "https://api.openai.com/v1")
        api_base = str(api_base or "https://api.openai.com/v1")

        ws_url = api_base.replace("https://", "wss://").replace("http://", "ws://")
        ws_url = ws_url.rstrip("/")
        if not ws_url.endswith("/responses"):
            ws_url += "/responses"
        return ws_url

    async def _connect_ws(self, api_key: str) -> ClientConnection:
        """Create a WebSocket connection to the Responses API endpoint.

        Args:
            api_key: API key used to authenticate the connection.

        Returns:
            An open WebSocket client connection.

        Raises:
            OSError: If the endpoint cannot be reached.
            websockets.WebSocketException: If the WebSocket handshake fails.
        """
        ws_url = self._get_ws_url()
        headers = dict(self.custom_headers or {})
        if not any(key.lower() == "authorization" for key in headers):
            headers["Authorization"] = f"Bearer {api_key}"

        extra_kwargs: dict[str, Any] = {}
        proxy = self.provider_config.get("proxy")
        if proxy:
            extra_kwargs["proxy"] = proxy

        return await websockets.connect(
            ws_url,
            additional_headers=headers,
            open_timeout=self.timeout,
            ping_interval=min(self.timeout, 30),
            ping_timeout=min(self.timeout, 10),
            close_timeout=self.timeout,
            max_size=2 * 1024 * 1024,
            **extra_kwargs,
        )

    @staticmethod
    def _stream_id_for_session(session_id: str) -> str:
        """Create a stable, protocol-safe stream identifier.

        Args:
            session_id: AstrBot session identifier.

        Returns:
            A deterministic stream identifier containing only safe characters.
        """
        digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:48]
        return f"astrbot_{digest}"

    async def _get_conversation_state(self, api_key: str) -> _ConversationState:
        """Get the continuation state for the active session.

        Args:
            api_key: API key selected by the inherited provider retry loop.

        Returns:
            A persistent session state, or an ephemeral state for direct calls
            that do not provide a session ID.
        """
        session_id = _ACTIVE_SESSION_ID.get()
        if session_id is None:
            return _ConversationState(stream_id=f"request_{uuid.uuid4().hex}")

        state_key = (api_key, session_id)
        async with self._state_lock:
            state = self._conversation_states.get(state_key)
            if state is None:
                state = _ConversationState(
                    stream_id=self._stream_id_for_session(session_id),
                )
                self._conversation_states[state_key] = state
            return state

    async def _get_connection(
        self,
        api_key: str,
        stream_id: str,
    ) -> _WebSocketConnection:
        """Get or create the shared connection for an API key.

        Args:
            api_key: API key selected by the inherited provider retry loop.
            stream_id: Named lane that must fit on the selected connection.

        Returns:
            A connection with an active event reader.
        """
        stale_connections: list[_WebSocketConnection] = []
        async with self._connections_lock:
            connections = self._connections.setdefault(api_key, [])
            for connection in list(connections):
                if (
                    connection.socket.close_code is None
                    and connection.reader_task is not None
                    and not connection.reader_task.done()
                    and (
                        stream_id in connection.stream_ids
                        or len(connection.stream_ids)
                        < self._MAX_NAMED_STREAMS_PER_CONNECTION
                    )
                ):
                    connection.stream_ids.add(stream_id)
                    return connection
                if (
                    connection.socket.close_code is not None
                    or connection.reader_task is None
                    or connection.reader_task.done()
                ):
                    connections.remove(connection)
                    stale_connections.append(connection)

            socket = await self._connect_ws(api_key)
            connection = _WebSocketConnection(api_key=api_key, socket=socket)
            connection.stream_ids.add(stream_id)
            connection.reader_task = asyncio.create_task(
                self._read_connection(connection),
                name=f"astrbot-responses-ws-reader-{api_key[:12]}",
            )
            connections.append(connection)

        for stale_connection in stale_connections:
            await self._drop_connection(stale_connection)
        return connection

    async def _read_connection(self, connection: _WebSocketConnection) -> None:
        """Read and route all events received on a multiplexed connection.

        Args:
            connection: Connection state whose socket should be read.
        """
        try:
            while True:
                raw = await connection.socket.recv()
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                event = json.loads(raw)
                if not isinstance(event, dict):
                    raise ValueError("Responses WS event must be a JSON object")

                stream_id = event.get("stream_id")
                if stream_id is not None:
                    queue = connection.pending.get(str(stream_id))
                    if queue is not None:
                        queue.put_nowait(event)
                    continue

                if event.get("type") == "error":
                    for queue in tuple(connection.pending.values()):
                        queue.put_nowait(event)
                elif len(connection.pending) == 1:
                    next(iter(connection.pending.values())).put_nowait(event)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            transport_error = ConnectionError(
                f"Responses WS connection closed: {exc}",
            )
            for queue in tuple(connection.pending.values()):
                queue.put_nowait(transport_error)
        finally:
            async with self._connections_lock:
                connections = self._connections.get(connection.api_key, [])
                for index, candidate in enumerate(connections):
                    if candidate is connection:
                        connections.pop(index)
                        break
                if not connections:
                    self._connections.pop(connection.api_key, None)

    async def _drop_connection(self, connection: _WebSocketConnection) -> None:
        """Remove and close a connection, waking all pending request lanes.

        Args:
            connection: Connection to remove and close.
        """
        async with self._connections_lock:
            connections = self._connections.get(connection.api_key, [])
            for index, candidate in enumerate(connections):
                if candidate is connection:
                    connections.pop(index)
                    break
            if not connections:
                self._connections.pop(connection.api_key, None)

        for queue in tuple(connection.pending.values()):
            queue.put_nowait(ConnectionError("Responses WS connection dropped"))

        reader_task = connection.reader_task
        current_task = asyncio.current_task()
        if reader_task is not None and reader_task is not current_task:
            reader_task.cancel()
            await asyncio.gather(reader_task, return_exceptions=True)
        await connection.socket.close()

    async def _request_events(
        self,
        connection: _WebSocketConnection,
        stream_id: str,
        payload: dict,
    ) -> AsyncIterator[dict]:
        """Send one event and yield only events belonging to its stream lane.

        Args:
            connection: Shared connection used for the request.
            stream_id: Lane identifier used for event routing.
            payload: ``response.create`` event to send.

        Yields:
            Events routed to ``stream_id``.

        Raises:
            TimeoutError: If no event arrives before the provider timeout.
            ConnectionError: If the reader reports a transport failure.
        """
        queue: asyncio.Queue[dict | BaseException] = asyncio.Queue()
        if stream_id in connection.pending:
            raise RuntimeError(f"Responses WS stream is already active: {stream_id}")
        connection.pending[stream_id] = queue
        try:
            try:
                async with connection.send_lock:
                    await connection.socket.send(json.dumps(payload))
            except asyncio.CancelledError:
                raise
            except Exception:
                await self._drop_connection(connection)
                raise

            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=self.timeout)
                except asyncio.TimeoutError as exc:
                    await self._drop_connection(connection)
                    raise TimeoutError(
                        "Timed out waiting for a Responses WS event",
                    ) from exc
                except asyncio.CancelledError:
                    raise

                if isinstance(item, BaseException):
                    raise item
                if (
                    item.get("type")
                    in {
                        "error",
                        "response.completed",
                        "response.incomplete",
                        "response.failed",
                    }
                    and connection.pending.get(stream_id) is queue
                ):
                    connection.pending.pop(stream_id, None)
                yield item
        finally:
            if connection.pending.get(stream_id) is queue:
                connection.pending.pop(stream_id, None)

    @classmethod
    def _is_model_output_item(cls, item: dict) -> bool:
        """Return whether an input item is already represented by a response.

        Args:
            item: Responses input item to inspect.

        Returns:
            ``True`` for model-generated output items that continuation omits.
        """
        item_type = item.get("type")
        if item_type == "message":
            return item.get("role") == "assistant"
        return item_type in cls._RESPONSE_OUTPUT_ITEM_TYPES

    def _prepare_ws_payload(
        self,
        payloads: dict,
        state: _ConversationState | None = None,
    ) -> dict:
        """Prepare a WebSocket ``response.create`` payload.

        Configured extra-body fields are merged into the top-level event. When
        a conversation state is supplied, the request uses the official
        ``previous_response_id`` continuation and sends only newly added,
        non-output input items.

        Args:
            payloads: Responses API request fields prepared by the parent adapter.
            state: Session continuation state, if this is a live request.

        Returns:
            A JSON-serializable ``response.create`` client event.
        """
        ws_payload = copy.deepcopy(payloads)

        extra_body: dict[str, Any] = {}
        custom_extra_body = self.provider_config.get("custom_extra_body", {})
        if isinstance(custom_extra_body, dict):
            extra_body.update(custom_extra_body)

        request_extra_body = ws_payload.pop("extra_body", None)
        if isinstance(request_extra_body, dict):
            extra_body.update(request_extra_body)

        for key in list(ws_payload):
            if key not in self.default_params:
                extra_body[key] = ws_payload.pop(key)

        max_tokens = extra_body.pop("max_tokens", None)
        if max_tokens is not None and "max_output_tokens" not in extra_body:
            extra_body["max_output_tokens"] = max_tokens
        reasoning_effort = extra_body.pop("reasoning_effort", None)
        if reasoning_effort is not None and "reasoning" not in extra_body:
            extra_body["reasoning"] = {"effort": reasoning_effort}

        extra_body.pop("conversation", None)
        extra_body.pop("store", None)
        ws_payload.pop("conversation", None)
        ws_payload["store"] = False
        ws_payload.update(extra_body)
        requested_previous_response_id = ws_payload.get("previous_response_id")
        requested_stream_id = ws_payload.get("stream_id")

        # Streaming is implicit, while background mode isn't supported.
        for field_name in (
            "background",
            "extra_headers",
            "extra_query",
            "stream",
            "stream_options",
            "timeout",
        ):
            ws_payload.pop(field_name, None)

        if state is not None:
            full_input = ws_payload.get("input")
            if isinstance(full_input, list):
                full_input = copy.deepcopy(full_input)
                state.pending_input = full_input
                can_continue = (
                    bool(state.response_id)
                    and full_input[: len(state.last_input)] == state.last_input
                )
                if can_continue:
                    ws_payload["previous_response_id"] = state.response_id
                    ws_payload["input"] = [
                        item
                        for item in full_input[len(state.last_input) :]
                        if isinstance(item, dict)
                        and not self._is_model_output_item(item)
                    ]
                else:
                    if requested_previous_response_id:
                        ws_payload["previous_response_id"] = (
                            requested_previous_response_id
                        )
                    else:
                        ws_payload.pop("previous_response_id", None)
                    ws_payload["input"] = full_input
            else:
                state.pending_input = None
                if not requested_previous_response_id:
                    ws_payload.pop("previous_response_id", None)
            ws_payload["stream_id"] = state.stream_id
        else:
            if not requested_previous_response_id:
                ws_payload.pop("previous_response_id", None)
            ws_payload["stream_id"] = str(
                requested_stream_id or "request_" + uuid.uuid4().hex,
            )

        ws_payload["type"] = "response.create"
        return ws_payload

    @staticmethod
    def _reset_state(state: _ConversationState) -> None:
        """Clear continuation data after a failed or invalid request."""
        state.response_id = None
        state.last_input = []
        state.pending_input = None

    async def _ws_create(
        self,
        payloads: dict,
        tools: ToolSet | None,
        state: _ConversationState,
        connection: _WebSocketConnection,
    ) -> Response:
        """Send a ``response.create`` event and collect its terminal response.

        Args:
            payloads: Responses API request fields.
            tools: Functions available to the model.
            state: Session continuation state for this request.
            connection: Shared connection on which the request is sent.

        Returns:
            The terminal Responses API response.

        Raises:
            EmptyModelOutputError: If a terminal event has no response payload.
            RuntimeError: If the server emits an error event.
            TimeoutError: If no server event arrives within the configured timeout.
        """
        if tools:
            response_tools = []
            for tool in tools.openai_schema():
                function = tool.get("function", {})
                response_tools.append({"type": "function", **function})
            if response_tools:
                payloads["tools"] = response_tools
                payloads["tool_choice"] = payloads.get("tool_choice", "auto")

        ws_payload = self._prepare_ws_payload(payloads, state)
        response_id: str | None = None

        event_stream = self._request_events(
            connection,
            state.stream_id,
            ws_payload,
        )
        try:
            async for event in event_stream:
                event_type = event.get("type", "")
                event_response = event.get("response")
                if isinstance(event_response, dict):
                    response_id = event_response.get("id", response_id)

                if event_type == "error":
                    error = event.get("error")
                    if not isinstance(error, dict):
                        error = event
                    code = error.get("code") or error.get("type") or "stream_error"
                    message = error.get("message", "Responses WS request failed")
                    status = event.get("status", "unknown")
                    if event.get("stream_id") is None:
                        await self._drop_connection(connection)
                    self._reset_state(state)
                    raise RuntimeError(
                        f"Responses API WS failed ({status}): {code}: {message}. "
                        f"response_id={response_id}"
                    )

                if event_type in {
                    "response.completed",
                    "response.incomplete",
                    "response.failed",
                }:
                    if event_response is None:
                        raise EmptyModelOutputError(
                            f"Responses WS terminal event has no response: {event_type}"
                        )
                    return Response.model_validate(event_response)
        finally:
            await event_stream.aclose()

        raise EmptyModelOutputError(
            f"Responses WS stream ended without a terminal event. response_id={response_id}"
        )

    async def _query(
        self,
        payloads: dict,
        tools: ToolSet | None,
        *,
        request_max_retries: int | None = None,
    ) -> LLMResponse:
        """Send a non-streaming Responses API request via WebSocket.

        Args:
            payloads: Responses API request fields.
            tools: Functions available to the model.
            request_max_retries: Maximum transport-level request attempts.

        Returns:
            The normalized AstrBot response.
        """
        del request_max_retries
        api_key = str(self.client.api_key or "")
        state = await self._get_conversation_state(api_key)
        async with state.lock:
            connection = await self._get_connection(api_key, state.stream_id)
            if state.connection is not None and state.connection is not connection:
                self._reset_state(state)
            state.connection = connection
            try:
                response = await self._ws_create(payloads, tools, state, connection)
                if not isinstance(response, Response):
                    raise TypeError(
                        f"Responses WS API returned an unexpected type: {type(response)}: "
                        f"{response}."
                    )
                result = await self._parse_response(response, tools)
            except BaseException:
                self._reset_state(state)
                raise

            state.response_id = response.id
            state.last_input = state.pending_input or []
            state.pending_input = None
            return result

    async def _query_stream(
        self,
        payloads: dict,
        tools: ToolSet | None,
        *,
        request_max_retries: int | None = None,
    ) -> AsyncGenerator[LLMResponse, None]:
        """Send a streaming Responses API request via WebSocket.

        Args:
            payloads: Responses API request fields.
            tools: Functions available to the model.
            request_max_retries: Maximum transport-level request attempts.

        Yields:
            Text/reasoning chunks followed by the normalized terminal response.
        """
        del request_max_retries
        if tools:
            response_tools = []
            for tool in tools.openai_schema():
                function = tool.get("function", {})
                response_tools.append({"type": "function", **function})
            if response_tools:
                payloads["tools"] = response_tools
                payloads["tool_choice"] = payloads.get("tool_choice", "auto")

        api_key = str(self.client.api_key or "")
        state = await self._get_conversation_state(api_key)
        async with state.lock:
            connection = await self._get_connection(api_key, state.stream_id)
            if state.connection is not None and state.connection is not connection:
                self._reset_state(state)
            state.connection = connection
            committed = False
            response_id: str | None = None
            try:
                ws_payload = self._prepare_ws_payload(payloads, state)
                async for event in self._request_events(
                    connection,
                    state.stream_id,
                    ws_payload,
                ):
                    event_type = event.get("type", "")
                    event_response = event.get("response")
                    if isinstance(event_response, dict):
                        response_id = event_response.get("id", response_id)

                    if event_type == "error":
                        error = event.get("error")
                        if not isinstance(error, dict):
                            error = event
                        code = error.get("code") or error.get("type") or "stream_error"
                        message = error.get("message", "Responses WS stream failed")
                        status = event.get("status", "unknown")
                        if event.get("stream_id") is None:
                            await self._drop_connection(connection)
                        self._reset_state(state)
                        raise RuntimeError(
                            f"Responses API WS stream failed ({status}): "
                            f"{code}: {message}. response_id={response_id}"
                        )

                    if event_type in {
                        "response.output_text.delta",
                        "response.refusal.delta",
                    }:
                        delta = event.get("delta", "")
                        if delta:
                            yield LLMResponse(
                                "assistant",
                                result_chain=MessageChain(
                                    chain=[Comp.Plain(str(delta))],
                                ),
                                is_chunk=True,
                                id=response_id,
                            )
                        continue

                    if event_type in {
                        "response.reasoning_text.delta",
                        "response.reasoning_summary_text.delta",
                    }:
                        delta = event.get("delta", "")
                        if delta:
                            yield LLMResponse(
                                "assistant",
                                reasoning_content=str(delta),
                                is_chunk=True,
                                id=response_id,
                            )
                        continue

                    if event_type in {
                        "response.completed",
                        "response.incomplete",
                        "response.failed",
                    }:
                        if event_response is None:
                            raise EmptyModelOutputError(
                                "Responses WS terminal event has no response: "
                                f"{event_type}"
                            )
                        response = Response.model_validate(event_response)
                        result = await self._parse_response(response, tools)
                        state.response_id = response.id
                        state.last_input = state.pending_input or []
                        state.pending_input = None
                        committed = True
                        yield result
                        return

                raise EmptyModelOutputError(
                    "Responses WS stream ended without a terminal event. "
                    f"response_id={response_id}"
                )
            except BaseException:
                if not committed:
                    self._reset_state(state)
                raise

    async def terminate(self) -> None:
        """Close shared WebSockets and the inherited OpenAI HTTP client."""
        async with self._connections_lock:
            connections = [
                connection
                for provider_connections in self._connections.values()
                for connection in provider_connections
            ]
            self._connections.clear()
        self._conversation_states.clear()
        for connection in connections:
            await self._drop_connection(connection)
        await super().terminate()
