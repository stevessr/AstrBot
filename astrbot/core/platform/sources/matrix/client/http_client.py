"""
Matrix HTTP Client - Direct implementation without matrix-nio
Implements the Matrix Client-Server API using aiohttp
"""

import aiohttp
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
        url = f"{self.homeserver}/_matrix/media/v3/download/{server_name}/{media_id}"

        headers = {
            "Authorization": f"Bearer {self.access_token}",
        }

        async with self.session.get(url, headers=headers) as response:
            if response.status >= 400:
                raise Exception(f"Matrix media download error: {response.status}")

            return await response.read()

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
