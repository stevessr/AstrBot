from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

DEFAULT_OUTPUT_MODES = [
    "text/plain",
    "text/markdown",
    "application/json",
]

V0_SEND_MESSAGE_METHOD = "message/send"
V0_GET_TASK_METHOD = "tasks/get"
V1_SEND_MESSAGE_METHOD = "SendMessage"
V1_GET_TASK_METHOD = "GetTask"

_STATE_ALIASES = {
    "SUBMITTED": "TASK_STATE_SUBMITTED",
    "WORKING": "TASK_STATE_WORKING",
    "INPUT_REQUIRED": "TASK_STATE_INPUT_REQUIRED",
    "AUTH_REQUIRED": "TASK_STATE_AUTH_REQUIRED",
    "COMPLETED": "TASK_STATE_COMPLETED",
    "FAILED": "TASK_STATE_FAILED",
    "CANCELED": "TASK_STATE_CANCELED",
    "REJECTED": "TASK_STATE_REJECTED",
    "UNKNOWN": "TASK_STATE_UNKNOWN",
}

FINAL_TASK_STATES = {
    "TASK_STATE_COMPLETED",
    "TASK_STATE_FAILED",
    "TASK_STATE_CANCELED",
    "TASK_STATE_REJECTED",
}

INTERRUPTED_TASK_STATES = {
    "TASK_STATE_INPUT_REQUIRED",
    "TASK_STATE_AUTH_REQUIRED",
}

ACTIVE_TASK_STATES = {
    "TASK_STATE_SUBMITTED",
    "TASK_STATE_WORKING",
}

STOP_POLLING_TASK_STATES = FINAL_TASK_STATES | INTERRUPTED_TASK_STATES


def normalize_task_state(state: str | None) -> str:
    if not state:
        return ""
    normalized = state.strip().upper().replace("-", "_")
    return _STATE_ALIASES.get(normalized, normalized)


def should_continue_task(state: str | None) -> bool:
    return normalize_task_state(state) in ACTIVE_TASK_STATES | INTERRUPTED_TASK_STATES


def should_stop_polling(state: str | None) -> bool:
    return normalize_task_state(state) in STOP_POLLING_TASK_STATES


def protocol_major(version: str | None) -> int:
    if not version:
        return 0
    head = version.strip().split(".", 1)[0]
    try:
        return int(head)
    except ValueError:
        return 0


def uses_v1_protocol(version: str | None) -> bool:
    return protocol_major(version) >= 1


@dataclass(slots=True)
class A2AProfile:
    key: str
    label: str
    transport: str = "a2a"
    agent_card_url: str = ""
    executable: str = ""
    description: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    accepted_output_modes: list[str] = field(
        default_factory=lambda: list(DEFAULT_OUTPUT_MODES),
    )
    blocking: bool = True
    history_length: int = 20

    @classmethod
    def from_config(cls, key: str, payload: dict[str, Any]) -> A2AProfile:
        headers = payload.get("headers", {})
        if not isinstance(headers, dict):
            headers = {}

        output_modes = payload.get("accepted_output_modes", DEFAULT_OUTPUT_MODES)
        if not isinstance(output_modes, list):
            output_modes = list(DEFAULT_OUTPUT_MODES)

        return cls(
            key=key,
            label=str(payload.get("label") or key),
            transport=str(payload.get("transport") or "a2a").strip().lower() or "a2a",
            agent_card_url=str(payload.get("agent_card_url") or "").strip(),
            executable=str(payload.get("executable") or "").strip(),
            description=str(payload.get("description") or "").strip(),
            headers={
                str(name): str(value)
                for name, value in headers.items()
                if name and value is not None
            },
            accepted_output_modes=[
                str(mode)
                for mode in output_modes
                if isinstance(mode, str) and mode.strip()
            ]
            or list(DEFAULT_OUTPUT_MODES),
            blocking=bool(payload.get("blocking", True)),
            history_length=max(int(payload.get("history_length", 20)), 0),
        )


@dataclass(slots=True)
class SessionBinding:
    profile_key: str
    profile_label: str
    profile_description: str
    transport: str
    agent_card_url: str
    rpc_url: str
    protocol_version: str
    agent_name: str
    executable: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    accepted_output_modes: list[str] = field(
        default_factory=lambda: list(DEFAULT_OUTPUT_MODES),
    )
    blocking: bool = True
    history_length: int = 20
    working_directory: str | None = None
    context_id: str | None = None
    last_task_id: str | None = None
    last_task_state: str | None = None

    @property
    def is_v1(self) -> bool:
        return uses_v1_protocol(self.protocol_version)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SessionBinding:
        return cls(
            profile_key=str(payload.get("profile_key") or "adhoc"),
            profile_label=str(payload.get("profile_label") or "adhoc"),
            profile_description=str(payload.get("profile_description") or ""),
            transport=str(payload.get("transport") or "a2a").strip().lower() or "a2a",
            agent_card_url=str(payload.get("agent_card_url") or "").strip(),
            rpc_url=str(payload.get("rpc_url") or "").strip(),
            protocol_version=str(payload.get("protocol_version") or "0.3.0"),
            agent_name=str(payload.get("agent_name") or ""),
            executable=str(payload.get("executable") or "").strip(),
            headers={
                str(name): str(value)
                for name, value in (payload.get("headers") or {}).items()
                if name and value is not None
            },
            accepted_output_modes=[
                str(mode)
                for mode in (
                    payload.get("accepted_output_modes") or DEFAULT_OUTPUT_MODES
                )
                if isinstance(mode, str) and mode.strip()
            ]
            or list(DEFAULT_OUTPUT_MODES),
            blocking=bool(payload.get("blocking", True)),
            history_length=max(int(payload.get("history_length", 20)), 0),
            working_directory=payload.get("working_directory"),
            context_id=payload.get("context_id"),
            last_task_id=payload.get("last_task_id"),
            last_task_state=payload.get("last_task_state"),
        )


@dataclass(slots=True)
class A2AReply:
    text: str
    context_id: str | None = None
    task_id: str | None = None
    task_state: str | None = None
    agent_name: str | None = None
