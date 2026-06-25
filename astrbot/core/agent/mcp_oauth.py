from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qs, urlparse

import httpx
from pydantic import BaseModel, ConfigDict

from astrbot import logger
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

try:
    from mcp.client.auth import OAuthClientProvider, TokenStorage
    from mcp.client.auth.extensions.client_credentials import (
        ClientCredentialsOAuthProvider,
    )
    from mcp.shared.auth import (
        OAuthClientInformationFull,
        OAuthClientMetadata,
        OAuthToken,
    )
except (ModuleNotFoundError, ImportError):
    OAuthClientProvider = None  # type: ignore[assignment]
    ClientCredentialsOAuthProvider = None  # type: ignore[assignment]
    TokenStorage = object  # type: ignore[assignment]
    OAuthClientInformationFull = None  # type: ignore[assignment]
    OAuthClientMetadata = None  # type: ignore[assignment]
    OAuthToken = None  # type: ignore[assignment]


class MCPOAuthError(Exception):
    """Base exception for MCP OAuth flows."""


class MCPOAuthAuthorizationRequiredError(MCPOAuthError):
    """Raised when interactive OAuth authorization is required."""


class MCPOAuthConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    grant_type: Literal["authorization_code", "client_credentials"] = (
        "authorization_code"
    )
    client_id: str | None = None
    client_secret: str | None = None
    token_endpoint_auth_method: (
        Literal["none", "client_secret_post", "client_secret_basic"] | None
    ) = None
    scope: str | None = None
    redirect_uri: str | None = None
    timeout: float = 300.0
    client_name: str | None = "AstrBot MCP Client"
    client_uri: str | None = None
    logo_uri: str | None = None
    contacts: list[str] | None = None
    tos_uri: str | None = None
    policy_uri: str | None = None
    software_id: str | None = None
    software_version: str | None = None
    client_metadata_url: str | None = None


_MCP_CONFIG_FILENAME = "mcp_server.json"
_MCP_OAUTH_CALLBACK_BASE_URL_ENV = "ASTRBOT_MCP_OAUTH_CALLBACK_BASE_URL"
_OAUTH_TOKEN_KEYS = {
    "access_token",
    "refresh_token",
    "token_type",
    "expires_in",
    "token_expires_at",
    "tokens",
}
_OAUTH_STORAGE_KEYS = _OAUTH_TOKEN_KEYS | {"client_info", "redirect_uri"}


def _prepare_config(config: Mapping[str, Any]) -> dict[str, Any]:
    prepared = dict(config)
    if prepared.get("mcpServers"):
        first_key = next(iter(prepared["mcpServers"]))
        prepared = dict(prepared["mcpServers"][first_key])
    prepared.pop("active", None)
    return prepared


def get_mcp_oauth_config(config: Mapping[str, Any]) -> MCPOAuthConfig | None:
    prepared = _prepare_config(config)
    oauth_config = prepared.get("oauth2") or prepared.get("oauth")
    if not isinstance(oauth_config, dict):
        return None
    return MCPOAuthConfig.model_validate(oauth_config)


def has_mcp_oauth_config(config: Mapping[str, Any]) -> bool:
    return get_mcp_oauth_config(config) is not None


