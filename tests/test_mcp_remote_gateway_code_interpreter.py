import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from data.plugins.astrbot_plugin_mcp_remote_gateway.main import McpRemoteGatewayPlugin


class DummyContext:
    def register_web_api(self, route, view_handler, methods, desc):
        self._route = route
        self._view_handler = view_handler
        self._methods = methods
        self._desc = desc

    def get_config(self, umo=None):
        return {
            "provider_settings": {
                "computer_use_require_admin": True,
                "sandbox": {"booter": "shipyard"},
            }
        }


class DummyTool:
    def __init__(self, name: str):
        self.name = name


class DummyCallResult:
    def __init__(self, text: str = "ok"):
        self.isError = False
        self.content = [{"type": "text", "text": text}]
        self.structuredContent = None
        self.meta = None


class DummyClient:
    def __init__(self):
        self.session = object()
        self.tools = [DummyTool("ping")]
        self.call_tool_with_reconnect = AsyncMock(return_value=DummyCallResult("pong"))


@pytest.fixture
def base_config():
    return {
        "enabled": True,
        "servers": [
            {
                "name": "s1",
                "active": True,
                "url": "https://example.com/mcp",
                "transport": "sse",
                "timeout": 10,
                "sse_read_timeout": 300,
                "priority": 100,
            }
        ],
        "enable_code_execution": True,
        "code_execution_runtime": "sandbox",
        "code_exec_timeout_sec": 20,
        "code_exec_max_code_len": 1000,
        "bridge_public_base_url": "https://bridge.example.com",
        "bridge_token_ttl_sec": 2,
        "bridge_token_max_calls": 2,
        "bridge_max_payload_bytes": 4096,
        "code_exec_require_admin": True,
        "monitor_interval_sec": 999,
    }


@pytest.fixture
def plugin(base_config):
    p = McpRemoteGatewayPlugin(DummyContext(), base_config)
    p._clients["s1"] = DummyClient()
    return p


def make_event(role: str = "admin", umo: str = "qq:group:123"):
    return SimpleNamespace(
        role=role,
        unified_msg_origin=umo,
        get_sender_id=lambda: "u-1",
    )


@pytest.mark.asyncio
async def test_tool_exposure_changed(plugin):
    assert hasattr(plugin, "mcp_discover")
    assert hasattr(plugin, "mcp_code_interpreter")
    assert not hasattr(plugin, "mcp_exec")


@pytest.mark.asyncio
async def test_bridge_token_ttl_and_quota(plugin):
    token_state = plugin._mint_bridge_token("umo-1")

    ok1, err1 = plugin._consume_bridge_token(token_state.token, "umo-1")
    ok2, err2 = plugin._consume_bridge_token(token_state.token, "umo-1")
    ok3, err3 = plugin._consume_bridge_token(token_state.token, "umo-1")

    assert ok1 is True and err1 == ""
    assert ok2 is True and err2 == ""
    assert ok3 is False and "quota" in err3

    token_state2 = plugin._mint_bridge_token("umo-2")
    token_state2.expires_at = 0.0
    ok4, err4 = plugin._consume_bridge_token(token_state2.token, "umo-2")
    assert ok4 is False and "expired" in err4


@pytest.mark.asyncio
async def test_runtime_sandbox_requires_public_bridge_url(base_config, monkeypatch):
    cfg = dict(base_config)
    cfg["bridge_public_base_url"] = ""
    p = McpRemoteGatewayPlugin(DummyContext(), cfg)
    ev = make_event("admin")

    resp = await p.mcp_code_interpreter(ev, code="print('x')", timeout_sec=3)
    data = json.loads(resp)

    assert data["ok"] is False
    assert "bridge_public_base_url" in data["error"]


@pytest.mark.asyncio
async def test_runtime_selection_sandbox(plugin, monkeypatch):
    ev = make_event("admin")

    fake_booter = SimpleNamespace(
        python=SimpleNamespace(
            exec=AsyncMock(
                return_value={
                    "data": {"output": {"text": "hello", "images": []}, "error": ""}
                }
            )
        )
    )

    async def fake_get_booter(context, session_id):
        return fake_booter

    monkeypatch.setattr(
        "data.plugins.astrbot_plugin_mcp_remote_gateway.main.get_booter",
        fake_get_booter,
    )

    resp = await plugin.mcp_code_interpreter(ev, code="print('ok')", timeout_sec=8)
    data = json.loads(resp)

    assert data["ok"] is True
    assert data["runtime"] == "sandbox"
    assert "hello" in data["result"]["stdout"]
    fake_booter.python.exec.assert_awaited_once()


@pytest.mark.asyncio
async def test_runtime_selection_local(base_config, monkeypatch):
    cfg = dict(base_config)
    cfg["code_execution_runtime"] = "local"
    p = McpRemoteGatewayPlugin(DummyContext(), cfg)
    ev = make_event("admin")

    fake_local_booter = SimpleNamespace(
        python=SimpleNamespace(
            exec=AsyncMock(
                return_value={
                    "data": {"output": {"text": "local-ok", "images": []}, "error": ""}
                }
            )
        )
    )

    monkeypatch.setattr(
        "data.plugins.astrbot_plugin_mcp_remote_gateway.main.get_local_booter",
        lambda: fake_local_booter,
    )

    resp = await p.mcp_code_interpreter(ev, code="print('ok')", timeout_sec=8)
    data = json.loads(resp)

    assert data["ok"] is True
    assert data["runtime"] == "local"
    assert "local-ok" in data["result"]["stdout"]
    fake_local_booter.python.exec.assert_awaited_once()


@pytest.mark.asyncio
async def test_admin_required(plugin):
    ev = make_event("member")

    resp = await plugin.mcp_code_interpreter(ev, code="print('blocked')", timeout_sec=3)
    data = json.loads(resp)

    assert data["ok"] is False
    assert "Permission denied" in data["error"]


@pytest.mark.asyncio
async def test_prelude_contains_mcp_call_config(plugin):
    prelude = plugin._build_code_prelude(
        event=make_event("admin", "umo-x"),
        session_id="umo-x",
        bridge_token="tok-x",
    )
    assert "class _MCPBridge" in prelude
    assert "def call(self, server, tool, **kwargs)" in prelude
    assert "mcp = _MCPBridge(_MCP_BRIDGE)" in prelude


@pytest.mark.asyncio
async def test_exec_internal_argument_merge_and_error(plugin):
    payload_ok = await plugin._exec_tool_internal(
        server_name="s1",
        tool_name="ping",
        arguments={"a": 1},
        arguments_json='{"b":2}',
    )
    assert payload_ok["ok"] is True
    assert payload_ok["result"]["is_error"] is False

    payload_bad = await plugin._exec_tool_internal(
        server_name="s1",
        tool_name="ping",
        arguments_json='{"broken":',
    )
    assert payload_bad["ok"] is False
    assert "invalid arguments_json" in payload_bad["error"]
