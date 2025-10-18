import os
from pathlib import Path

from nio import AsyncClient, RoomSendResponse
from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.platform import AstrBotMessage, PlatformMetadata, MessageType
from astrbot.api.message_components import (
    Plain,
    Image,
    Reply,
    At,
    File,
    Record,
)
from astrbot import logger
from astrbot.core.utils.astrbot_path import get_astrbot_data_path


class MatrixPlatformEvent(AstrMessageEvent):
    def __init__(
        self,
        message_str: str,
        message_obj: AstrBotMessage,
        platform_meta: PlatformMetadata,
        session_id: str,
        client: AsyncClient,
    ):
        super().__init__(message_str, message_obj, platform_meta, session_id)
        self.client = client

    @classmethod
    async def send_with_client(cls, client: AsyncClient, message: MessageChain, room_id: str):
        """Send a message to a Matrix room"""
        for i in message.chain:
            if isinstance(i, Plain):
                # Send text message
                response = await client.room_send(
                    room_id=room_id,
                    message_type="m.room.message",
                    content={
                        "msgtype": "m.text",
                        "body": i.text,
                    },
                )
                if not isinstance(response, RoomSendResponse):
                    logger.error(f"Failed to send message: {response}")
                    
            elif isinstance(i, Image):
                # Send image
                try:
                    image_path = await i.convert_to_file_path()
                    
                    # Read image file
                    with open(image_path, "rb") as f:
                        file_data = f.read()
                    
                    # Determine mimetype
                    mimetype = "image/jpeg"
                    if image_path.lower().endswith(".png"):
                        mimetype = "image/png"
                    elif image_path.lower().endswith(".gif"):
                        mimetype = "image/gif"
                    elif image_path.lower().endswith(".webp"):
                        mimetype = "image/webp"
                    
                    # Upload to Matrix server
                    upload_response = await client.upload(
                        data_provider=lambda: file_data,
                        content_type=mimetype,
                        filename=os.path.basename(image_path),
                    )
                    
                    if hasattr(upload_response, 'content_uri'):
                        # Send image message
                        await client.room_send(
                            room_id=room_id,
                            message_type="m.room.message",
                            content={
                                "msgtype": "m.image",
                                "body": os.path.basename(image_path),
                                "url": upload_response.content_uri,
                                "info": {
                                    "mimetype": mimetype,
                                    "size": len(file_data),
                                },
                            },
                        )
                    else:
                        logger.error(f"Failed to upload image: {upload_response}")
                        
                except Exception as e:
                    logger.error(f"Error sending image: {e}")
                    
            elif isinstance(i, File):
                # Send file
                try:
                    file_path = i.file
                    if file_path.startswith("https://"):
                        # TODO: Download remote file
                        logger.warning("Remote file upload not yet implemented")
                        continue
                    
                    with open(file_path, "rb") as f:
                        file_data = f.read()
                    
                    # Upload to Matrix server
                    upload_response = await client.upload(
                        data_provider=lambda: file_data,
                        content_type="application/octet-stream",
                        filename=i.name,
                    )
                    
                    if hasattr(upload_response, 'content_uri'):
                        # Send file message
                        await client.room_send(
                            room_id=room_id,
                            message_type="m.room.message",
                            content={
                                "msgtype": "m.file",
                                "body": i.name,
                                "url": upload_response.content_uri,
                                "info": {
                                    "size": len(file_data),
                                },
                            },
                        )
                    else:
                        logger.error(f"Failed to upload file: {upload_response}")
                        
                except Exception as e:
                    logger.error(f"Error sending file: {e}")
                    
            elif isinstance(i, Record):
                # Send audio/voice message
                try:
                    audio_path = await i.convert_to_file_path()
                    
                    with open(audio_path, "rb") as f:
                        file_data = f.read()
                    
                    # Determine mimetype
                    mimetype = "audio/ogg"
                    if audio_path.lower().endswith(".mp3"):
                        mimetype = "audio/mpeg"
                    elif audio_path.lower().endswith(".wav"):
                        mimetype = "audio/wav"
                    elif audio_path.lower().endswith(".m4a"):
                        mimetype = "audio/mp4"
                    
                    # Upload to Matrix server
                    upload_response = await client.upload(
                        data_provider=lambda: file_data,
                        content_type=mimetype,
                        filename=os.path.basename(audio_path),
                    )
                    
                    if hasattr(upload_response, 'content_uri'):
                        # Send audio message
                        await client.room_send(
                            room_id=room_id,
                            message_type="m.room.message",
                            content={
                                "msgtype": "m.audio",
                                "body": os.path.basename(audio_path),
                                "url": upload_response.content_uri,
                                "info": {
                                    "mimetype": mimetype,
                                    "size": len(file_data),
                                },
                            },
                        )
                    else:
                        logger.error(f"Failed to upload audio: {upload_response}")
                        
                except Exception as e:
                    logger.error(f"Error sending audio: {e}")

    async def send(self, message: MessageChain):
        """Send a message"""
        if self.get_message_type() == MessageType.GROUP_MESSAGE:
            await self.send_with_client(self.client, message, self.message_obj.group_id)
        else:
            await self.send_with_client(self.client, message, self.session_id)
        await super().send(message)