def _get_storage_fingerprint(config: Mapping[str, Any]) -> str:
    prepared = _prepare_config(config)
    oauth_raw = prepared.get("oauth2") or prepared.get("oauth")
    if not isinstance(oauth_raw, dict):
        raise MCPOAuthError("OAuth 2.0 is not configured for this MCP server.")
    oauth_for_fingerprint = {
        key: value for key, value in oauth_raw.items() if key not in _OAUTH_STORAGE_KEYS
    }
    oauth_config = MCPOAuthConfig.model_validate(oauth_for_fingerprint)

    fingerprint_payload = {
        "url": prepared.get("url"),
        "transport": prepared.get("transport") or prepared.get("type"),
        "grant_type": oauth_config.grant_type,
        "client_id": oauth_config.client_id,
        "client_secret": oauth_config.client_secret,
        "token_endpoint_auth_method": oauth_config.token_endpoint_auth_method,
        "scope": oauth_config.scope,
        "client_metadata_url": oauth_config.client_metadata_url,
    }
    canonical = json.dumps(
        fingerprint_payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _get_mcp_config_path() -> Path:
    return Path(get_astrbot_data_path()) / _MCP_CONFIG_FILENAME


def _get_first_mcp_server_name(config: Mapping[str, Any]) -> str | None:
    mcp_servers = config.get("mcpServers")
    if isinstance(mcp_servers, dict) and mcp_servers:
        return str(next(iter(mcp_servers)))
    name = config.get("name")
    return str(name) if isinstance(name, str) and name else None


def _get_server_config_ref(config: dict[str, Any]) -> dict[str, Any]:
    mcp_servers = config.get("mcpServers")
    if isinstance(mcp_servers, dict) and mcp_servers:
        first_server = mcp_servers[next(iter(mcp_servers))]
        if isinstance(first_server, dict):
            return first_server
    return config


class MCPConfigTokenStorage(TokenStorage):
    def __init__(
        self,
        config: Mapping[str, Any],
        *,
        server_name: str | None = None,
    ) -> None:
        self._config = config if isinstance(config, dict) else dict(config)
        self._server_name = server_name or _get_first_mcp_server_name(self._config)
        self._fingerprint = _get_storage_fingerprint(self._config)
        self._lock = asyncio.Lock()

    @classmethod
    def from_mcp_config(
        cls,
        config: Mapping[str, Any],
        *,
        server_name: str | None = None,
    ) -> MCPConfigTokenStorage:
        return cls(config, server_name=server_name)

    def _load_mcp_config_unlocked(self) -> dict[str, Any]:
        config_path = _get_mcp_config_path()
        if not config_path.exists():
            return {"mcpServers": {}}
        try:
            loaded = json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                return loaded
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to load MCP config for OAuth token storage %s: %s",
                config_path,
                exc,
            )
        return {"mcpServers": {}}

    def _save_mcp_config_unlocked(self, config: dict[str, Any]) -> None:
        config_path = _get_mcp_config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps(config, ensure_ascii=False, indent=4),
            encoding="utf-8",
        )

    def _find_server_config_unlocked(
        self,
        mcp_config: dict[str, Any],
    ) -> dict[str, Any] | None:
        servers = mcp_config.get("mcpServers")
        if not isinstance(servers, dict):
            return None

        if self._server_name:
            server_config = servers.get(self._server_name)
            if isinstance(server_config, dict):
                return server_config

        for server_config in servers.values():
            if not isinstance(server_config, dict):
                continue
            try:
                if _get_storage_fingerprint(server_config) == self._fingerprint:
                    return server_config
            except MCPOAuthError:
                continue
        return None

    def _get_oauth_payload_unlocked(
        self,
        server_config: dict[str, Any],
        *,
        create: bool = False,
    ) -> dict[str, Any]:
        oauth_key = (
            "oauth2"
            if "oauth2" in server_config or "oauth" not in server_config
            else "oauth"
        )
        oauth_payload = server_config.get(oauth_key)
        if isinstance(oauth_payload, dict):
            return oauth_payload
        if create:
            oauth_payload = {}
            server_config[oauth_key] = oauth_payload
            return oauth_payload
        return {}

    def _read_oauth_payload_unlocked(self) -> dict[str, Any]:
        mcp_config = self._load_mcp_config_unlocked()
        server_config = self._find_server_config_unlocked(mcp_config)
        if server_config is not None:
            return dict(self._get_oauth_payload_unlocked(server_config))
        return dict(
            self._get_oauth_payload_unlocked(_get_server_config_ref(self._config))
        )

    def _mutate_oauth_payload_unlocked(self, mutator) -> None:
        mcp_config = self._load_mcp_config_unlocked()
        server_config = self._find_server_config_unlocked(mcp_config)
        if server_config is not None:
            oauth_payload = self._get_oauth_payload_unlocked(server_config, create=True)
            mutator(oauth_payload)
            direct_oauth_payload = self._get_oauth_payload_unlocked(
                _get_server_config_ref(self._config),
                create=True,
            )
            if direct_oauth_payload is not oauth_payload:
                direct_oauth_payload.clear()
                direct_oauth_payload.update(oauth_payload)
            self._save_mcp_config_unlocked(mcp_config)
            return

        direct_config = _get_server_config_ref(self._config)
        mutator(self._get_oauth_payload_unlocked(direct_config, create=True))

    async def get_tokens(self) -> OAuthToken | None:
        async with self._lock:
            payload = self._read_oauth_payload_unlocked()
        token_payload = payload.get("tokens")
        if not isinstance(token_payload, dict):
            token_payload = {
                key: payload[key]
                for key in (
                    "access_token",
                    "token_type",
                    "expires_in",
                    "scope",
                    "refresh_token",
                )
                if key in payload
            }
        if not token_payload or "access_token" not in token_payload:
            return None
        return OAuthToken.model_validate(token_payload)

    async def set_tokens(self, tokens: OAuthToken) -> None:
        async with self._lock:
            token_payload = tokens.model_dump(mode="json", exclude_none=True)

            def mutate(payload: dict[str, Any]) -> None:
                for key in _OAUTH_TOKEN_KEYS:
                    payload.pop(key, None)
                payload.update(token_payload)
                if tokens.expires_in is not None:
                    payload["token_expires_at"] = time.time() + float(tokens.expires_in)

            self._mutate_oauth_payload_unlocked(mutate)

    async def clear_tokens(self) -> None:
        async with self._lock:

            def mutate(payload: dict[str, Any]) -> None:
                for key in _OAUTH_TOKEN_KEYS:
                    payload.pop(key, None)

            self._mutate_oauth_payload_unlocked(mutate)

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        async with self._lock:
            payload = self._read_oauth_payload_unlocked()
        client_info_payload = payload.get("client_info")
        if not client_info_payload:
            return None
        return OAuthClientInformationFull.model_validate(client_info_payload)

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        async with self._lock:

            def mutate(payload: dict[str, Any]) -> None:
                payload["client_info"] = client_info.model_dump(
                    mode="json",
                    exclude_none=True,
                )

            self._mutate_oauth_payload_unlocked(mutate)

    async def get_redirect_uri(self) -> str | None:
        async with self._lock:
            payload = self._read_oauth_payload_unlocked()
        redirect_uri = payload.get("redirect_uri")
        return str(redirect_uri) if isinstance(redirect_uri, str) else None

    async def set_redirect_uri(self, redirect_uri: str) -> None:
        async with self._lock:

            def mutate(payload: dict[str, Any]) -> None:
                payload["redirect_uri"] = redirect_uri

            self._mutate_oauth_payload_unlocked(mutate)

    async def get_token_expires_at(self) -> float | None:
        async with self._lock:
            payload = self._read_oauth_payload_unlocked()
        expires_at = payload.get("token_expires_at")
        if isinstance(expires_at, (int, float)):
            return float(expires_at)
        return None


