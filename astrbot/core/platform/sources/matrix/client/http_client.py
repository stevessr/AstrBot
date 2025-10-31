"""
Matrix HTTP Client - Direct implementation without matrix-nio
Implements the Matrix Client-Server API using aiohttp
"""

import aiohttp
import os
import json
from typing import Optional, Dict, Any, List
from astrbot.api import logger


class MatrixHTTPClient:
    """
    Low-level HTTP client for Matrix C-S API
    Does not depend on matrix-nio
    """

    def __init__(self, homeserver: str):
        """
        Initialize Matrix HTTP client

        Args:
            homeserver: Matrix homeserver URL (e.g., https://matrix.org)
        """
        self.homeserver = homeserver.rstrip("/")
        self.access_token: Optional[str] = None
        self.user_id: Optional[str] = None
        self.device_id: Optional[str] = None
        self.session: Optional[aiohttp.ClientSession] = None
        self._next_batch: Optional[str] = None

    async def _ensure_session(self):
        """Ensure aiohttp session exists"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()

    async def close(self):
        """Close the HTTP session"""
        if self.session and not self.session.closed:
            await self.session.close()

    def _get_headers(self) -> Dict[str, str]:
        """Get HTTP headers for authenticated requests"""
        headers = {"Content-Type": "application/json"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    async def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None,
        authenticated: bool = True,
    ) -> Dict[str, Any]:
        """
        Make HTTP request to Matrix server

        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint (e.g., /_matrix/client/v3/login)
            data: JSON data for request body
            params: URL query parameters
            authenticated: Whether to include access token

        Returns:
            Response JSON data

        Raises:
            Exception: On HTTP errors
        """
        await self._ensure_session()

        url = f"{self.homeserver}{endpoint}"
        headers = (
            self._get_headers()
            if authenticated
            else {"Content-Type": "application/json"}
        )

        try:
            async with self.session.request(
                method, url, json=data, params=params, headers=headers
            ) as response:
                response_data = await response.json()

                if response.status >= 400:
                    error_code = response_data.get("errcode", "UNKNOWN")
                    error_msg = response_data.get("error", "Unknown error")
                    raise Exception(
                        f"Matrix API error: {error_code} - {error_msg} (status: {response.status})"
                    )

                return response_data

        except aiohttp.ClientError as e:
            logger.error(f"Matrix HTTP request failed: {e}")
            raise

    async def login_password(
        self,
        user_id: str,
        password: str,
        device_name: str = "AstrBot",
        device_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Login with password

        Args:
            user_id: Matrix user ID
            password: User password
            device_name: Device display name
            device_id: Optional device ID to reuse

        Returns:
            Login response with access_token, device_id, etc.
        """
        data = {
            "type": "m.login.password",
            "identifier": {"type": "m.id.user", "user": user_id},
            "password": password,
            "initial_device_display_name": device_name,
        }
        if device_id:
            data["device_id"] = device_id

        response = await self._request(
            "POST", "/_matrix/client/v3/login", data=data, authenticated=False
        )

        self.access_token = response.get("access_token")
        self.user_id = response.get("user_id")
        self.device_id = response.get("device_id")

        return response

    def restore_login(
        self, user_id: str, access_token: str, device_id: Optional[str] = None
    ):
        """
        Restore login session with access token

        Args:
            user_id: Matrix user ID
            access_token: Access token from previous login
            device_id: Device ID (optional)
        """
        self.user_id = user_id
        self.access_token = access_token
        self.device_id = device_id

    async def whoami(self) -> Dict[str, Any]:
        """
        Get information about the current user

        Returns:
            User information including user_id and device_id
        """
        return await self._request("GET", "/_matrix/client/v3/account/whoami")

    async def sync(
        self,
        since: Optional[str] = None,
        timeout: int = 30000,
        full_state: bool = False,
        filter_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Sync with the Matrix server

        Args:
            since: Sync batch token from previous sync
            timeout: Timeout in milliseconds
            full_state: Whether to return full state
            filter_id: Filter ID for filtering events

        Returns:
            Sync response
        """
        params = {"timeout": timeout}
        if since:
            params["since"] = since
        if full_state:
            params["full_state"] = "true"
        if filter_id:
            params["filter"] = filter_id

        response = await self._request("GET", "/_matrix/client/v3/sync", params=params)

        # Store next_batch for future syncs
        self._next_batch = response.get("next_batch")

        return response

    async def send_message(
        self, room_id: str, msg_type: str, content: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Send a message to a room

        Args:
            room_id: Room ID
            msg_type: Message type (e.g., m.room.message)
            content: Message content

        Returns:
            Send response with event_id
        """
        import time

        txn_id = f"{int(time.time() * 1000)}_{id(content)}"
        endpoint = f"/_matrix/client/v3/rooms/{room_id}/send/{msg_type}/{txn_id}"
        return await self._request("PUT", endpoint, data=content)

    # NOTE: send_to_device is defined later with an optional txn_id parameter.
    # The detailed implementation (including diagnostics) is implemented below
    # to avoid duplicate definitions.

    async def send_room_event(
        self, room_id: str, event_type: str, content: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Send a custom event to a room

        Args:
            room_id: Room ID
            event_type: Event type (e.g., m.key.verification.request)
            content: Event content

        Returns:
            Send response with event_id
        """
        import time

        txn_id = f"txn_{int(time.time() * 1000)}"
        endpoint = f"/_matrix/client/v3/rooms/{room_id}/send/{event_type}/{txn_id}"
        return await self._request("PUT", endpoint, data=content)

    async def upload_file(
        self, data: bytes, content_type: str, filename: str
    ) -> Dict[str, Any]:
        """
        Upload a file to the Matrix media repository

        Args:
            data: File data as bytes
            content_type: MIME type
            filename: Filename

        Returns:
            Upload response with content_uri
        """
        await self._ensure_session()

        url = f"{self.homeserver}/_matrix/media/v3/upload"
        headers = {
            "Content-Type": content_type,
            "Authorization": f"Bearer {self.access_token}",
        }
        params = {"filename": filename}

        async with self.session.post(
            url, data=data, headers=headers, params=params
        ) as response:
            response_data = await response.json()

            if response.status >= 400:
                error_code = response_data.get("errcode", "UNKNOWN")
                error_msg = response_data.get("error", "Unknown error")
                raise Exception(
                    f"Matrix media upload error: {error_code} - {error_msg}"
                )

            return response_data

    async def download_file(self, mxc_url: str) -> bytes:
        """
        Download a file from the Matrix media repository
        按照 Matrix spec 正确实现媒体下载
        
        参考：https://spec.matrix.org/latest/client-server-api/#get_matrixmediav3downloadservernamemediaid

        Args:
            mxc_url: MXC URL (mxc://server/media_id)

        Returns:
            File data as bytes
        """
        await self._ensure_session()

        # Parse MXC URL
        if not mxc_url.startswith("mxc://"):
            raise ValueError(f"Invalid MXC URL: {mxc_url}")

        parts = mxc_url[6:].split("/", 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid MXC URL format: {mxc_url}")

        server_name, media_id = parts

        # 按照 Matrix spec，所有媒体下载都通过用户的 homeserver
        # 不管媒体来自哪个服务器，都使用认证请求
        # 参考：https://spec.matrix.org/latest/client-server-api/#id429
        
        # Try multiple download endpoints
        # 1. 新的认证媒体 API (Matrix v1.11+) - 需要认证
        # 2. 传统媒体 API (v3/r0) - 可能需要认证
        # 3. 带 allow_redirect 参数的版本
        endpoints = [
            # 新的认证媒体 API (推荐)
            f"/_matrix/client/v1/media/download/{server_name}/{media_id}",
            # 传统 API
            f"/_matrix/media/v3/download/{server_name}/{media_id}",
            f"/_matrix/media/r0/download/{server_name}/{media_id}",
            # 带重定向参数
            f"/_matrix/media/v3/download/{server_name}/{media_id}?allow_redirect=true",
            f"/_matrix/media/r0/download/{server_name}/{media_id}?allow_redirect=true",
        ]

        last_error = None
        last_status = None

        for endpoint in endpoints:
            url = f"{self.homeserver}{endpoint}"

            # 根据 Matrix spec，媒体下载需要认证
            # 使用 Authorization header 进行认证
            headers = {}
            if self.access_token:
                headers["Authorization"] = f"Bearer {self.access_token}"

            try:
                logger.debug(f"Downloading media from: {url}")
                async with self.session.get(url, headers=headers, allow_redirects=True) as response:
                    last_status = response.status
                    if response.status == 200:
                        logger.debug(f"✅ Successfully downloaded media from {endpoint}")
                        return await response.read()
                    elif response.status == 404:
                        logger.debug(f"Got 404 on {endpoint}, trying next endpoint...")
                        last_error = f"Media not found: {response.status}"
                        continue
                    elif response.status == 403:
                        # 403 通常意味着认证问题或权限问题
                        logger.warning(f"Got 403 on {endpoint} (auth problem or private media)")
                        last_error = f"Access denied: {response.status}"
                        continue
                    else:
                        last_error = f"HTTP {response.status}"
                        logger.debug(f"Got status {response.status} from {endpoint}")
            except aiohttp.ClientError as e:
                last_error = str(e)
                logger.debug(f"Network error downloading from {endpoint}: {e}")
                continue
            except Exception as e:
                last_error = str(e)
                logger.debug(f"Exception downloading from {endpoint}: {e}")
                continue

        # 所有端点都失败了，尝试缩略图作为最后手段
        if last_status in [403, 404]:
            logger.debug("Trying thumbnail endpoints as fallback...")
            thumbnail_endpoints = [
                # 新的认证媒体 API
                f"/_matrix/client/v1/media/thumbnail/{server_name}/{media_id}?width=800&height=600",
                # 传统 API
                f"/_matrix/media/v3/thumbnail/{server_name}/{media_id}?width=800&height=600",
                f"/_matrix/media/r0/thumbnail/{server_name}/{media_id}?width=800&height=600",
            ]
            
            for endpoint in thumbnail_endpoints:
                url = f"{self.homeserver}{endpoint}"
                headers = {}
                if self.access_token:
                    headers["Authorization"] = f"Bearer {self.access_token}"
                
                try:
                    async with self.session.get(url, headers=headers, allow_redirects=True) as response:
                        if response.status == 200:
                            logger.info("✅ Downloaded thumbnail instead of full media")
                            return await response.read()
                except Exception:
                    continue

        # If all attempts failed, raise the last error
        error_msg = f"Matrix media download error: {last_error} (last status: {last_status}) for {mxc_url}"
        logger.error(error_msg)
        raise Exception(error_msg)

    async def join_room(self, room_id: str) -> Dict[str, Any]:
        """
        Join a room

        Args:
            room_id: Room ID or alias

        Returns:
            Join response with room_id
        """
        endpoint = f"/_matrix/client/v3/join/{room_id}"
        return await self._request("POST", endpoint, data={})

    async def leave_room(self, room_id: str) -> Dict[str, Any]:
        """
        Leave a room

        Args:
            room_id: Room ID

        Returns:
            Leave response
        """
        endpoint = f"/_matrix/client/v3/rooms/{room_id}/leave"
        return await self._request("POST", endpoint, data={})

    async def get_room_state(self, room_id: str) -> List[Dict[str, Any]]:
        """
        Get room state events

        Args:
            room_id: Room ID

        Returns:
            List of state events
        """
        endpoint = f"/_matrix/client/v3/rooms/{room_id}/state"
        return await self._request("GET", endpoint)

    async def get_room_members(self, room_id: str) -> Dict[str, Any]:
        """
        Get room members

        Args:
            room_id: Room ID

        Returns:
            Room members data
        """
        endpoint = f"/_matrix/client/v3/rooms/{room_id}/members"
        return await self._request("GET", endpoint)

    async def set_display_name(self, display_name: str) -> Dict[str, Any]:
        """
        Set user display name

        Args:
            display_name: New display name

        Returns:
            Response data
        """
        endpoint = f"/_matrix/client/v3/profile/{self.user_id}/displayname"
        return await self._request("PUT", endpoint, data={"displayname": display_name})

    async def get_display_name(self, user_id: str) -> str:
        """
        Get user display name

        Args:
            user_id: Matrix user ID

        Returns:
            Display name
        """
        endpoint = f"/_matrix/client/v3/profile/{user_id}/displayname"
        response = await self._request("GET", endpoint, authenticated=False)
        return response.get("displayname", user_id)

    async def get_joined_rooms(self) -> List[str]:
        """
        Get list of joined room IDs

        Returns:
            List of room IDs
        """
        response = await self._request("GET", "/_matrix/client/v3/joined_rooms")
        return response.get("joined_rooms", [])

    async def edit_message(
        self,
        room_id: str,
        original_event_id: str,
        new_content: Dict[str, Any],
        msg_type: str = "m.text",
    ) -> Dict[str, Any]:
        """
        Edit an existing message

        Args:
            room_id: Room ID
            original_event_id: Event ID of the original message
            new_content: New message content (should include 'body')
            msg_type: Message type (default: m.text)

        Returns:
            Send response with event_id
        """
        import time

        txn_id = f"{int(time.time() * 1000)}_{id(new_content)}"
        endpoint = f"/_matrix/client/v3/rooms/{room_id}/send/m.room.message/{txn_id}"

        # Construct edit content according to Matrix spec
        content = {
            "msgtype": msg_type,
            "body": f"* {new_content.get('body', '')}",  # Fallback for clients that don't support edits
            "m.new_content": {
                "msgtype": msg_type,
                "body": new_content.get("body", ""),
                **{
                    k: v for k, v in new_content.items() if k not in ["body", "msgtype"]
                },
            },
            "m.relates_to": {"rel_type": "m.replace", "event_id": original_event_id},
        }

        return await self._request("PUT", endpoint, data=content)

    async def upload_keys(
        self,
        device_keys: Dict[str, Any],
        one_time_keys: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Upload device and one-time keys to the server

        Args:
            device_keys: Device identity keys
            one_time_keys: One-time keys (optional)

        Returns:
            Upload response with one_time_key_counts
        """
        endpoint = "/_matrix/client/v3/keys/upload"

        data = {"device_keys": device_keys}

        if one_time_keys:
            data["one_time_keys"] = one_time_keys

        return await self._request("POST", endpoint, data=data)

    async def query_keys(
        self, device_keys: Dict[str, List[str]], timeout: int = 10000
    ) -> Dict[str, Any]:
        """
        Query keys for other devices

        Args:
            device_keys: Dict of user_id -> list of device_ids
            timeout: Query timeout in milliseconds

        Returns:
            Device keys information
        """
        endpoint = "/_matrix/client/v3/keys/query"

        data = {"device_keys": device_keys, "timeout": timeout}

        return await self._request("POST", endpoint, data=data)

    async def claim_keys(
        self, one_time_keys: Dict[str, Dict[str, str]]
    ) -> Dict[str, Any]:
        """
        Claim one-time keys for establishing Olm sessions

        Args:
            one_time_keys: Dict of user_id -> device_id -> key_algorithm

        Returns:
            Claimed one-time keys
        """
        endpoint = "/_matrix/client/v3/keys/claim"

        data = {"one_time_keys": one_time_keys}

        return await self._request("POST", endpoint, data=data)

    async def get_devices(self) -> Dict[str, Any]:
        """
        Get the list of devices for the current user

        Returns:
            List of devices with their information
        """
        endpoint = "/_matrix/client/v3/devices"

        return await self._request("GET", endpoint)

    async def get_device(self, device_id: str) -> Dict[str, Any]:
        """
        Get information about a specific device

        Args:
            device_id: The device ID to query

        Returns:
            Device information
        """
        endpoint = f"/_matrix/client/v3/devices/{device_id}"

        return await self._request("GET", endpoint)

    async def update_device(
        self, device_id: str, display_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Update device information

        Args:
            device_id: The device ID to update
            display_name: New display name for the device

        Returns:
            Empty dict on success
        """
        endpoint = f"/_matrix/client/v3/devices/{device_id}"

        data = {}
        if display_name is not None:
            data["display_name"] = display_name

        return await self._request("PUT", endpoint, data=data)

    async def delete_device(
        self, device_id: str, auth: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Delete a device

        Args:
            device_id: The device ID to delete
            auth: Authentication data (if required)

        Returns:
            Empty dict on success or auth flow information
        """
        endpoint = f"/_matrix/client/v3/devices/{device_id}"

        data = {}
        if auth:
            data["auth"] = auth

        return await self._request("DELETE", endpoint, data=data)

    async def send_to_device(
        self, event_type: str, messages: Dict[str, Dict[str, Any]], txn_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send to-device events to specific devices

        Args:
            event_type: The type of event to send
            messages: Dict of user_id -> device_id -> content
            txn_id: Transaction ID (auto-generated if not provided)

        Returns:
            Empty dict on success
        """
        import secrets

        if txn_id is None:
            txn_id = secrets.token_hex(16)

        endpoint = f"/_matrix/client/v3/sendToDevice/{event_type}/{txn_id}"
        data = {"messages": messages}

        # Control verbose logging via environment variable to avoid accidental secret leaks
        verbose_env = os.environ.get("ASTRBOT_VERBOSE_TO_DEVICE", "").lower()
        verbose = verbose_env in ("1", "true", "yes")

        # Helper to produce a short, safe representation of potentially large dicts
        def _short(obj: Any, maxlen: int = 400) -> str:
            try:
                s = json.dumps(obj, ensure_ascii=False)
            except Exception:
                s = str(obj)
            if len(s) > maxlen:
                return s[: maxlen - 80] + f"... (truncated, {len(s)} bytes)"
            return s

        # Build request manually so we can capture HTTP status and raw response body
        await self._ensure_session()
        url = f"{self.homeserver}{endpoint}"
        headers = self._get_headers()

        try:
            async with self.session.put(url, json=data, headers=headers) as resp:
                status = resp.status
                # Try to parse JSON, fallback to text
                try:
                    resp_body = await resp.json()
                except Exception:
                    resp_text = await resp.text()
                    resp_body = resp_text

                # Log summary for diagnostics
                try:
                    from astrbot.api import logger as api_logger

                    api_logger.debug(
                        f"send_to_device response for {event_type} txn {txn_id}: status={status} body={_short(resp_body)}"
                    )

                    if verbose:
                        api_logger.debug(f"send_to_device request payload: {_short(data, maxlen=2000)}")
                        api_logger.debug(f"send_to_device full response: {_short(resp_body, maxlen=2000)}")
                except Exception:
                    pass

                if status >= 400:
                    # Try to extract errcode/message if JSON
                    if isinstance(resp_body, dict):
                        error_code = resp_body.get("errcode", "UNKNOWN")
                        error_msg = resp_body.get("error", "Unknown error")
                    else:
                        error_code = "UNKNOWN"
                        error_msg = str(resp_body)

                    raise Exception(
                        f"Matrix API error: {error_code} - {error_msg} (status: {status})"
                    )

                return resp_body

        except aiohttp.ClientError as e:
            logger.error(f"send_to_device network error for {event_type} txn {txn_id}: {e}")
            raise
