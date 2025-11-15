"""
Matrix Sync Manager
Handles the sync loop and event distribution
"""

import asyncio
from typing import Optional, Callable
from astrbot.api import logger


class MatrixSyncManager:
    """
    Manages the Matrix sync loop and event processing
    """

    def __init__(
        self,
        client,
        sync_timeout: int = 30000,
        auto_join_rooms: bool = True,
    ):
        """
        Initialize sync manager

        Args:
            client: Matrix HTTP client
            sync_timeout: Sync timeout in milliseconds
            auto_join_rooms: Whether to auto-join invited rooms
        """
        self.client = client
        self.sync_timeout = sync_timeout
        self.auto_join_rooms = auto_join_rooms

        # Event callbacks
        self.on_room_event: Optional[Callable] = None
        self.on_to_device_event: Optional[Callable] = None
        self.on_invite: Optional[Callable] = None

        # Sync state
        self._next_batch: Optional[str] = None
        self._first_sync = True
        self._running = False

    def set_room_event_callback(self, callback: Callable):
        """
        Set callback for room events

        Args:
            callback: Async function(room_id, room_data) -> None
        """
        self.on_room_event = callback

    def set_to_device_event_callback(self, callback: Callable):
        """
        Set callback for to-device events

        Args:
            callback: Async function(events) -> None
        """
        self.on_to_device_event = callback

    def set_invite_callback(self, callback: Callable):
        """
        Set callback for room invites

        Args:
            callback: Async function(room_id, invite_data) -> None
        """
        self.on_invite = callback

    async def sync_forever(self):
        """
        Run the sync loop forever
        Continuously syncs with the Matrix server and processes events
        """
        self._running = True
        logger.info("Starting Matrix sync loop")

        while self._running:
            try:
                # Execute sync
                sync_response = await self.client.sync(
                    since=self._next_batch,
                    timeout=self.sync_timeout,
                    full_state=self._first_sync,
                )

                self._next_batch = sync_response.get("next_batch")
                self._first_sync = False

                # Process to-device messages (E2EE verification, etc.)
                to_device_events = sync_response.get("to_device", {}).get("events", [])
                if to_device_events and self.on_to_device_event:
                    await self.on_to_device_event(to_device_events)

                # Process rooms events
                rooms = sync_response.get("rooms", {})

                # Process joined rooms
                for room_id, room_data in rooms.get("join", {}).items():
                    if self.on_room_event:
                        await self.on_room_event(room_id, room_data)

                # Process invited rooms
                if self.auto_join_rooms:
                    for room_id, invite_data in rooms.get("invite", {}).items():
                        if self.on_invite:
                            await self.on_invite(room_id, invite_data)

            except KeyboardInterrupt:
                logger.info("Sync loop interrupted by user")
                raise
            except Exception as e:
                logger.error(f"Error in sync loop: {e}")
                # Wait a bit before retrying
                await asyncio.sleep(5)

    def stop(self):
        """Stop the sync loop"""
        self._running = False
        logger.info("Stopping Matrix sync loop")

    def is_running(self) -> bool:
        """Check if sync loop is running"""
        return self._running

    def get_next_batch(self) -> Optional[str]:
        """Get the current sync batch token"""
        return self._next_batch

    def set_next_batch(self, batch: str):
        """Set the sync batch token (for resuming sync)"""
        self._next_batch = batch
        self._first_sync = False
