import asyncio
import sys
import time
from typing import Any, Optional

from astrbot.api.platform import (
    Platform,
    AstrBotMessage,
    MessageMember,
    PlatformMetadata,
    MessageType,
    register_platform_adapter,
)
from astrbot.api.event import MessageChain
from astrbot.api.message_components import Plain
from astrbot.core.platform.astr_message_event import MessageSesion
from astrbot import logger

from .matrix_event import MatrixMessageEvent

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

try:
    from nio import (
        AsyncClient,
        LoginResponse,
        SyncResponse,
        RoomMessageText,
        RoomMessageImage,
        RoomMessageFile,
        InviteEvent,
        MatrixRoom,
    )
    from nio.events.room_events import RoomMessage
except ImportError:
    logger.error("matrix-nio is not installed. Please install it with: pip install matrix-nio[e2e]")
    raise


@register_platform_adapter(
    "matrix",
    "Matrix 协议适配器 (基于 matrix-nio)",
    default_config_tmpl={
        "type": "matrix",
        "enable": False,
        "id": "matrix",
        "matrix_homeserver": "https://matrix.org",
        "matrix_user_id": "@your_bot:matrix.org",
        "matrix_password": "your_password",
        "matrix_access_token": "",  # Alternative to password
        "matrix_device_name": "AstrBot",
        "matrix_auto_join_rooms": True,
        "matrix_sync_timeout": 30000,
    }
)
class MatrixAdapter(Platform):
    """Matrix platform adapter for AstrBot"""

    def __init__(
        self, platform_config: dict, platform_settings: dict, event_queue: asyncio.Queue
    ) -> None:
        super().__init__(event_queue)
        self.config = platform_config
        self.settings = platform_settings
        self.client: Optional[AsyncClient] = None
        self.client_self_id = None
        self.shutdown_event = asyncio.Event()
        self._sync_task: Optional[asyncio.Task] = None

        # Configuration
        self.homeserver = self.config.get("matrix_homeserver", "https://matrix.org")
        self.user_id = self.config.get("matrix_user_id", "")
        self.password = self.config.get("matrix_password", "")
        self.access_token = self.config.get("matrix_access_token", "")
        self.device_name = self.config.get("matrix_device_name", "AstrBot")
        self.auto_join_rooms = self.config.get("matrix_auto_join_rooms", True)
        self.sync_timeout = self.config.get("matrix_sync_timeout", 30000)

        if not self.user_id:
            raise ValueError("matrix_user_id is required for Matrix adapter")
        if not self.password and not self.access_token:
            raise ValueError("Either matrix_password or matrix_access_token is required for Matrix adapter")

        self.metadata = PlatformMetadata(
            name="matrix",
            description="Matrix 协议适配器 (基于 matrix-nio)",
            id=self.config.get("id", "matrix"),
        )

    @override
    def meta(self) -> PlatformMetadata:
        return self.metadata

    @override
    async def run(self) -> Any:
        """Main run loop for Matrix adapter"""
        try:
            # Initialize Matrix client
            self.client = AsyncClient(self.homeserver, self.user_id)

            # Login to Matrix
            if self.access_token:
                # Use existing access token
                self.client.access_token = self.access_token
                self.client.user_id = self.user_id
                logger.info(f"[Matrix] Using existing access token for {self.user_id}")
            else:
                # Login with password
                logger.info(f"[Matrix] Logging in to {self.homeserver} as {self.user_id}")
                response = await self.client.login(self.password, device_name=self.device_name)

                if not isinstance(response, LoginResponse):
                    logger.error(f"[Matrix] Failed to login: {response}")
                    return

                logger.info(f"[Matrix] Successfully logged in. Device ID: {response.device_id}")

            # Set up event handlers
            self.client.add_event_callback(self._handle_message, RoomMessageText)
            self.client.add_event_callback(self._handle_message, RoomMessageImage)
            self.client.add_event_callback(self._handle_message, RoomMessageFile)

            if self.auto_join_rooms:
                self.client.add_event_callback(self._handle_invite, InviteEvent)

            # Store client self ID
            self.client_self_id = self.client.user_id

            # Start sync loop
            logger.info("[Matrix] Starting sync loop...")
            self._sync_task = asyncio.create_task(self._sync_loop())

            # Wait for shutdown
            await self.shutdown_event.wait()

        except Exception as e:
            logger.error(f"[Matrix] Error in run(): {e}", exc_info=True)
        finally:
            await self._cleanup()

    async def _sync_loop(self):
        """Main sync loop to receive Matrix events"""
        try:
            # Do initial sync
            logger.info("[Matrix] Performing initial sync...")
            sync_response = await self.client.sync(timeout=0)  # Full sync first

            if not isinstance(sync_response, SyncResponse):
                logger.error(f"[Matrix] Initial sync failed: {sync_response}")
                return

            logger.info(f"[Matrix] Initial sync completed. Next batch: {sync_response.next_batch}")

            # Continuous sync
            while not self.shutdown_event.is_set():
                try:
                    sync_response = await self.client.sync(timeout=self.sync_timeout)

                    if not isinstance(sync_response, SyncResponse):
                        logger.error(f"[Matrix] Sync failed: {sync_response}")
                        await asyncio.sleep(5)
                        continue

                except asyncio.TimeoutError:
                    # Normal timeout, continue syncing
                    continue
                except Exception as e:
                    logger.error(f"[Matrix] Sync error: {e}", exc_info=True)
                    await asyncio.sleep(5)
                    continue

        except Exception as e:
            logger.error(f"[Matrix] Error in sync loop: {e}", exc_info=True)

    async def _handle_message(self, room: MatrixRoom, event: RoomMessage):
        """Handle incoming Matrix messages"""
        try:
            # Skip messages from the bot itself
            if event.sender == self.client.user_id:
                return

            # Skip messages that are too old (more than 5 minutes)
            if time.time() - (event.server_timestamp / 1000) > 300:
                return

            logger.debug(f"[Matrix] Received message in {room.room_id} from {event.sender}: {event.body}")

            # Convert Matrix event to AstrBot message
            abm = await self._convert_matrix_event_to_astrbot_message(room, event)

            if abm:
                # Create Matrix message event
                session_id = room.room_id  # Use room ID as session ID for group chats

                matrix_event = MatrixMessageEvent(
                    message_str=abm.message_str,
                    message_obj=abm,
                    platform_meta=self.meta(),
                    session_id=session_id,
                    client=self.client,
                    room_id=room.room_id,
                )

                # Submit to event queue
                self.commit_event(matrix_event)

        except Exception as e:
            logger.error(f"[Matrix] Error handling message: {e}", exc_info=True)

    async def _handle_invite(self, room: MatrixRoom, event: InviteEvent):
        """Handle Matrix room invitations"""
        try:
            logger.info(f"[Matrix] Received invite to room {room.room_id} from {event.sender}")

            if self.auto_join_rooms:
                logger.info(f"[Matrix] Auto-joining room {room.room_id}")
                response = await self.client.join(room.room_id)

                if hasattr(response, "transport_response") and response.transport_response.ok:
                    logger.info(f"[Matrix] Successfully joined room {room.room_id}")
                else:
                    logger.error(f"[Matrix] Failed to join room {room.room_id}: {response}")

        except Exception as e:
            logger.error(f"[Matrix] Error handling invite: {e}", exc_info=True)

    async def _convert_matrix_event_to_astrbot_message(
        self, room: MatrixRoom, event: RoomMessage
    ) -> Optional[AstrBotMessage]:
        """Convert Matrix event to AstrBot message format"""
        try:
            # Create message components
            message_components = []
            message_str = ""

            if isinstance(event, RoomMessageText):
                message_components.append(Plain(event.body))
                message_str = event.body

            elif isinstance(event, RoomMessageImage):
                message_components.append(Plain(f"[图片: {event.body}]"))
                # TODO: Download and convert matrix:// URLs to local files
                message_str = f"[图片: {event.body}]"

            elif isinstance(event, RoomMessageFile):
                message_components.append(Plain(f"[文件: {event.body}]"))
                message_str = f"[文件: {event.body}]"

            # Determine message type (room vs direct)
            if room.member_count > 2:
                message_type = MessageType.GROUP_MESSAGE
                group_id = room.room_id
            else:
                message_type = MessageType.FRIEND_MESSAGE
                group_id = ""

            # Get sender information
            sender_name = room.user_name(event.sender) or event.sender

            # Create sender object
            sender = MessageMember(
                user_id=event.sender,
                nickname=sender_name,
            )

            # Create AstrBot message
            abm = AstrBotMessage()
            abm.type = message_type
            abm.self_id = self.client.user_id
            abm.session_id = room.room_id
            abm.message_id = event.event_id
            abm.sender = sender
            abm.message = message_components
            abm.message_str = message_str
            abm.raw_message = event
            abm.group_id = group_id
            abm.timestamp = int(event.server_timestamp / 1000)

            return abm

        except Exception as e:
            logger.error(f"[Matrix] Error converting event to AstrBot message: {e}", exc_info=True)
            return None

    @override
    async def send_by_session(
        self, session: MessageSesion, message_chain: MessageChain
    ):
        """Send message by session (room ID)"""
        try:
            if not self.client:
                logger.error("[Matrix] Client not initialized")
                return

            room_id = session.session_id

            # Create a temporary event for sending
            matrix_event = MatrixMessageEvent(
                message_str="",
                message_obj=None,
                platform_meta=self.meta(),
                session_id=room_id,
                client=self.client,
                room_id=room_id,
            )

            await matrix_event.send(message_chain)
            await super().send_by_session(session, message_chain)

        except Exception as e:
            logger.error(f"[Matrix] Error sending message by session: {e}", exc_info=True)

    @override
    async def terminate(self):
        """Terminate the Matrix adapter"""
        logger.info("[Matrix] Terminating adapter...")
        self.shutdown_event.set()

        if self._sync_task and not self._sync_task.done():
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass

        await self._cleanup()

    async def _cleanup(self):
        """Clean up Matrix client resources"""
        if self.client:
            try:
                await self.client.close()
                logger.info("[Matrix] Client closed successfully")
            except Exception as e:
                logger.error(f"[Matrix] Error closing client: {e}", exc_info=True)

    def get_client(self) -> Optional[AsyncClient]:
        """Get the Matrix client instance"""
        return self.client
