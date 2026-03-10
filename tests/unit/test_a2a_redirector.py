from astrbot.builtin_stars.a2a_redirector.a2a_client import (
    A2AClient,
    build_send_params,
    extract_reply,
)
from astrbot.builtin_stars.a2a_redirector.models import A2AProfile, SessionBinding
from astrbot.builtin_stars.a2a_redirector.terminal_bridge import (
    build_terminal_command,
    parse_terminal_output,
)


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
    assert '"$PWD"' in command

    result = parse_terminal_output(
        f"/home/steve/project\r\n{marker}:0:/home/steve/project\r\n",
        marker,
    )

    assert result.output.endswith("/home/steve/project")
    assert result.cwd == "/home/steve/project"
    assert result.exit_code == 0
