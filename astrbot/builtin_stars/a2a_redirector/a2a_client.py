from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import urljoin, urlparse
from uuid import uuid4

import aiohttp

from astrbot.api import logger

from .models import (
    V0_GET_TASK_METHOD,
    V0_SEND_MESSAGE_METHOD,
    V1_GET_TASK_METHOD,
    V1_SEND_MESSAGE_METHOD,
    A2AReply,
    SessionBinding,
    normalize_task_state,
    should_continue_task,
    should_stop_polling,
)


class A2AClientError(RuntimeError):
    pass


class A2AClient:
    def __init__(
        self,
        *,
        request_timeout_seconds: int = 180,
        poll_interval_seconds: float = 2.0,
        max_wait_seconds: int = 600,
    ) -> None:
        self.request_timeout_seconds = max(request_timeout_seconds, 1)
        self.poll_interval_seconds = max(poll_interval_seconds, 0.2)
        self.max_wait_seconds = max(max_wait_seconds, 1)

    async def discover(
        self,
        agent_card_url: str,
        headers: dict[str, str] | None = None,
    ) -> tuple[str, dict[str, Any], str, str]:
        last_error: Exception | None = None
        for candidate in self._candidate_card_urls(agent_card_url):
            try:
                card = await self._get_json(candidate, headers=headers)
                rpc_url, protocol_version = self._extract_rpc_url(card, candidate)
                return candidate, card, rpc_url, protocol_version
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.debug(
                    "[A2A Redirector] Agent card discovery failed for %s: %s",
                    candidate,
                    exc,
                )
        raise A2AClientError(
            f"Unable to discover an A2A agent card from {agent_card_url}. "
            f"Last error: {last_error}"
        )

    async def send_message(
        self,
        binding: SessionBinding,
        *,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> A2AReply:
        params = build_send_params(binding, text=text, metadata=metadata or {})
        result = await self._call_rpc_with_compat(
            binding=binding,
            primary_method=V1_SEND_MESSAGE_METHOD
            if binding.is_v1
            else V0_SEND_MESSAGE_METHOD,
            fallback_method=V0_SEND_MESSAGE_METHOD
            if binding.is_v1
            else V1_SEND_MESSAGE_METHOD,
            params=params,
        )
        reply = extract_reply(result)
        if reply.task_id and not should_stop_polling(reply.task_state):
            reply = await self.wait_for_task(binding, reply.task_id)
        return reply

    async def wait_for_task(
        self,
        binding: SessionBinding,
        task_id: str,
    ) -> A2AReply:
        deadline = asyncio.get_running_loop().time() + self.max_wait_seconds
        last_reply = A2AReply(text="", task_id=task_id)

        while True:
            result = await self._call_rpc_with_compat(
                binding=binding,
                primary_method=V1_GET_TASK_METHOD
                if binding.is_v1
                else V0_GET_TASK_METHOD,
                fallback_method=V0_GET_TASK_METHOD
                if binding.is_v1
                else V1_GET_TASK_METHOD,
                params={
                    "id": task_id,
                    "historyLength": binding.history_length,
                },
            )
            last_reply = extract_reply(result)
            if should_stop_polling(last_reply.task_state):
                return last_reply
            if asyncio.get_running_loop().time() >= deadline:
                return last_reply
            await asyncio.sleep(self.poll_interval_seconds)

    async def _call_rpc_with_compat(
        self,
        *,
        binding: SessionBinding,
        primary_method: str,
        fallback_method: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        methods = [primary_method]
        if fallback_method not in methods:
            methods.append(fallback_method)

        last_error: A2AClientError | None = None
        for method in methods:
            try:
                return await self._call_rpc(
                    binding.rpc_url,
                    method=method,
                    params=params,
                    headers=binding.headers,
                    protocol_version=binding.protocol_version,
                )
            except A2AClientError as exc:
                last_error = exc
                if not self._is_method_not_found(exc):
                    raise
        raise last_error or A2AClientError("A2A RPC call failed.")

    async def _call_rpc(
        self,
        rpc_url: str,
        *,
        method: str,
        params: dict[str, Any],
        headers: dict[str, str] | None,
        protocol_version: str | None,
    ) -> dict[str, Any]:
        request_body = {
            "jsonrpc": "2.0",
            "id": str(uuid4()),
            "method": method,
            "params": params,
        }
        request_headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if headers:
            request_headers.update(headers)
        if protocol_version and protocol_version.startswith("1"):
            request_headers.setdefault("A2A-Version", protocol_version)

        timeout = aiohttp.ClientTimeout(total=self.request_timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
            async with session.post(
                rpc_url,
                json=request_body,
                headers=request_headers,
            ) as response:
                payload = await response.json(content_type=None)
                if response.status >= 400:
                    raise A2AClientError(
                        f"HTTP {response.status} from A2A endpoint: {payload}"
                    )

        if not isinstance(payload, dict):
            raise A2AClientError("A2A endpoint returned a non-object response.")

        error = payload.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or "Unknown RPC error")
            code = error.get("code")
            raise A2AClientError(f"{message} (code={code})")

        result = payload.get("result")
        if not isinstance(result, dict):
            raise A2AClientError("A2A endpoint returned an empty result object.")
        return result

    async def _get_json(
        self,
        url: str,
        *,
        headers: dict[str, str] | None,
    ) -> dict[str, Any]:
        request_headers = {"Accept": "application/json"}
        if headers:
            request_headers.update(headers)
        timeout = aiohttp.ClientTimeout(total=self.request_timeout_seconds)

        async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
            async with session.get(url, headers=request_headers) as response:
                if response.status >= 400:
                    raise A2AClientError(
                        f"HTTP {response.status} while fetching agent card."
                    )
                payload = await response.json(content_type=None)

        if not isinstance(payload, dict):
            raise A2AClientError("Agent card response is not a JSON object.")
        return payload

    def _candidate_card_urls(self, agent_card_url: str) -> list[str]:
        clean = agent_card_url.strip()
        if not clean:
            return []

        parsed = urlparse(clean)
        if not parsed.scheme or not parsed.netloc:
            return [clean]

        candidates = [clean]
        if clean.endswith(".json"):
            return candidates

        base = clean.rstrip("/")
        candidates.extend(
            [
                f"{base}/.well-known/agent-card.json",
                f"{base}/.well-known/agent.json",
            ],
        )
        return list(dict.fromkeys(candidates))

    def _extract_rpc_url(
        self,
        card: dict[str, Any],
        card_url: str,
    ) -> tuple[str, str]:
        protocol_version = str(
            card.get("protocolVersion") or card.get("version") or "0.3.0",
        )

        supported_interfaces = card.get("supportedInterfaces")
        if isinstance(supported_interfaces, list):
            for interface in supported_interfaces:
                if not isinstance(interface, dict):
                    continue
                binding = str(interface.get("protocolBinding") or "").upper()
                if binding != "JSONRPC":
                    continue
                endpoint_url = interface.get("url") or interface.get("transportUrl")
                if endpoint_url:
                    return (
                        urljoin(card_url, str(endpoint_url)),
                        str(interface.get("protocolVersion") or protocol_version),
                    )

        preferred_transport = card.get("preferredTransport")
        if isinstance(preferred_transport, dict):
            binding = str(
                preferred_transport.get("protocolBinding")
                or preferred_transport.get("transport")
                or "",
            ).upper()
            endpoint_url = preferred_transport.get("url") or preferred_transport.get(
                "transportUrl"
            )
            if binding == "JSONRPC" and endpoint_url:
                return urljoin(card_url, str(endpoint_url)), protocol_version

        additional_interfaces = card.get("additionalInterfaces")
        if isinstance(additional_interfaces, list):
            for interface in additional_interfaces:
                if not isinstance(interface, dict):
                    continue
                binding = str(
                    interface.get("transport")
                    or interface.get("protocolBinding")
                    or "",
                ).upper()
                if binding != "JSONRPC":
                    continue
                endpoint_url = interface.get("url") or interface.get("transportUrl")
                if endpoint_url:
                    return (
                        urljoin(card_url, str(endpoint_url)),
                        str(interface.get("protocolVersion") or protocol_version),
                    )

        direct_url = card.get("url")
        if direct_url:
            return urljoin(card_url, str(direct_url)), protocol_version

        raise A2AClientError(
            "The agent card does not expose a JSONRPC endpoint that this plugin can use."
        )

    def _is_method_not_found(self, error: Exception) -> bool:
        text = str(error).lower()
        return "code=-32601" in text or "method not found" in text


def build_send_params(
    binding: SessionBinding,
    *,
    text: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    message: dict[str, Any] = {
        "messageId": str(uuid4()),
        "role": "ROLE_USER" if binding.is_v1 else "user",
        "parts": [{"text": text} if binding.is_v1 else {"kind": "text", "text": text}],
        "metadata": metadata,
    }

    if binding.context_id:
        message["contextId"] = binding.context_id

    if binding.last_task_id:
        if should_continue_task(binding.last_task_state):
            message["taskId"] = binding.last_task_id
        else:
            message["referenceTaskIds"] = [binding.last_task_id]

    return {
        "message": message,
        "configuration": {
            "blocking": binding.blocking,
            "acceptedOutputModes": binding.accepted_output_modes,
            "historyLength": binding.history_length,
        },
    }


def extract_reply(result: dict[str, Any]) -> A2AReply:
    task, message = _unwrap_result(result)
    task_state = normalize_task_state((task or {}).get("status", {}).get("state"))
    context_id = (
        (task or {}).get("contextId")
        or (message or {}).get("contextId")
        or (task or {}).get("status", {}).get("contextId")
    )
    task_id = (task or {}).get("id") or (message or {}).get("taskId")

    parts: list[str] = []
    if message:
        parts.extend(_collect_text_blocks(message))
    if task:
        status_message = task.get("status", {}).get("message")
        parts.extend(_collect_text_blocks(status_message))
        for artifact in task.get("artifacts", []):
            parts.extend(_collect_text_blocks(artifact))

    unique_parts: list[str] = []
    seen = set()
    for part in parts:
        clean = part.strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        unique_parts.append(clean)

    text = "\n\n".join(unique_parts)
    if not text and task_id:
        pretty_state = task_state or "UNKNOWN"
        text = f"A2A task {task_id} finished with state {pretty_state}, but returned no text content."

    return A2AReply(
        text=text,
        context_id=context_id,
        task_id=task_id,
        task_state=task_state or None,
    )


def _unwrap_result(
    result: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if "task" in result and isinstance(result["task"], dict):
        return result["task"], result.get("message")
    if "message" in result and isinstance(result["message"], dict):
        return None, result["message"]

    kind = str(result.get("kind") or "").lower()
    if kind == "task" or ("status" in result and "id" in result):
        return result, None
    if kind == "message" or "parts" in result:
        return None, result
    return None, None


def _collect_text_blocks(node: Any) -> list[str]:
    if node is None:
        return []
    if isinstance(node, str):
        return [node]
    if isinstance(node, list):
        blocks: list[str] = []
        for item in node:
            blocks.extend(_collect_text_blocks(item))
        return blocks
    if not isinstance(node, dict):
        return [str(node)]

    if "parts" in node and isinstance(node["parts"], list):
        blocks: list[str] = []
        for part in node["parts"]:
            blocks.extend(_collect_part_text(part))
        return blocks

    return _collect_part_text(node)


def _collect_part_text(part: Any) -> list[str]:
    if part is None:
        return []
    if isinstance(part, str):
        return [part]
    if not isinstance(part, dict):
        return [str(part)]

    if isinstance(part.get("text"), str):
        return [part["text"]]
    if isinstance(part.get("raw"), str):
        return [part["raw"]]
    if "data" in part:
        try:
            return [json.dumps(part["data"], ensure_ascii=False, indent=2)]
        except TypeError:
            return [str(part["data"])]

    uri = part.get("uri")
    filename = part.get("filename")
    if uri or filename:
        label = filename or uri
        return [f"[A2A file] {label}"]

    return []
