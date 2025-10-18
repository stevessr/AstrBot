import asyncio
import sys
import uuid
from pathlib import Path

from nio import (
    AsyncClient,
    MatrixRoom,
    RoomMessageText,
    RoomMessageImage,
    RoomMessageAudio,
    RoomMessageVideo,
    RoomMessageFile,
    SyncResponse,
    LoginResponse,
    RoomSendResponse,
    DownloadResponse,
)

import astrbot.api.message_components as Comp
from astrbot.api import logger
from astrbot.api.event import MessageChain
from astrbot.api.platform import (
    AstrBotMessage,
    MessageMember,
    MessageType,
    Platform,
    PlatformMetadata,
    register_platform_adapter,
)
from astrbot.core.platform.astr_message_event import MessageSesion
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .matrix_event import MatrixPlatformEvent

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override


@register_platform_adapter("matrix", "Matrix 适配器 (支持 E2EE)")
class MatrixPlatformAdapter(Platform):
    def __init__(
        self, platform_config: dict, platform_settings: dict, event_queue: asyncio.Queue
    ) -> None:
        super().__init__(event_queue)
        self.config = platform_config
        self.settings = platform_settings
        self.client_self_id = uuid.uuid4().hex[:8]

        # Matrix configuration
        self.homeserver = self.config.get("matrix_homeserver", "https://matrix.org")
        self.user_id = self.config.get("matrix_user_id", "")
        self.password = self.config.get("matrix_password", "")
        self.device_name = self.config.get("matrix_device_name", "AstrBot")
        self.device_id = self.config.get("matrix_device_id", None)
        self.access_token = self.config.get("matrix_access_token", None)
        
        # Store directory for E2EE keys
        store_path = Path(get_astrbot_data_path()) / "matrix_store"
        store_path.mkdir(parents=True, exist_ok=True)
        
        # Create client with E2EE support
        self.client = AsyncClient(
            self.homeserver,
            self.user_id,
            store_path=str(store_path),
            config=None,
        )
        
        if self.device_id:
            self.client.device_id = self.device_id
        
        self.running = False

    @override
    async def send_by_session(
        self, session: MessageSesion, message_chain: MessageChain
    ):
        room_id = session.session_id
        await MatrixPlatformEvent.send_with_client(
            self.client, message_chain, room_id
        )
        await super().send_by_session(session, message_chain)

    @override
    def meta(self) -> PlatformMetadata:
        return PlatformMetadata(
            name="matrix", 
            description="Matrix 适配器 (支持 E2EE)", 
            id=self.config.get("id")
        )

    async def _login(self):
        """Login to the Matrix homeserver"""
        if self.access_token:
            # Use existing access token
            self.client.access_token = self.access_token
            self.client.user_id = self.user_id
            logger.info(f"Using provided access token for Matrix user: {self.user_id}")
        else:
            # Login with password
            response = await self.client.login(
                password=self.password,
                device_name=self.device_name,
            )
            
            if isinstance(response, LoginResponse):
                logger.info(f"Matrix login successful: {self.user_id}")
                logger.info(f"Device ID: {response.device_id}")
                logger.info(f"Access Token: {response.access_token[:20]}...")
                
                # Save device_id and access_token for future use
                self.device_id = response.device_id
                self.access_token = response.access_token
            else:
                logger.error(f"Matrix login failed: {response}")
                raise Exception(f"Matrix login failed: {response}")

    async def _sync_callback(self, response: SyncResponse):
        """Handle sync responses from the Matrix server"""
        # Process room messages
        for room_id, room_info in response.rooms.join.items():
            for event in room_info.timeline.events:
                # Only handle message events
                if isinstance(event, (RoomMessageText, RoomMessageImage, 
                                     RoomMessageAudio, RoomMessageVideo, 
                                     RoomMessageFile)):
                    # Ignore messages from the bot itself
                    if event.sender == self.client.user_id:
                        continue
                    
                    # Convert to AstrBotMessage and handle
                    abm = await self._convert_matrix_event(event, room_id)
                    if abm:
                        await self._handle_msg(abm)

    async def _convert_matrix_event(self, event, room_id: str) -> AstrBotMessage:
        """Convert a Matrix event to an AstrBotMessage"""
        room: MatrixRoom = self.client.rooms.get(room_id)
        if not room:
            return None
        
        message = AstrBotMessage()
        message.session_id = room_id
        message.message_id = event.event_id
        
        # Determine if it's a direct message or group
        if len(room.users) == 2:
            message.type = MessageType.FRIEND_MESSAGE
        else:
            message.type = MessageType.GROUP_MESSAGE
            message.group_id = room_id
        
        # Get sender information
        sender_name = room.user_name(event.sender) or event.sender
        message.sender = MessageMember(event.sender, sender_name)
        message.self_id = self.client.user_id
        message.raw_message = event
        message.message = []
        message.message_str = ""
        
        # Handle different message types
        if isinstance(event, RoomMessageText):
            # Text message
            message.message_str = event.body
            message.message.append(Comp.Plain(event.body))
            
        elif isinstance(event, RoomMessageImage):
            # Image message
            try:
                # Download the image
                response = await self.client.download(
                    server_name=event.server_name,
                    media_id=event.media_id,
                )
                
                if isinstance(response, DownloadResponse):
                    # Save to temporary file
                    temp_dir = Path(get_astrbot_data_path()) / "temp"
                    temp_dir.mkdir(parents=True, exist_ok=True)
                    
                    file_path = temp_dir / f"{event.event_id}_{event.body}"
                    file_path.write_bytes(response.body)
                    
                    message.message.append(Comp.Image(file=str(file_path)))
                    if event.body:
                        message.message_str = event.body
                        message.message.append(Comp.Plain(event.body))
                else:
                    logger.warning(f"Failed to download image: {response}")
            except Exception as e:
                logger.error(f"Error downloading image: {e}")
                
        elif isinstance(event, RoomMessageAudio):
            # Audio/voice message
            try:
                response = await self.client.download(
                    server_name=event.server_name,
                    media_id=event.media_id,
                )
                
                if isinstance(response, DownloadResponse):
                    temp_dir = Path(get_astrbot_data_path()) / "temp"
                    temp_dir.mkdir(parents=True, exist_ok=True)
                    
                    file_path = temp_dir / f"{event.event_id}_{event.body}"
                    file_path.write_bytes(response.body)
                    
                    message.message.append(Comp.Record(file=str(file_path)))
                else:
                    logger.warning(f"Failed to download audio: {response}")
            except Exception as e:
                logger.error(f"Error downloading audio: {e}")
                
        elif isinstance(event, RoomMessageVideo):
            # Video message
            message.message_str = f"[视频] {event.body}"
            message.message.append(Comp.Plain(message.message_str))
            
        elif isinstance(event, RoomMessageFile):
            # File message
            message.message_str = f"[文件] {event.body}"
            message.message.append(Comp.Plain(message.message_str))
        
        return message

    async def _handle_msg(self, message: AstrBotMessage):
        """Handle a converted message"""
        message_event = MatrixPlatformEvent(
            message_str=message.message_str,
            message_obj=message,
            platform_meta=self.meta(),
            session_id=message.session_id,
            client=self.client,
        )
        self.commit_event(message_event)

    @override
    async def run(self):
        """Start the Matrix client"""
        try:
            # Login
            await self._login()
            
            # Enable encryption support if available
            if self.client.store:
                logger.info("Matrix E2EE support enabled")
            else:
                logger.warning("Matrix E2EE support not available")
            
            # Start syncing
            self.running = True
            logger.info("Matrix Platform Adapter is running.")
            
            # Sync loop
            while self.running:
                try:
                    response = await self.client.sync(timeout=30000)
                    if isinstance(response, SyncResponse):
                        await self._sync_callback(response)
                    else:
                        logger.error(f"Sync error: {response}")
                        await asyncio.sleep(5)
                except asyncio.CancelledError:
                    logger.info("Matrix sync cancelled")
                    break
                except Exception as e:
                    logger.error(f"Error in Matrix sync loop: {e}")
                    await asyncio.sleep(5)
                    
        except Exception as e:
            logger.error(f"Error starting Matrix adapter: {e}")
            raise

    def get_client(self) -> AsyncClient:
        return self.client

    async def terminate(self):
        """Shutdown the Matrix client"""
        try:
            self.running = False
            await self.client.close()
            logger.info("Matrix 适配器已被优雅地关闭")
        except Exception as e:
            logger.error(f"Matrix 适配器关闭时出错: {e}")
