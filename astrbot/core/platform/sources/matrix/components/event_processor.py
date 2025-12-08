"""
Matrix Event Processor
Handles processing of Matrix events (messages, encryption, etc.)
"""

import json
from typing import Optional, Callable, Dict, Any, Set
from astrbot.api import logger


class MatrixEventProcessor:
    """
    Processes Matrix events and handles encryption/decryption
    """

    def __init__(
        self,
        client,
        user_id: str,
        startup_ts: int,
        e2ee_manager=None,
    ):
        """
        Initialize event processor

        Args:
            client: Matrix HTTP client
            user_id: Bot's user ID
            startup_ts: Startup timestamp (milliseconds) for filtering historical messages
            e2ee_manager: E2EE manager instance (optional)
        """
        self.client = client
        self.user_id = user_id
        self.startup_ts = startup_ts
        self.e2ee_manager = e2ee_manager

        # Message deduplication
        self._processed_messages: Set[str] = set()
        self._max_processed_messages = 1000

        # Event callbacks
        self.on_message: Optional[Callable] = None

    def set_message_callback(self, callback: Callable):
        """
        Set callback for processed messages

        Args:
            callback: Async function(room, event) -> None
        """
        self.on_message = callback

    async def process_room_events(self, room_id: str, room_data: dict):
        """
        Process events from a room

        Args:
            room_id: Room ID
            room_data: Room data from sync response
        """
        from ..client.event_types import MatrixRoom

        timeline = room_data.get("timeline", {})
        events = timeline.get("events", [])

        # Build simplified room object
        room = MatrixRoom(room_id=room_id)

        # Process state events to get room information
        state_events = room_data.get("state", {}).get("events", [])
        for event in state_events:
            if event.get("type") == "m.room.member":
                user_id = event.get("state_key")
                content = event.get("content", {})
                if content.get("membership") == "join":
                    display_name = content.get("displayname", user_id)
                    room.members[user_id] = display_name
                    room.member_count += 1

        # Process timeline events
        for event_data in events:
            await self._handle_event(room, event_data)

    async def _handle_event(self, room, event_data: dict):
        """
        Handle a single event

        Args:
            room: Room object
            event_data: Event data
        """
        from ..client.event_types import parse_event

        event_type = event_data.get("type")

        if event_type == "m.room.message":
            # Parse plaintext message event
            event = parse_event(event_data, room.room_id)
            await self._process_message_event(room, event)

        elif event_type == "m.room.encrypted":
            # Ignore encrypted messages - E2EE is disabled
            logger.debug(f"Ignoring encrypted message in room {room.room_id} (E2EE disabled)")
            return

    async def _process_message_event(self, room, event):
        """
        Process a message event (after decryption if needed)

        Args:
            room: Room object
            event: Parsed event object
        """
        try:
            # Ignore messages from self
            if event.sender == self.user_id:
                logger.debug(f"Ignoring message from self: {event.event_id}")
                return

            # Filter historical messages: ignore events before startup
            evt_ts = getattr(event, "origin_server_ts", None)
            if evt_ts is None:
                evt_ts = getattr(event, "server_timestamp", None)
            if evt_ts is not None and evt_ts < (self.startup_ts - 1000):  # Allow 1s drift
                logger.debug(
                    f"Ignoring historical message before startup: "
                    f"id={getattr(event, 'event_id', '<unknown>')} "
                    f"ts={evt_ts} startup={self.startup_ts}"
                )
                return

            # Message deduplication: check if already processed
            if event.event_id in self._processed_messages:
                logger.debug(f"Ignoring duplicate message: {event.event_id}")
                return

            # Record processed message ID
            self._processed_messages.add(event.event_id)

            # Limit cache size to prevent memory leak
            if len(self._processed_messages) > self._max_processed_messages:
                # Remove oldest half of message IDs (simple FIFO strategy)
                old_messages = list(self._processed_messages)[
                    : self._max_processed_messages // 2
                ]
                for msg_id in old_messages:
                    self._processed_messages.discard(msg_id)

            # Call message callback
            if self.on_message:
                await self.on_message(room, event)

        except Exception as e:
            logger.error(f"Error processing message event: {e}")

    async def _decrypt_room_event(self, event_data: dict, room) -> Optional[dict]:
        """
        Decrypt an encrypted room event - DISABLED

        Args:
            event_data: Encrypted event data
            room: Room object

        Returns:
            Always returns None (E2EE is disabled)
        """
        logger.debug("Decryption is disabled - ignoring encrypted event")
        return None

    async def process_to_device_events(self, events: list):
        """
        Process to-device events (ignoring all E2EE-related events)

        Args:
            events: List of to-device events
        """
        for event in events:
            event_type = event.get("type")
            sender = event.get("sender")

            # Ignore all E2EE-related events
            if event_type in [
                "m.room.encrypted",  # Encrypted messages
                "m.key.verification.request",  # Verification requests
                "m.key.verification.ready",
                "m.key.verification.start",
                "m.key.verification.accept",
                "m.key.verification.key",
                "m.key.verification.mac",
                "m.key.verification.done",
                "m.key.verification.cancel",
                "m.room_key",  # Room keys
                "m.forwarded_room_key",  # Forwarded room keys
            ]:
                logger.debug(f"Ignoring E2EE event: {event_type} from {sender}")
                continue

            # Log other event types
            logger.debug(f"Received to-device event: {event_type} from {sender}")

    def clear_processed_messages(self):
        """Clear the processed messages cache"""
        self._processed_messages.clear()

    def get_processed_message_count(self) -> int:
        """Get the number of processed messages in cache"""
        return len(self._processed_messages)

