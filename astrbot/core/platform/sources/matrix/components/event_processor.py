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
            # Handle encrypted message
            if self.e2ee_manager and self.e2ee_manager.is_enabled():
                logger.debug(f"Received encrypted message in room {room.room_id}")
                # Try to decrypt message
                decrypted_event = await self._decrypt_room_event(event_data, room)
                if decrypted_event:
                    # Successfully decrypted, process plaintext message
                    event = parse_event(decrypted_event, room.room_id)
                    await self._process_message_event(room, event)
                else:
                    logger.warning(
                        f"Failed to decrypt message in room {room.room_id}, "
                        f"sender: {event_data.get('sender')}"
                    )
            else:
                logger.warning(
                    f"Received encrypted message but E2EE is not enabled in room {room.room_id}"
                )

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
        Decrypt an encrypted room event

        Args:
            event_data: Encrypted event data
            room: Room object

        Returns:
            Decrypted event data, or None if decryption fails
        """
        try:
            content = event_data.get("content", {})
            sender = event_data.get("sender")

            # Extract encryption information
            algorithm = content.get("algorithm")
            sender_key = content.get("sender_key")
            ciphertext = content.get("ciphertext")
            session_id = content.get("session_id")
            device_id = content.get("device_id")

            logger.debug(
                f"Decrypting: algorithm={algorithm}, sender={sender}, device={device_id}"
            )

            # Call E2EE manager to decrypt
            if algorithm == "m.megolm.v1.aes-sha2":
                # Megolm group encryption (used in encrypted rooms)
                plaintext = await self.e2ee_manager.decrypt_megolm_event(
                    room.room_id, sender, sender_key, session_id, ciphertext
                )
            elif algorithm == "m.olm.v1.curve25519-aes-sha2":
                # Olm 1-to-1 encryption
                plaintext = await self.e2ee_manager.decrypt_olm_event(
                    sender, device_id, ciphertext
                )
            else:
                logger.warning(f"Unsupported encryption algorithm: {algorithm}")
                return None

            if plaintext:
                # Build decrypted event
                decrypted_content = json.loads(plaintext)
                decrypted_event = event_data.copy()
                decrypted_event["type"] = decrypted_content.get("type", "m.room.message")
                decrypted_event["content"] = decrypted_content.get("content", {})
                return decrypted_event

            return None

        except Exception as e:
            logger.error(f"Error decrypting room event: {e}")
            return None

    async def process_to_device_events(self, events: list):
        """
        Process to-device events (E2EE verification, encrypted messages, etc.)

        Args:
            events: List of to-device events
        """
        for event in events:
            event_type = event.get("type")
            content = event.get("content", {})
            sender = event.get("sender")

            # Log all to-device events (for debugging)
            logger.info(f"📨 Received to-device event: {event_type} from {sender}")
            logger.debug(f"Event content: {content}")

            # Handle encrypted to-device messages (Olm)
            if event_type == "m.room.encrypted":
                if self.e2ee_manager:
                    # Decrypt the message
                    decrypted_event = await self.e2ee_manager.handle_encrypted_to_device(sender, content)
                    if decrypted_event:
                        # Process the decrypted event
                        decrypted_type = decrypted_event.get("type")
                        decrypted_content = decrypted_event.get("content", {})

                        # Handle decrypted event based on its type
                        if decrypted_type == "m.room_key":
                            await self.e2ee_manager.handle_room_key(sender, decrypted_content)
                        elif decrypted_type == "m.forwarded_room_key":
                            await self.e2ee_manager.handle_room_key(sender, decrypted_content)
                        else:
                            logger.info(f"Decrypted to-device event type: {decrypted_type}")
                else:
                    logger.warning("Received encrypted to-device message but E2EE is not enabled")
                continue

            # Handle E2EE verification events
            if event_type in [
                "m.key.verification.ready",
                "m.key.verification.start",
                "m.key.verification.accept",
                "m.key.verification.key",
                "m.key.verification.mac",
                "m.key.verification.done",
                "m.key.verification.cancel",
            ]:
                if self.e2ee_manager:
                    await self.e2ee_manager.handle_verification_event(event)
                else:
                    logger.warning(f"Received {event_type} but E2EE is not enabled")
                continue

            # Handle unencrypted room key events (less common, usually encrypted)
            if event_type == "m.room_key":
                if self.e2ee_manager:
                    await self.e2ee_manager.handle_room_key(sender, content)
                else:
                    logger.warning("Received m.room_key but E2EE is not enabled")
                continue

            if event_type == "m.forwarded_room_key":
                if self.e2ee_manager:
                    await self.e2ee_manager.handle_room_key(sender, content)
                else:
                    logger.warning("Received m.forwarded_room_key but E2EE is not enabled")
                continue

            # Log other event types
            if event_type not in ["m.room.encrypted"]:
                # Log unhandled event types
                logger.warning(f"⚠️ Unhandled to-device event type: {event_type}")

    def clear_processed_messages(self):
        """Clear the processed messages cache"""
        self._processed_messages.clear()

    def get_processed_message_count(self) -> int:
        """Get the number of processed messages in cache"""
        return len(self._processed_messages)

