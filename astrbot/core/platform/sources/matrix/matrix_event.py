from __future__ import annotations

import asyncio
from typing import Optional

from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.message_components import Plain

from .matrix_client import MatrixClient


class MatrixPlatformEvent(AstrMessageEvent):
    def __init__(
        self,
        message_str: str,
        message_obj,
        platform_meta,
        session_id: str,
        client: MatrixClient,
        room_id: str,
        event_id: Optional[str] = None,
    ):
        super().__init__(message_str, message_obj, platform_meta, session_id)
        self.client = client
        self.room_id = room_id
        self.event_id = event_id

    async def send(self, message: MessageChain):
        reply_to: Optional[str] = None
        for comp in message.chain:
            if comp.type == "reply":
                # best-effort reply support
                reply_to = getattr(comp, "id", None) or self.event_id
            elif isinstance(comp, Plain):
                await self.client.send_text(
                    self.room_id, comp.text, reply_to_event_id=reply_to
                )
                # only set reply_to for the first chunk
                reply_to = None
            else:
                # Other message types (image/file/audio) can be supported later
                pass
        await super().send(message)

    async def send_streaming(self, generator, use_fallback: bool = False):
        # Simplified streaming: aggregate plain texts and send in throttled edits is not
        # supported for Matrix in this initial version. We'll send chunks as separate messages.
        async for chain in generator:
            if isinstance(chain, MessageChain):
                buffer = ""
                for comp in chain.chain:
                    if isinstance(comp, Plain):
                        buffer += comp.text
                if buffer:
                    await self.client.send_text(
                        self.room_id, buffer, reply_to_event_id=self.event_id
                    )
                await asyncio.sleep(0)
        return await super().send_streaming(generator, use_fallback)