def _render_qr_ascii(data: str) -> str:
    """Render a QR code as terminal-friendly text.

    Args:
        data: The URL or text to encode.

    Returns:
        An ASCII QR code string, or an empty string if rendering fails.
    """
    try:
        import qrcode

        qr = qrcode.QRCode(border=1)
        qr.add_data(data)
        qr.make(fit=True)
        output = io.StringIO()
        qr.print_ascii(out=output, tty=False)
        return output.getvalue().rstrip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to render MCP OAuth QR code: %s", exc)
        return ""


def log_mcp_oauth_authorization_url(
    authorization_url: str,
    *,
    server_name: str | None = None,
) -> None:
    """Log an OAuth login URL and QR code at info level.

    Args:
        authorization_url: The authorization URL users should open.
        server_name: Optional MCP server name for log context.
    """
    qr_ascii = _render_qr_ascii(authorization_url)
    server_label = server_name or "unknown"
    if qr_ascii:
        logger.info(
            "MCP OAuth authorization required for %s. Login URL: %s\nQR code:\n%s",
            server_label,
            authorization_url,
            qr_ascii,
        )
        return
    logger.info(
        "MCP OAuth authorization required for %s. Login URL: %s",
        server_label,
        authorization_url,
    )


def get_mcp_oauth_callback_base_url(config: Mapping[str, Any]) -> str:
    """Resolve the callback base URL used for automatic log-based OAuth login.

    Args:
        config: MCP server config.

    Returns:
        Base URL used to build `/mcp/oauth/callback`.
    """
    oauth_config = get_mcp_oauth_config(config)
    if oauth_config and oauth_config.redirect_uri:
        parsed = urlparse(oauth_config.redirect_uri)
        if parsed.scheme and parsed.netloc:
            suffix = "/mcp/oauth/callback"
            path = parsed.path
            if path.endswith(suffix):
                base_path = path[: -len(suffix)].rstrip("/")
                return (
                    parsed._replace(
                        path=base_path,
                        params="",
                        query="",
                        fragment="",
                    )
                    .geturl()
                    .rstrip("/")
                )
            return f"{parsed.scheme}://{parsed.netloc}"

    return os.getenv(_MCP_OAUTH_CALLBACK_BASE_URL_ENV, "http://127.0.0.1:6185")


