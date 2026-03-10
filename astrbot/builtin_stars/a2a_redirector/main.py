from __future__ import annotations

from pathlib import Path
from sys import maxsize
from typing import Any

from astrbot.api import logger, sp, star
from astrbot.api.event import AstrMessageEvent, filter

from .a2a_client import A2AClient, A2AClientError
from .models import A2AProfile, SessionBinding
from .terminal_bridge import (
    TerminalBridgeError,
    TerminalSessionManager,
    resolve_local_executable,
)

STATE_KEY = "a2a_redirector_binding"
terminal_session_manager = TerminalSessionManager()

DEFAULT_PROFILES: dict[str, dict[str, Any]] = {
    "bash": {
        "label": "Bash",
        "transport": "terminal",
        "executable": "bash",
        "description": "Route the current session to a local Bash terminal.",
    },
    "fish": {
        "label": "Fish",
        "transport": "terminal",
        "executable": "fish",
        "description": "Route the current session to a local Fish terminal.",
    },
    "zsh": {
        "label": "Zsh",
        "transport": "terminal",
        "executable": "zsh",
        "description": "Route the current session to a local Zsh terminal.",
    },
    "sh": {
        "label": "sh",
        "transport": "terminal",
        "executable": "sh",
        "description": "Route the current session to a local POSIX shell.",
    },
    "ash": {
        "label": "ash",
        "transport": "terminal",
        "executable": "ash",
        "description": "Route the current session to a local ash shell.",
    },
    "claude-code": {
        "label": "Claude Code",
        "transport": "a2a",
        "agent_card_url": "",
        "description": "Route the current session to a Claude Code A2A bridge.",
    },
    "codex": {
        "label": "Codex",
        "transport": "a2a",
        "agent_card_url": "",
        "description": "Route the current session to a Codex CLI A2A bridge.",
    },
    "qwen-code": {
        "label": "Qwen Code",
        "transport": "a2a",
        "agent_card_url": "",
        "description": "Route the current session to a Qwen Code A2A bridge.",
    },
    "gemini-cli": {
        "label": "Gemini CLI",
        "transport": "a2a",
        "agent_card_url": "",
        "description": "Route the current session to a Gemini CLI A2A bridge.",
    },
    "iflow": {
        "label": "iFlow",
        "transport": "a2a",
        "agent_card_url": "",
        "description": "Route the current session to an iFlow CLI A2A bridge.",
    },
    "copilot-cli": {
        "label": "Copilot CLI",
        "transport": "a2a",
        "agent_card_url": "",
        "description": "Route the current session to a Copilot CLI A2A bridge.",
    },
}


