import asyncio
import os
import sys
import uuid
import base64

from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.platform import AstrBotMessage, PlatformMetadata
from astrbot.api.message_components import (
    Plain,
    Image,
    File,
    Reply,
)
from astrbot import logger
from astrbot.core.utils.io import download_file
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

try:
    from nio import AsyncClient, RoomSendResponse, UploadResponse
except ImportError:
    logger.error("matrix-nio is not installed. Please install it with: pip install matrix-nio[e2e]")
    raise


class MatrixMessageEvent(AstrMessageEvent):
    """Matrix platform message event handler"""

    def __init__(
        self,
        message_str: str,
        message_obj: AstrBotMessage,
        platform_meta: PlatformMetadata,
        session_id: str,
        client: AsyncClient,
        room_id: str,
    ):
        super().__init__(message_str, message_obj, platform_meta, session_id)
        self.client = client
        self.room_id = room_id

    @override
    async def send(self, message: MessageChain):
        """Send message to Matrix room"""
        try:
            for component in message.chain:
                if isinstance(component, Plain):
                    await self._send_text(component.text)
                elif isinstance(component, Image):
                    await self._send_image(component)
                elif isinstance(component, File):
                    await self._send_file(component)
                elif isinstance(component, Reply):
                    # Matrix replies are handled differently - we'll prepend the reply info to the next text message
                    continue
                else:
                    logger.warning(f"Matrix adapter: Unsupported message component type: {component.type}")

                # Small delay to avoid flooding
                await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"Failed to send Matrix message: {e}", exc_info=True)

    async def _send_text(self, text: str):
        """Send text message to Matrix room"""
        if not text.strip():
            return

        try:
            response = await self.client.room_send(
                room_id=self.room_id,
                message_type="m.room.message",
                content={
                    "msgtype": "m.text",
                    "body": text,
                    "format": "org.matrix.custom.html",
                    "formatted_body": text.replace("\n", "<br/>")
                }
            )

            if not isinstance(response, RoomSendResponse):
                logger.error(f"Failed to send Matrix text message: {response}")

        except Exception as e:
            logger.error(f"Error sending Matrix text message: {e}", exc_info=True)

    async def _send_image(self, image: Image):
        """Send image to Matrix room"""
        try:
            # Get image file path
            if image.file and image.file.startswith("file:///"):
                file_path = image.file.replace("file:///", "")
            elif image.file and image.file.startswith("http"):
                # Download image from URL
                temp_dir = os.path.join(get_astrbot_data_path(), "temp")
                os.makedirs(temp_dir, exist_ok=True)
                file_path = await download_file(image.file, temp_dir)
            elif image.file and image.file.startswith("base64://"):
                # Handle base64 images
                base64_str = image.file.removeprefix("base64://")
                image_data = base64.b64decode(base64_str)
                temp_dir = os.path.join(get_astrbot_data_path(), "temp")
                os.makedirs(temp_dir, exist_ok=True)
                file_path = os.path.join(temp_dir, f"matrix_image_{uuid.uuid4()}.png")
                with open(file_path, "wb") as f:
                    f.write(image_data)
            else:
                file_path = image.file

            if not file_path or not os.path.exists(file_path):
                logger.error(f"Matrix image file not found: {file_path}")
                return

            # Upload image to Matrix
            with open(file_path, "rb") as f:
                file_data = f.read()

            file_stats = os.stat(file_path)
            filename = os.path.basename(file_path)

            # Upload the file
            upload_response = await self.client.upload(
                data_provider=file_data,
                content_type="image/png",  # Matrix supports auto-detection
                filename=filename
            )

            if not isinstance(upload_response, UploadResponse):
                logger.error(f"Failed to upload Matrix image: {upload_response}")
                return

            # Send image message
            content = {
                "msgtype": "m.image",
                "body": filename,
                "url": upload_response.content_uri,
                "info": {
                    "size": file_stats.st_size,
                    "mimetype": "image/png",  # Could be more specific
                }
            }

            response = await self.client.room_send(
                room_id=self.room_id,
                message_type="m.room.message",
                content=content
            )

            if not isinstance(response, RoomSendResponse):
                logger.error(f"Failed to send Matrix image message: {response}")

        except Exception as e:
            logger.error(f"Error sending Matrix image: {e}", exc_info=True)

    async def _send_file(self, file: File):
        """Send file to Matrix room"""
        try:
            file_path = file.url if file.url else file.name

            if not file_path or not os.path.exists(file_path):
                logger.error(f"Matrix file not found: {file_path}")
                return

            # Upload file to Matrix
            with open(file_path, "rb") as f:
                file_data = f.read()

            file_stats = os.stat(file_path)
            filename = file.name or os.path.basename(file_path)

            # Upload the file
            upload_response = await self.client.upload(
                data_provider=file_data,
                content_type="application/octet-stream",  # Generic content type
                filename=filename
            )

            if not isinstance(upload_response, UploadResponse):
                logger.error(f"Failed to upload Matrix file: {upload_response}")
                return

            # Send file message
            content = {
                "msgtype": "m.file",
                "body": filename,
                "url": upload_response.content_uri,
                "info": {
                    "size": file_stats.st_size,
                }
            }

            response = await self.client.room_send(
                room_id=self.room_id,
                message_type="m.room.message",
                content=content
            )

            if not isinstance(response, RoomSendResponse):
                logger.error(f"Failed to send Matrix file message: {response}")

        except Exception as e:
            logger.error(f"Error sending Matrix file: {e}", exc_info=True)

    @override
    async def send_streaming(self, generator, use_fallback: bool = False):
        """Send streaming messages (Matrix doesn't support streaming, so we buffer)"""
        buffer = ""

        async for message_chain in generator:
            for component in message_chain.chain:
                if isinstance(component, Plain):
                    buffer += component.text

                    # Send when buffer gets large enough or contains sentence breaks
                    if len(buffer) > 1000 or any(punct in buffer for punct in [".", "!", "?", "\n\n"]):
                        await self._send_text(buffer.strip())
                        buffer = ""
                        await asyncio.sleep(1.0)  # Rate limiting

        # Send remaining buffer
        if buffer.strip():
            await self._send_text(buffer.strip())

        await super().send_streaming(generator, use_fallback)