def _get_token_endpoint_auth_method(oauth_config: MCPOAuthConfig) -> str:
    if oauth_config.token_endpoint_auth_method:
        return oauth_config.token_endpoint_auth_method
    if oauth_config.client_secret:
        return "client_secret_basic"
    return "none"


async def _raise_interactive_redirect_required(_: str) -> None:
    raise MCPOAuthAuthorizationRequiredError(
        "OAuth 2.0 authorization is required. Complete authorization in the MCP server dialog first.",
    )


async def _raise_interactive_callback_required() -> tuple[str, str | None]:
    raise MCPOAuthAuthorizationRequiredError(
        "OAuth 2.0 authorization is required. Complete authorization in the MCP server dialog first.",
    )


if OAuthClientProvider is not None:

    class AstrBotOAuthClientProvider(OAuthClientProvider):
        async def _initialize(self) -> None:
            await super()._initialize()

            storage = self.context.storage
            if not isinstance(storage, MCPConfigTokenStorage):
                return

            expires_at = await storage.get_token_expires_at()
            if expires_at is not None:
                self.context.token_expiry_time = expires_at

            if (
                expires_at is not None
                and time.time() > expires_at
                and not self.context.can_refresh_token()
            ):
                raise MCPOAuthAuthorizationRequiredError(
                    "The stored OAuth 2.0 token has expired. Complete authorization in the MCP server dialog again.",
                )

else:
    AstrBotOAuthClientProvider = None  # type: ignore[assignment]


if ClientCredentialsOAuthProvider is not None:

    class AstrBotClientCredentialsOAuthProvider(ClientCredentialsOAuthProvider):
        async def _initialize(self) -> None:
            await super()._initialize()

            storage = self.context.storage
            if not isinstance(storage, MCPConfigTokenStorage):
                return

            expires_at = await storage.get_token_expires_at()
            if expires_at is not None:
                self.context.token_expiry_time = expires_at

else:
    AstrBotClientCredentialsOAuthProvider = None  # type: ignore[assignment]


def _build_client_metadata(
    oauth_config: MCPOAuthConfig,
    *,
    redirect_uri: str,
) -> OAuthClientMetadata:
    return OAuthClientMetadata(
        redirect_uris=[redirect_uri],
        token_endpoint_auth_method=_get_token_endpoint_auth_method(oauth_config),
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        scope=oauth_config.scope,
        client_name=oauth_config.client_name,
        client_uri=oauth_config.client_uri,
        logo_uri=oauth_config.logo_uri,
        contacts=oauth_config.contacts,
        tos_uri=oauth_config.tos_uri,
        policy_uri=oauth_config.policy_uri,
        software_id=oauth_config.software_id,
        software_version=oauth_config.software_version,
    )


