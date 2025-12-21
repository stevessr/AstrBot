"""
Matrix Event Processor
Handles processing of Matrix events (messages, etc.)
"""

from collections.abc import Callable
from typing import Any

from astrbot.api import logger


class MatrixEventProcessor:
    """
    Processes Matrix events
    """

    def __init__(
        self,
        client,
        user_id: str,
        startup_ts: int,
    ):
        """
        Initialize event processor

        Args:
            client: Matrix HTTP client
            user_id: Bot's user ID
            startup_ts: Startup timestamp (milliseconds) for filtering historical messages
        """
        self.client = client
        self.user_id = user_id
        self.startup_ts = startup_ts

        # Message deduplication
        self._processed_messages: set[str] = set()
        self._max_processed_messages = 1000

        # Event callbacks
        self.on_message: Callable | None = None

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
        # Update import: Client event types in ..client.event_types
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

        if event_type == "m.room.message" or event_type == "m.room.encrypted":
            # Parse plaintext message event or encrypted event
            event = parse_event(event_data, room.room_id)
            await self._process_message_event(room, event)

    async def _process_message_event(self, room, event):
        """
        Process a message event

        Args:
            room: Room object
            event: Parsed event object
        """
        try:
            # Ignore messages from self
            if event.sender == self.user_id:
                logger.debug(f"忽略来自自身的消息: {event.event_id}")
                return

            # Check if message is encrypted
            event_type = event.event_type
            event_content = event.content

            if event_type == "m.room.encrypted" or event_content.get("algorithm"):
                # This is an encrypted message
                logger.error(
                    f"收到加密消息 (room_id={room.room_id}, event_id={event.event_id})。无法解密。"
                )
                return

            # Filter historical messages: ignore events before startup
            evt_ts = getattr(event, "origin_server_ts", None)
            if evt_ts is None:
                evt_ts = getattr(event, "server_timestamp", None)
            if evt_ts is not None and evt_ts < (
                self.startup_ts - 1000
            ):  # Allow 1s drift
                logger.debug(
                    f"忽略启动前的历史消息: "
                    f"id={getattr(event, 'event_id', '<unknown>')} "
                    f"ts={evt_ts} startup={self.startup_ts}"
                )
                return

            # Message deduplication: check if already processed
            if event.event_id in self._processed_messages:
                logger.debug(f"忽略重复消息: {event.event_id}")
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

                # Send read receipt after successful processing
                try:
                    await self.client.send_read_receipt(room.room_id, event.event_id)
                    logger.debug(f"已发送事件 {event.event_id} 的已读回执")
                except Exception as e:
                    logger.debug(f"发送已读回执失败: {e}")

        except Exception as e:
            logger.error(f"处理消息事件时出错: {e}")

    async def process_to_device_events(self, events: list):
        """
        Process to-device events

        Args:
            events: List of to-device events
        """
        for event in events:
            event_type = event.get("type")
            sender = event.get("sender")

            if event_type in [
                "m.room.encrypted",
                "m.key.verification.request",
                "m.key.verification.ready",
                "m.key.verification.start",
                "m.key.verification.accept",
                "m.key.verification.key",
                "m.key.verification.mac",
                "m.key.verification.done",
                "m.key.verification.cancel",
                "m.room_key",
                "m.forwarded_room_key",
            ]:
                logger.debug(f"忽略 E2EE 事件: {event_type} 来自 {sender}")
                continue

            # Log other event types
            logger.debug(f"收到设备间事件: {event_type} 来自 {sender}")

    def clear_processed_messages(self):
        """Clear the processed messages cache"""
        self._processed_messages.clear()

    def get_processed_message_count(self) -> int:
        """Get the number of processed messages in cache"""
        return len(self._processed_messages)
