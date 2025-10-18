import asyncio
import sys
import traceback
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
    RoomEncryptedMedia,
    RoomEncryptedImage,
    RoomEncryptedAudio,
    RoomEncryptedVideo,
    RoomEncryptedFile,
    SyncResponse,
    SyncError,
    LoginResponse,
    DownloadResponse,
    KeysUploadResponse,
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
        store_base = Path(get_astrbot_data_path()) / "matrix_store"
        store_base.mkdir(parents=True, exist_ok=True)
        store_path = store_base / (self.config.get("id") or "default")
        store_path.mkdir(parents=True, exist_ok=True)
        self.store_path = store_path

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
        await MatrixPlatformEvent.send_with_client(self.client, message_chain, room_id)
        await super().send_by_session(session, message_chain)

    @override
    def meta(self) -> PlatformMetadata:
        return PlatformMetadata(
            name="matrix",
            description="Matrix 适配器 (支持 E2EE)",
            id=self.config.get("id"),
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

        # Upload encryption keys if E2EE is enabled
        if self.client.store:
            try:
                keys_response = await self.client.keys_upload()
                if isinstance(keys_response, KeysUploadResponse):
                    logger.info(
                        f"Uploaded {keys_response.one_time_key_counts} encryption keys"
                    )
                else:
                    logger.warning(f"Failed to upload keys: {keys_response}")
            except Exception as e:
                logger.warning(f"Failed to upload encryption keys: {e}")

    async def _sync_callback(self, response: SyncResponse):
        """Handle sync responses from the Matrix server"""
        # Handle room invites
        for room_id, room_info in response.rooms.invite.items():
            logger.info(f"Received invitation to room {room_id}")
            try:
                # Auto-join invited rooms
                await self.client.join(room_id)
                logger.info(f"Joined room {room_id}")
            except Exception as e:
                logger.error(f"Failed to join room {room_id}: {e}")

        # Process room messages
        for room_id, room_info in response.rooms.join.items():
            for event in room_info.timeline.events:
                # Handle both regular and encrypted message events
                if isinstance(
                    event,
                    (
                        RoomMessageText,
                        RoomMessageImage,
                        RoomMessageAudio,
                        RoomMessageVideo,
                        RoomMessageFile,
                        RoomEncryptedImage,
                        RoomEncryptedAudio,
                        RoomEncryptedVideo,
                        RoomEncryptedFile,
                        RoomEncryptedMedia,
                    ),
                ):
                    # Ignore messages from the bot itself
                    if event.sender == self.client.user_id:
                        continue

                    # Convert to AstrBotMessage and handle
                    abm = await self._convert_matrix_event(event, room_id)
                    if abm:
                        await self._handle_msg(abm)

    async def _reset_sync_state(self):
        """Reset sync-related state to recover from errors"""
        logger.warning("Resetting Matrix sync state due to sync error")
        if hasattr(self.client, "next_batch"):
            self.client.next_batch = None
        if hasattr(self.client, "sync_token"):
            self.client.sync_token = None
        if self.client.store:
            try:
                self.client.store.next_batch = None
            except AttributeError:
                pass

    async def _handle_sync_error(self, error: SyncError):
        """Handle sync errors, attempting recovery when possible"""
        message = getattr(error, "message", str(error))
        status_code = getattr(error, "status_code", None)
        logger.error(f"Matrix sync error: {message}")
        if status_code:
            logger.error(f"Matrix sync status code: {status_code}")

        needs_reset = False
        if message and "next_batch" in message:
            needs_reset = True
        if status_code in {400, 401}:
            needs_reset = True

        if needs_reset:
            await self._reset_sync_state()

        if status_code == 401:
            logger.warning("Matrix sync unauthorized. Reauthenticating...")
            await self._login()

        transport = getattr(error, "transport_response", None)
        if transport is not None:
            try:
                logger.debug(f"Matrix sync transport response: {transport.body}")
            except AttributeError:
                try:
                    logger.debug(f"Matrix sync transport response: {transport.text}")
                except AttributeError:
                    logger.debug("Matrix sync transport response unavailable")

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

        elif isinstance(event, (RoomMessageImage, RoomEncryptedImage)):
            # Image message (regular or encrypted)
            try:
                # For encrypted images, we need to decrypt the attachment
                if isinstance(event, RoomEncryptedImage):
                    # Download encrypted data from the url (mxc://)
                    url_parts = event.url.replace("mxc://", "").split("/")
                    if len(url_parts) == 2:
                        server_name, media_id = url_parts
                        response = await self.client.download(
                            server_name=server_name,
                            media_id=media_id,
                        )

                        if isinstance(response, DownloadResponse):
                            # Decrypt the attachment
                            try:
                                from nio.crypto import decrypt_attachment

                                decrypted_data = decrypt_attachment(
                                    response.body,
                                    event.key["k"],
                                    event.hashes["sha256"],
                                    event.iv,
                                )
                                # Save decrypted data
                                temp_dir = Path(get_astrbot_data_path()) / "temp"
                                temp_dir.mkdir(parents=True, exist_ok=True)

                                file_path = temp_dir / f"{event.event_id}_{event.body}"
                                file_path.write_bytes(decrypted_data)

                                message.message.append(Comp.Image(file=str(file_path)))
                                if event.body:
                                    message.message_str = event.body
                                    message.message.append(Comp.Plain(event.body))
                            except Exception as decrypt_error:
                                logger.error(
                                    f"Failed to decrypt image: {decrypt_error}"
                                )
                                message.message_str = f"[加密图片解密失败] {event.body}"
                                message.message.append(Comp.Plain(message.message_str))
                        else:
                            logger.warning(
                                f"Failed to download encrypted image: {response}"
                            )
                    else:
                        logger.error(f"Invalid MXC URL: {event.url}")
                else:
                    # Regular unencrypted image
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

        elif isinstance(event, (RoomMessageAudio, RoomEncryptedAudio)):
            # Audio/voice message (regular or encrypted)
            try:
                if isinstance(event, RoomEncryptedAudio):
                    url_parts = event.url.replace("mxc://", "").split("/")
                    if len(url_parts) == 2:
                        server_name, media_id = url_parts
                        response = await self.client.download(
                            server_name=server_name,
                            media_id=media_id,
                        )

                        if isinstance(response, DownloadResponse):
                            try:
                                from nio.crypto import decrypt_attachment

                                decrypted_data = decrypt_attachment(
                                    response.body,
                                    event.key["k"],
                                    event.hashes["sha256"],
                                    event.iv,
                                )
                                temp_dir = Path(get_astrbot_data_path()) / "temp"
                                temp_dir.mkdir(parents=True, exist_ok=True)

                                file_path = temp_dir / f"{event.event_id}_{event.body}"
                                file_path.write_bytes(decrypted_data)

                                message.message.append(Comp.Record(file=str(file_path)))
                            except Exception as decrypt_error:
                                logger.error(
                                    f"Failed to decrypt audio: {decrypt_error}"
                                )
                                message.message_str = f"[加密语音解密失败] {event.body}"
                                message.message.append(Comp.Plain(message.message_str))
                        else:
                            logger.warning(
                                f"Failed to download encrypted audio: {response}"
                            )
                    else:
                        logger.error(f"Invalid MXC URL: {event.url}")
                else:
                    # Regular unencrypted audio
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

        elif isinstance(event, (RoomMessageVideo, RoomEncryptedVideo)):
            # Video message
            message.message_str = f"[视频] {event.body}"
            message.message.append(Comp.Plain(message.message_str))

        elif isinstance(event, (RoomMessageFile, RoomEncryptedFile)):
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
            # Login first
            await self._login()

            # Log E2EE status
            if self.client.store:
                logger.info(f"Matrix E2EE support enabled (store: {self.store_path})")
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
                    elif isinstance(response, SyncError):
                        await self._handle_sync_error(response)
                        await asyncio.sleep(5)
                    else:
                        logger.error(f"Unexpected sync response type: {type(response)}")
                        await asyncio.sleep(5)
                except asyncio.CancelledError:
                    logger.info("Matrix sync cancelled")
                    break
                except Exception as e:
                    logger.error(f"Error in Matrix sync loop: {e}")
                    logger.error(traceback.format_exc())
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