async def _seed_client_info_if_needed(
    storage: MCPConfigTokenStorage,
    oauth_config: MCPOAuthConfig,
    *,
    redirect_uri: str,
) -> None:
    if not oauth_config.client_id:
        return

    client_info = OAuthClientInformationFull(
        redirect_uris=[redirect_uri],
        client_id=oauth_config.client_id,
        client_secret=oauth_config.client_secret,
        grant_types=["authorization_code", "refresh_token"],
        token_endpoint_auth_method=_get_token_endpoint_auth_method(oauth_config),
        response_types=["code"],
        scope=oauth_config.scope,
        client_name=oauth_config.client_name,
        client_uri=oauth_config.client_uri,
        logo_uri=oauth_config.logo_uri,
        contacts=oauth_config.contacts,
        tos_uri=oauth_config.tos_uri,
        policy_uri=oauth_config.policy_uri,
        software_id=oauth_config.software_id,
        software_version=oauth_config.software_version,
    )
    await storage.set_client_info(client_info)


@dataclass(slots=True)
class MCPOAuthPendingFlow:
    flow_id: str
    config: dict[str, Any]
    redirect_uri: str
    server_name: str | None = None
    log_authorization: bool = False
    created_at: float = field(default_factory=time.time)
    status: Literal[
        "initializing",
        "awaiting_user",
        "authorizing",
        "completed",
        "failed",
    ] = "initializing"
    authorization_url: str | None = None
    error: str | None = None
    callback_code: str | None = None
    callback_state: str | None = None
    callback_error: str | None = None
    oauth_state: str | None = None
    url_ready_event: asyncio.Event = field(default_factory=asyncio.Event)
    callback_ready_event: asyncio.Event = field(default_factory=asyncio.Event)
    done_event: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None

    async def handle_redirect(self, authorization_url: str) -> None:
        self.authorization_url = authorization_url
        parsed_url = urlparse(authorization_url)
        self.oauth_state = parse_qs(parsed_url.query).get("state", [None])[0]
        self.status = "awaiting_user"
        if self.log_authorization:
            log_mcp_oauth_authorization_url(
                authorization_url,
                server_name=self.server_name,
            )
        self.url_ready_event.set()

    async def wait_for_callback(self) -> tuple[str, str | None]:
        await self.callback_ready_event.wait()
        if self.callback_error:
            raise MCPOAuthError(self.callback_error)
        self.status = "authorizing"
        return self.callback_code or "", self.callback_state

    def submit_callback(
        self,
        *,
        code: str | None,
        state: str | None,
        error: str | None,
    ) -> None:
        self.callback_code = code
        self.callback_state = state
        self.callback_error = error
        self.callback_ready_event.set()