class Main(star.Star):
    def __init__(
        self,
        context: star.Context,
        config: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(context, config)
        self.config = config or {}
        self._cleanup_registered = False

    async def initialize(self) -> None:
        if not self._cleanup_registered:
            self.context.conversation_manager.register_on_session_deleted(
                self._clear_binding_for_session,
            )
            self._cleanup_registered = True

    async def terminate(self) -> None:
        await terminal_session_manager.close_all()

    @filter.command_group("redirect", alias={"a2a"})
    def redirect(self) -> None:
        """Bind the current session to a terminal or A2A target."""

    @redirect.command("profiles")
    async def profiles(self, event: AstrMessageEvent) -> None:
        """List available redirect profiles."""
        profiles = self._get_profiles()
        current = await self._get_binding(event.unified_msg_origin)
        lines = ["Configured redirect profiles:"]
        for key, profile in profiles.items():
            if profile.transport == "terminal":
                status = profile.executable or "missing executable"
            else:
                status = (
                    "configured" if profile.agent_card_url else "missing agent_card_url"
                )
            current_mark = (
                " (current)" if current and current.profile_key == key else ""
            )
            description = f" - {profile.description}" if profile.description else ""
            lines.append(
                f"- {key}: {profile.label} [{profile.transport}: {status}]{current_mark}{description}"
            )
        lines.append("")
        lines.append(
            "Use /redirect bind <profile> or /redirect bind_url <agent_card_or_base_url>."
        )
        yield event.make_result().message("\n".join(lines)).use_t2i(False)

    @redirect.command("bind")
    async def bind(self, event: AstrMessageEvent, profile_key: str = "") -> None:
        """Bind the current session to a configured target profile."""
        if permission_error := self._check_access(event):
            yield event.plain_result(permission_error)
            return
        if not profile_key:
            yield event.plain_result("Usage: /redirect bind <profile>")
            return

        profile = self._get_profiles().get(profile_key)
        if not profile:
            yield event.plain_result(f"Unknown redirect profile: {profile_key}")
            return

        try:
            if profile.transport == "terminal":
                summary = await self._bind_terminal_profile(
                    event=event, profile=profile
                )
            else:
                if not profile.agent_card_url:
                    yield event.plain_result(
                        f"Profile {profile_key} is missing agent_card_url. Configure it in the plugin settings first.",
                    )
                    return
                summary = await self._bind_profile(
                    event=event,
                    profile_key=profile.key,
                    profile_label=profile.label,
                    profile_description=profile.description,
                    transport=profile.transport,
                    agent_card_url=profile.agent_card_url,
                    executable=profile.executable,
                    headers=profile.headers,
                    accepted_output_modes=profile.accepted_output_modes,
                    blocking=profile.blocking,
                    history_length=profile.history_length,
                )
        except (A2AClientError, TerminalBridgeError) as exc:
            yield event.plain_result(str(exc))
            return

        yield event.make_result().message(summary).use_t2i(False)

    @redirect.command("bind_url")
    async def bind_url(self, event: AstrMessageEvent, agent_card_url: str = "") -> None:
        """Bind the current session to an ad-hoc A2A endpoint."""
        if permission_error := self._check_access(event):
            yield event.plain_result(permission_error)
            return
        if not agent_card_url:
            yield event.plain_result(
                "Usage: /redirect bind_url <agent_card_url_or_base_url>",
            )
            return

        try:
            summary = await self._bind_profile(
                event=event,
                profile_key="adhoc",
                profile_label="Ad-hoc A2A",
                profile_description="Ad-hoc A2A endpoint bound from command.",
                transport="a2a",
                agent_card_url=agent_card_url,
                executable="",
                headers={},
                accepted_output_modes=[],
                blocking=True,
                history_length=self._default_history_length(),
            )
        except A2AClientError as exc:
            yield event.plain_result(str(exc))
            return

        yield event.make_result().message(summary).use_t2i(False)

    @redirect.command("status")
    async def status(self, event: AstrMessageEvent) -> None:
        """Show the current session binding."""
        binding = await self._get_binding(event.unified_msg_origin)
        if not binding:
            yield event.plain_result(
                "This session is not bound to any redirect target."
            )
            return

        lines = [
            f"Current redirect binding: {binding.profile_label}",
            f"- profile: {binding.profile_key}",
            f"- transport: {binding.transport}",
            f"- agent: {binding.agent_name or '(unnamed agent)'}",
            f"- executable: {binding.executable or '(empty)'}",
            f"- card: {binding.agent_card_url}",
            f"- rpc: {binding.rpc_url}",
            f"- protocol: {binding.protocol_version}",
            f"- working_directory: {binding.working_directory or '(empty)'}",
            f"- context_id: {binding.context_id or '(empty)'}",
            f"- last_task_id: {binding.last_task_id or '(empty)'}",
            f"- last_task_state: {binding.last_task_state or '(empty)'}",
            "",
            "Only /redirect ... and /a2a ... stay local while the session is bound. Other messages are forwarded to the configured target.",
        ]
        yield event.make_result().message("\n".join(lines)).use_t2i(False)

    @redirect.command("reset")
    async def reset(self, event: AstrMessageEvent) -> None:
        """Reset local context tracking for the current session."""
        if permission_error := self._check_access(event):
            yield event.plain_result(permission_error)
            return
        binding = await self._get_binding(event.unified_msg_origin)
        if not binding:
            yield event.plain_result(
                "This session is not bound to any redirect target."
            )
            return

        binding.context_id = None
        binding.last_task_id = None
        binding.last_task_state = None
        if binding.transport == "terminal":
            await terminal_session_manager.close_session(event.unified_msg_origin)
        await self._save_binding(event.unified_msg_origin, binding)
        yield event.plain_result(
            "The local redirect session context has been reset. The binding is still active.",
        )

    @redirect.command("unbind")
    async def unbind(self, event: AstrMessageEvent) -> None:
        """Remove the current session binding."""
        if permission_error := self._check_access(event):
            yield event.plain_result(permission_error)
            return
        binding = await self._get_binding(event.unified_msg_origin)
        if not binding:
            yield event.plain_result(
                "This session is not bound to any redirect target."
            )
            return

        await self._clear_binding_for_session(event.unified_msg_origin)
        yield event.plain_result(
            f"Unbound the current session from {binding.profile_label}."
        )

    @filter.event_message_type(filter.EventMessageType.ALL, priority=maxsize - 2)
    async def handle_bound_session(self, event: AstrMessageEvent) -> None:
        """Forward bound-session messages to the configured target."""
        binding = await self._get_binding(event.unified_msg_origin)
        if not binding or self._is_redirect_command(event):
            return

        if permission_error := self._check_access(event):
            await event.send(event.plain_result(permission_error))
            event.stop_event()
            return

        text = (event.message_str or event.get_message_outline() or "").strip()
        if not text:
            await event.send(
                event.plain_result(
                    "The current redirect target only receives text content from AstrBot.",
                ),
            )
            event.stop_event()
            return

        try:
            if binding.transport == "terminal":
                response_text = await self._forward_to_terminal(
                    event=event,
                    binding=binding,
                    text=text,
                )
            else:
                response_text = await self._forward_to_a2a(
                    event=event,
                    binding=binding,
                    text=text,
                )
            await event.send(event.make_result().message(response_text).use_t2i(False))
        except (A2AClientError, TerminalBridgeError) as exc:
            logger.error("[A2A Redirector] %s", exc)
            await event.send(
                event.plain_result(f"Redirect forwarding failed: {exc}"),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("[A2A Redirector] Unexpected error: %s", exc, exc_info=True)
            await event.send(
                event.plain_result(
                    f"Redirect forwarding failed with an unexpected error: {exc}"
                ),
            )
        finally:
            event.stop_event()

    async def _bind_profile(
        self,
        *,
        event: AstrMessageEvent,
        profile_key: str,
        profile_label: str,
        profile_description: str,
        transport: str,
        agent_card_url: str,
        executable: str,
        headers: dict[str, str],
        accepted_output_modes: list[str],
        blocking: bool,
        history_length: int,
    ) -> str:
        await terminal_session_manager.close_session(event.unified_msg_origin)
        client = self._build_client()
        discovered_card_url, card, rpc_url, protocol_version = await client.discover(
            agent_card_url,
            headers=headers,
        )
        agent_name = str(card.get("name") or profile_label)
        binding = SessionBinding(
            profile_key=profile_key,
            profile_label=profile_label,
            profile_description=profile_description,
            transport=transport,
            agent_card_url=discovered_card_url,
            rpc_url=rpc_url,
            protocol_version=protocol_version,
            agent_name=agent_name,
            executable=executable,
            headers=headers,
            accepted_output_modes=accepted_output_modes or self._default_output_modes(),
            blocking=blocking,
            history_length=max(history_length, 0),
        )
        await self._save_binding(event.unified_msg_origin, binding)

        return "\n".join(
            [
                f"Bound this session to {profile_label}.",
                f"- transport: {transport}",
                f"- agent: {agent_name}",
                f"- card: {discovered_card_url}",
                f"- rpc: {rpc_url}",
                f"- protocol: {protocol_version}",
                "",
                "Only /redirect ... and /a2a ... stay local while the session is bound. Other messages in this session are now forwarded to the remote A2A agent.",
            ]
        )

    async def _bind_terminal_profile(
        self,
        *,
        event: AstrMessageEvent,
        profile: A2AProfile,
    ) -> str:
        await terminal_session_manager.close_session(event.unified_msg_origin)
        executable = profile.executable or profile.key
        resolved_executable = resolve_local_executable(executable)

        binding = SessionBinding(
            profile_key=profile.key,
            profile_label=profile.label,
            profile_description=profile.description,
            transport="terminal",
            agent_card_url="",
            rpc_url="",
            protocol_version="local-terminal",
            agent_name=profile.label,
            executable=resolved_executable,
            headers={},
            accepted_output_modes=[],
            blocking=True,
            history_length=0,
            working_directory=self._terminal_default_working_directory(),
        )
        await self._save_binding(event.unified_msg_origin, binding)

        return "\n".join(
            [
                f"Bound this session to local terminal profile {profile.label}.",
                "- transport: terminal",
                f"- executable: {resolved_executable}",
                f"- working_directory: {binding.working_directory or str(Path.cwd())}",
                "",
                "Only /redirect ... and /a2a ... stay local while the session is bound. Other messages in this session are now executed in the local shell session.",
            ]
        )

    async def _clear_binding_for_session(self, unified_msg_origin: str) -> None:
        await terminal_session_manager.close_session(unified_msg_origin)
        await sp.session_remove(unified_msg_origin, STATE_KEY)

    async def _get_binding(self, unified_msg_origin: str) -> SessionBinding | None:
        payload = await sp.session_get(unified_msg_origin, STATE_KEY, None)
        if not isinstance(payload, dict):
            return None
        try:
            return SessionBinding.from_dict(payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[A2A Redirector] Dropping invalid binding for %s: %s",
                unified_msg_origin,
                exc,
            )
            await self._clear_binding_for_session(unified_msg_origin)
            return None

    async def _save_binding(
        self,
        unified_msg_origin: str,
        binding: SessionBinding,
    ) -> None:
        await sp.session_put(unified_msg_origin, STATE_KEY, binding.to_dict())

    def _build_client(self) -> A2AClient:
        return A2AClient(
            request_timeout_seconds=max(
                int(self.config.get("request_timeout_seconds", 180)),
                1,
            ),
            poll_interval_seconds=max(
                float(self.config.get("poll_interval_seconds", 2.0)),
                0.2,
            ),
            max_wait_seconds=max(int(self.config.get("max_wait_seconds", 600)), 1),
        )

    def _get_profiles(self) -> dict[str, A2AProfile]:
        raw_profiles = self.config.get("profiles", DEFAULT_PROFILES)
        if not isinstance(raw_profiles, dict):
            raw_profiles = DEFAULT_PROFILES

        profiles: dict[str, A2AProfile] = {}
        for key, payload in raw_profiles.items():
            if not isinstance(key, str) or not isinstance(payload, dict):
                continue
            profiles[key] = A2AProfile.from_config(key, payload)
        return profiles

    def _default_history_length(self) -> int:
        return max(int(self.config.get("default_history_length", 20)), 0)

    def _default_output_modes(self) -> list[str]:
        return ["text/plain", "text/markdown", "application/json"]

    def _terminal_default_working_directory(self) -> str:
        configured = str(self.config.get("terminal_working_directory") or "").strip()
        if not configured:
            return ""
        return str(Path(configured).expanduser().resolve())

    def _is_redirect_command(self, event: AstrMessageEvent) -> bool:
        text = (event.message_str or "").strip()
        if not text:
            return False

        wake_prefixes = self.context.get_config(umo=event.unified_msg_origin).get(
            "wake_prefix",
            ["/"],
        )
        for prefix in wake_prefixes:
            if text == f"{prefix}a2a" or text.startswith(f"{prefix}a2a "):
                return True
            if text == f"{prefix}redirect" or text.startswith(f"{prefix}redirect "):
                return True
        return (
            text == "a2a"
            or text.startswith("a2a ")
            or text == "redirect"
            or text.startswith("redirect ")
        )

    def _check_access(self, event: AstrMessageEvent) -> str | None:
        if self.config.get("require_admin", True) and not event.is_admin():
            return "Only AstrBot administrators can use redirect targets that execute commands."
        if event.get_group_id() and not event.is_admin():
            return "Only group administrators can bind or unbind a shared session."
        return None

    async def _forward_to_a2a(
        self,
        *,
        event: AstrMessageEvent,
        binding: SessionBinding,
        text: str,
    ) -> str:
        client = self._build_client()
        reply = await client.send_message(
            binding,
            text=text,
            metadata={
                "astrbot_session": event.unified_msg_origin,
                "astrbot_platform_id": event.get_platform_id(),
                "astrbot_sender_id": event.get_sender_id(),
                "astrbot_sender_name": event.get_sender_name(),
                "a2a_profile": binding.profile_key,
            },
        )
        binding.context_id = reply.context_id or binding.context_id
        binding.last_task_id = reply.task_id or binding.last_task_id
        binding.last_task_state = reply.task_state or binding.last_task_state
        await self._save_binding(event.unified_msg_origin, binding)
        return self._normalize_response_text(reply.text)

    async def _forward_to_terminal(
        self,
        *,
        event: AstrMessageEvent,
        binding: SessionBinding,
        text: str,
    ) -> str:
        result = await terminal_session_manager.execute(
            event.unified_msg_origin,
            executable=binding.executable or binding.profile_key,
            command=text,
            working_directory=binding.working_directory,
            timeout_seconds=max(
                int(self.config.get("terminal_command_timeout_seconds", 180)),
                1,
            ),
        )
        binding.working_directory = result.cwd
        binding.last_task_state = f"EXIT_{result.exit_code}"
        binding.last_task_id = None
        binding.context_id = None
        await self._save_binding(event.unified_msg_origin, binding)

        response = result.output
        if result.exit_code != 0:
            suffix = f"[exit {result.exit_code}]"
            response = f"{response}\n{suffix}" if response else suffix
        if not response:
            response = f"[exit {result.exit_code}]"
        return self._normalize_response_text(response)

    def _normalize_response_text(self, text: str) -> str:
        normalized = text.strip()
        if not normalized:
            return "(empty response)"

        limit = max(int(self.config.get("response_char_limit", 12000)), 200)
        if len(normalized) <= limit:
            return normalized
        return normalized[:limit] + "\n\n[truncated]"
