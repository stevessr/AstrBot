import time
import uuid
from typing import Any, Dict, Optional

import aiohttp


class MatrixClient:
    """Minimal Matrix Client-Server API wrapper for AstrBot adapters.

    This client only implements the subset needed by the adapter:
    - whoami
    - sync (long-poll)
    - send text messages
    """

    def __init__(
        self,
        homeserver: str,
        access_token: str,
        user_id: Optional[str] = None,
        session: Optional[aiohttp.ClientSession] = None,
        timeout: int = 30000,
    ) -> None:
        self.homeserver = homeserver.rstrip("/")
        self.access_token = access_token
        self.user_id = user_id
        self.timeout = timeout
        self._session = session or aiohttp.ClientSession(
            headers={"Authorization": f"Bearer {access_token}"}
        )

    @property
    def session(self) -> aiohttp.ClientSession:
        return self._session

    async def close(self):
        if not self._session.closed:
            await self._session.close()

    async def whoami(self) -> Dict[str, Any]:
        url = f"{self.homeserver}/_matrix/client/v3/account/whoami"
        async with self._session.get(url) as resp:
            resp.raise_for_status()
            data = await resp.json()
            self.user_id = data.get("user_id", self.user_id)
            return data

    async def sync(
        self,
        since: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        url = f"{self.homeserver}/_matrix/client/v3/sync"
        params = {
            "timeout": str(timeout or self.timeout),
        }
        if since:
            params["since"] = since
        async with self._session.get(url, params=params) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def send_text(
        self,
        room_id: str,
        text: str,
        reply_to_event_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send a plain text message into a room."""
        txn_id = f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
        url = (
            f"{self.homeserver}/_matrix/client/v3/rooms/"
            f"{room_id}/send/m.room.message/{txn_id}"
        )
        content: Dict[str, Any] = {
            "msgtype": "m.text",
            "body": text,
        }
        # Reply relation if provided (MSC2674)
        if reply_to_event_id:
            content["m.relates_to"] = {"m.in_reply_to": {"event_id": reply_to_event_id}}
        async with self._session.put(url, json=content) as resp:
            resp.raise_for_status()
            return await resp.json()