async def create_mcp_http_auth(
    config: Mapping[str, Any],
    *,
    interactive_flow: MCPOAuthPendingFlow | None = None,
    server_name: str | None = None,
) -> httpx.Auth | None:
    prepared = _prepare_config(config)
    if "url" not in prepared:
        return None

    oauth_config = get_mcp_oauth_config(prepared)
    if oauth_config is None:
        return None

    if OAuthClientProvider is None or OAuthClientMetadata is None:
        raise MCPOAuthError("The installed MCP dependency does not support OAuth 2.0.")

    storage = MCPConfigTokenStorage.from_mcp_config(prepared, server_name=server_name)

    if oauth_config.grant_type == "client_credentials":
        if not oauth_config.client_id or not oauth_config.client_secret:
            raise MCPOAuthError(
                "OAuth client_credentials requires both client_id and client_secret.",
            )
        if AstrBotClientCredentialsOAuthProvider is None:
            raise MCPOAuthError(
                "The installed MCP dependency does not support OAuth 2.0 client_credentials.",
            )
        return AstrBotClientCredentialsOAuthProvider(
            server_url=str(prepared["url"]),
            storage=storage,
            client_id=oauth_config.client_id,
            client_secret=oauth_config.client_secret,
            token_endpoint_auth_method=_get_token_endpoint_auth_method(oauth_config),
            scopes=oauth_config.scope,
        )

    if oauth_config.grant_type != "authorization_code":
        raise MCPOAuthError(
            f"Unsupported MCP OAuth grant_type: {oauth_config.grant_type}",
        )

    if interactive_flow is None:
        stored_tokens = await storage.get_tokens()
        if stored_tokens is None:
            raise MCPOAuthAuthorizationRequiredError(
                "OAuth 2.0 authorization is required. Complete authorization in the MCP server dialog first.",
            )

        expires_at = await storage.get_token_expires_at()
        if (
            expires_at is not None
            and time.time() > expires_at
            and not stored_tokens.refresh_token
        ):
            raise MCPOAuthAuthorizationRequiredError(
                "The stored OAuth 2.0 token has expired and no refresh token is available. Complete authorization in the MCP server dialog again.",
            )

    redirect_uri = (
        interactive_flow.redirect_uri
        if interactive_flow is not None
        else oauth_config.redirect_uri
        or await storage.get_redirect_uri()
        or "http://127.0.0.1/astrbot/mcp/oauth/callback/pending"
    )

    await storage.set_redirect_uri(redirect_uri)
    await _seed_client_info_if_needed(storage, oauth_config, redirect_uri=redirect_uri)

    redirect_handler = (
        interactive_flow.handle_redirect
        if interactive_flow is not None
        else _raise_interactive_redirect_required
    )
    callback_handler = (
        interactive_flow.wait_for_callback
        if interactive_flow is not None
        else _raise_interactive_callback_required
    )

    if AstrBotOAuthClientProvider is None:
        raise MCPOAuthError("The installed MCP dependency does not support OAuth 2.0.")

    return AstrBotOAuthClientProvider(
        server_url=str(prepared["url"]),
        client_metadata=_build_client_metadata(
            oauth_config,
            redirect_uri=redirect_uri,
        ),
        storage=storage,
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
        timeout=oauth_config.timeout,
        client_metadata_url=oauth_config.client_metadata_url,
    )


async def get_mcp_oauth_state(config: Mapping[str, Any]) -> dict[str, Any]:
    oauth_config = get_mcp_oauth_config(config)
    if oauth_config is None:
        return {
            "oauth2_enabled": False,
            "oauth2_authorized": False,
            "oauth2_grant_type": None,
        }

    if oauth_config.grant_type == "client_credentials":
        return {
            "oauth2_enabled": True,
            "oauth2_authorized": True,
            "oauth2_grant_type": oauth_config.grant_type,
        }

    storage = MCPConfigTokenStorage.from_mcp_config(config)
    tokens = await storage.get_tokens()
    return {
        "oauth2_enabled": True,
        "oauth2_authorized": tokens is not None,
        "oauth2_grant_type": oauth_config.grant_type,
    }


async def _probe_http_oauth_connection(
    config: Mapping[str, Any],
    auth: httpx.Auth,
) -> None:
    prepared = _prepare_config(config)
    url = str(prepared["url"])
    headers = {
        str(key): str(value) for key, value in dict(prepared.get("headers", {})).items()
    }
    timeout_value = float(prepared.get("timeout", 30))
    transport_type = prepared.get("transport") or prepared.get("type") or "sse"

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=timeout_value,
    ) as client:
        if transport_type == "streamable_http":
            response = await client.post(
                url,
                headers={
                    **headers,
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
                json={
                    "jsonrpc": "2.0",
                    "method": "initialize",
                    "id": 0,
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {
                            "name": "astrbot-oauth-probe",
                            "version": "1.0.0",
                        },
                    },
                },
                auth=auth,
            )
        else:
            response = await client.get(
                url,
                headers={
                    **headers,
                    "Accept": "application/json, text/event-stream",
                },
                auth=auth,
            )

    if response.status_code != 200:
        raise MCPOAuthError(
            f"OAuth authorization probe failed: HTTP {response.status_code} {response.reason_phrase}",
        )


