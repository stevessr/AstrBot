import json
import shutil
import types
from pathlib import Path

import pytest

from astrbot.builtin_stars.a2a_redirector.a2a_client import (
    A2AClient,
    build_send_params,
    extract_reply,
)
from astrbot.builtin_stars.a2a_redirector.main import (
    DEFAULT_PROFILE_ENTRIES,
    _profile_entries_to_mapping,
    _profile_mapping_to_entries,
)
from astrbot.builtin_stars.a2a_redirector.models import A2AProfile, SessionBinding
from astrbot.builtin_stars.a2a_redirector.terminal_bridge import (
    TerminalBridgeError,
    TerminalSession,
    build_terminal_command,
    parse_terminal_output,
)
from astrbot.core.config.astrbot_config import AstrBotConfig


def make_binding(**kwargs) -> SessionBinding:
    payload = {
        "profile_key": "codex",
        "profile_label": "Codex",
        "profile_description": "Test profile",
        "transport": "a2a",
        "agent_card_url": "http://localhost:8080/.well-known/agent-card.json",
        "rpc_url": "http://localhost:8080/rpc",
        "protocol_version": "0.3.0",
        "agent_name": "Codex",
        "executable": "",
        "headers": {},
        "accepted_output_modes": ["text/plain"],
        "blocking": True,
        "history_length": 20,
        "working_directory": None,
        "context_id": None,
        "last_task_id": None,
        "last_task_state": None,
    }
    payload.update(kwargs)
    return SessionBinding.from_dict(payload)


def test_build_send_params_continues_open_task() -> None:
    binding = make_binding(
        context_id="ctx-1",
        last_task_id="task-1",
        last_task_state="working",
    )

    params = build_send_params(binding, text="ls -la", metadata={"source": "astrbot"})

    assert params["message"]["contextId"] == "ctx-1"
    assert params["message"]["taskId"] == "task-1"
    assert "referenceTaskIds" not in params["message"]
    assert params["message"]["parts"] == [{"kind": "text", "text": "ls -la"}]


def test_build_send_params_references_completed_task() -> None:
    binding = make_binding(
        context_id="ctx-2",
        last_task_id="task-2",
        last_task_state="completed",
    )

    params = build_send_params(binding, text="continue", metadata={})

    assert params["message"]["contextId"] == "ctx-2"
    assert params["message"]["referenceTaskIds"] == ["task-2"]
    assert "taskId" not in params["message"]


def test_extract_reply_reads_status_and_artifact_text() -> None:
    reply = extract_reply(
        {
            "id": "task-3",
            "kind": "task",
            "contextId": "ctx-3",
            "status": {
                "state": "completed",
                "message": {
                    "role": "agent",
                    "parts": [{"kind": "text", "text": "Working tree updated."}],
                },
            },
            "artifacts": [
                {
                    "parts": [
                        {
                            "kind": "text",
                            "text": "Changed files:\n- src/app.py\n- tests/test_app.py",
                        }
                    ]
                }
            ],
        }
    )

    assert reply.task_id == "task-3"
    assert reply.context_id == "ctx-3"
    assert reply.task_state == "TASK_STATE_COMPLETED"
    assert "Working tree updated." in reply.text
    assert "Changed files:" in reply.text


def test_extract_rpc_url_prefers_v1_jsonrpc_interface() -> None:
    client = A2AClient()

    rpc_url, protocol_version = client._extract_rpc_url(
        {
            "protocolVersion": "1.0",
            "supportedInterfaces": [
                {
                    "protocolBinding": "HTTP+JSON",
                    "url": "https://example.com/http-json",
                },
                {
                    "protocolBinding": "JSONRPC",
                    "protocolVersion": "1.0",
                    "url": "https://example.com/rpc",
                },
            ],
        },
        "https://example.com/.well-known/agent-card.json",
    )

    assert rpc_url == "https://example.com/rpc"
    assert protocol_version == "1.0"


def test_profile_from_config_supports_terminal_transport() -> None:
    profile = A2AProfile.from_config(
        "bash",
        {
            "label": "Bash",
            "transport": "terminal",
            "executable": "bash",
        },
    )

    assert profile.transport == "terminal"
    assert profile.executable == "bash"
    assert profile.agent_card_url == ""


def test_terminal_command_and_output_parsing_for_posix_shell() -> None:
    marker = "__ASTRBOT_DONE_test__"
    command = build_terminal_command("bash", "pwd", marker)

    assert marker in command
    assert f"{marker}:BEGIN" in command
    assert '"$PWD"' in command

    result = parse_terminal_output(
        (
            "pwd\r\n"
            f"{marker}:BEGIN\r\n"
            "/home/steve/project\r\n"
            f"{marker}:0:/home/steve/project\r\n"
        ),
        marker,
    )

    assert result.output == "/home/steve/project"
    assert result.cwd == "/home/steve/project"
    assert result.exit_code == 0


def test_a2a_redirector_schema_uses_template_list_defaults(tmp_path) -> None:
    schema_path = (
        Path(__file__).resolve().parents[2]
        / "astrbot"
        / "builtin_stars"
        / "a2a_redirector"
        / "_conf_schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    config = AstrBotConfig(
        config_path=str(tmp_path / "a2a_redirector.json"),
        schema=schema,
    )

    assert config.profiles[0]["profile_key"] == "bash"
    assert config.profiles[0]["__template_key"] == "terminal"
    assert config.require_admin is True


def test_profile_entries_to_mapping_supports_template_list() -> None:
    profiles = _profile_entries_to_mapping(DEFAULT_PROFILE_ENTRIES)

    assert profiles["bash"]["transport"] == "terminal"
    assert profiles["codex"]["transport"] == "a2a"
    assert profiles["codex"]["agent_card_url"] == ""


def test_profile_mapping_to_entries_preserves_profile_key() -> None:
    entries = _profile_mapping_to_entries(
        {
            "codex": {
                "transport": "a2a",
                "label": "Codex",
                "agent_card_url": "http://127.0.0.1/.well-known/agent-card.json",
            }
        }
    )

    assert entries == [
        {
            "__template_key": "a2a",
            "profile_key": "codex",
            "transport": "a2a",
            "label": "Codex",
            "agent_card_url": "http://127.0.0.1/.well-known/agent-card.json",
        }
    ]


def test_terminal_session_read_until_marker_converts_eio_to_bridge_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = TerminalSession(executable="/bin/sh", working_directory=".")
    session.master_fd = 123
    session.process = types.SimpleNamespace(returncode=None)

    monkeypatch.setattr(
        "astrbot.builtin_stars.a2a_redirector.terminal_bridge.select.select",
        lambda *_args, **_kwargs: ([123], [], []),
    )

    def raise_eio(_fd: int, _size: int) -> bytes:
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(
        "astrbot.builtin_stars.a2a_redirector.terminal_bridge.os.read",
        raise_eio,
    )

    with pytest.raises(
        TerminalBridgeError,
        match="Terminal session ended before the command completed.",
    ):
        session._read_until_marker("__ASTRBOT_DONE_test__", timeout_seconds=1)


@pytest.mark.skipif(shutil.which("fish") is None, reason="fish is not installed")
def test_terminal_session_supports_fish_interactive_shell(tmp_path: Path) -> None:
    async def run() -> None:
        session = await TerminalSession.create(
            executable="fish",
            working_directory=str(tmp_path),
        )
        try:
            result = await session.execute("pwd", timeout_seconds=10)
        finally:
            await session.close()

        assert result.exit_code == 0
        assert Path(result.cwd) == tmp_path.resolve()
        assert result.output == str(tmp_path.resolve())

    import asyncio

    asyncio.run(run())