class MCPOAuthManager:
    _FLOW_TTL_SECONDS = 900

    def __init__(self) -> None:
        self._flows: dict[str, MCPOAuthPendingFlow] = {}
        self._state_to_flow_id: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def _prune_flows(self) -> None:
        threshold = time.time() - self._FLOW_TTL_SECONDS
        async with self._lock:
            expired_ids = [
                flow_id
                for flow_id, flow in self._flows.items()
                if flow.created_at < threshold
            ]
            for flow_id in expired_ids:
                expired_states = [
                    state
                    for state, state_flow_id in self._state_to_flow_id.items()
                    if state_flow_id == flow_id
                ]
                for state in expired_states:
                    self._state_to_flow_id.pop(state, None)
                self._flows.pop(flow_id, None)

    async def _run_flow(self, flow: MCPOAuthPendingFlow) -> None:
        try:
            auth = await create_mcp_http_auth(flow.config, interactive_flow=flow)
            if auth is None:
                raise MCPOAuthError("OAuth 2.0 is not configured for this MCP server.")
            await _probe_http_oauth_connection(flow.config, auth)
            flow.status = "completed"
        except Exception as exc:  # noqa: BLE001
            flow.error = str(exc)
            flow.status = "failed"
            flow.url_ready_event.set()
        finally:
            flow.done_event.set()

    async def start_authorization(
        self,
        config: Mapping[str, Any],
        *,
        callback_base_url: str,
        force: bool = False,
        server_name: str | None = None,
        log_authorization: bool = False,
    ) -> MCPOAuthPendingFlow:
        prepared = _prepare_config(config)
        oauth_config = get_mcp_oauth_config(prepared)
        if oauth_config is None:
            raise MCPOAuthError("OAuth 2.0 is not configured for this MCP server.")
        if oauth_config.grant_type != "authorization_code":
            raise MCPOAuthError(
                "Interactive login is only available for authorization_code flows.",
            )
        if "url" not in prepared:
            raise MCPOAuthError("OAuth 2.0 is only supported for HTTP MCP transports.")

        await self._prune_flows()

        storage = MCPConfigTokenStorage.from_mcp_config(
            prepared,
            server_name=server_name,
        )
        if force:
            await storage.clear_tokens()

        flow_id = uuid.uuid4().hex
        redirect_uri = oauth_config.redirect_uri or (
            f"{callback_base_url.rstrip('/')}/mcp/oauth/callback"
        )
        flow = MCPOAuthPendingFlow(
            flow_id=flow_id,
            config=prepared,
            redirect_uri=redirect_uri,
            server_name=server_name,
            log_authorization=log_authorization,
        )
        flow.task = asyncio.create_task(
            self._run_flow(flow),
            name=f"mcp-oauth:{flow_id}",
        )

        async with self._lock:
            self._flows[flow_id] = flow

        wait_url_task = asyncio.create_task(flow.url_ready_event.wait())
        wait_done_task = asyncio.create_task(flow.done_event.wait())
        try:
            done, pending = await asyncio.wait(
                {wait_url_task, wait_done_task},
                timeout=15,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

            if not done:
                raise MCPOAuthError(
                    "Timed out while preparing the OAuth 2.0 authorization flow.",
                )
        finally:
            if not wait_url_task.done():
                wait_url_task.cancel()
            if not wait_done_task.done():
                wait_done_task.cancel()

        if flow.status == "failed":
            raise MCPOAuthError(flow.error or "Failed to start OAuth 2.0 flow.")

        if flow.oauth_state:
            async with self._lock:
                self._state_to_flow_id[flow.oauth_state] = flow.flow_id

        return flow

    async def submit_callback(
        self,
        flow_id: str | None = None,
        *,
        code: str | None,
        state: str | None,
        error: str | None,
    ) -> None:
        resolved_flow_id = flow_id
        if resolved_flow_id is None and state:
            resolved_flow_id = self._state_to_flow_id.get(state)

        async with self._lock:
            flow = self._flows.get(resolved_flow_id or "")
        if flow is None:
            raise KeyError(flow_id or state or "")
        flow.submit_callback(code=code, state=state, error=error)

    def get_flow_status(self, flow_id: str) -> dict[str, Any]:
        flow = self._flows.get(flow_id)
        if flow is None:
            raise KeyError(flow_id)
        return {
            "flow_id": flow.flow_id,
            "status": flow.status,
            "authorization_url": flow.authorization_url,
            "redirect_uri": flow.redirect_uri,
            "mcp_server_config": flow.config,
            "error": flow.error,
        }
