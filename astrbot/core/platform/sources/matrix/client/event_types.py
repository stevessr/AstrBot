"""
Matrix Event Types - Replacement for matrix-nio event types
"""

from typing import Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class MatrixEvent:
    """Base class for Matrix events"""

    event_id: str
    sender: str
    origin_server_ts: int
    room_id: str
    content: Dict[str, Any]
    event_type: str
    unsigned: Optional[Dict[str, Any]] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any], room_id: str):
        """Create event from dictionary"""
        return cls(
            event_id=data.get("event_id", ""),
            sender=data.get("sender", ""),
            origin_server_ts=data.get("origin_server_ts", 0),
            room_id=room_id,
            content=data.get("content", {}),
            event_type=data.get("type", ""),
            unsigned=data.get("unsigned"),
        )


@dataclass
class RoomMessageEvent(MatrixEvent):
    """Room message event (m.room.message)"""

    msgtype: str = ""
    body: str = ""
    url: Optional[str] = None
    info: Optional[Dict[str, Any]] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any], room_id: str):
        """Create room message event from dictionary"""
        content = data.get("content", {})
        return cls(
            event_id=data.get("event_id", ""),
            sender=data.get("sender", ""),
            origin_server_ts=data.get("origin_server_ts", 0),
            room_id=room_id,
            content=content,
            event_type=data.get("type", ""),
            unsigned=data.get("unsigned"),
            msgtype=content.get("msgtype", ""),
            body=content.get("body", ""),
            url=content.get("url"),
            info=content.get("info"),
        )


@dataclass
class RoomMessageText(RoomMessageEvent):
    """Text message event"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any], room_id: str):
        event = super().from_dict(data, room_id)
        event.msgtype = "m.text"
        return event


@dataclass
class RoomMessageImage(RoomMessageEvent):
    """Image message event"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any], room_id: str):
        event = super().from_dict(data, room_id)
        event.msgtype = "m.image"
        return event


@dataclass
class RoomMessageFile(RoomMessageEvent):
    """File message event"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any], room_id: str):
        event = super().from_dict(data, room_id)
        event.msgtype = "m.file"
        return event


@dataclass
class InviteEvent(MatrixEvent):
    """Room invite event"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any], room_id: str):
        """Create invite event from dictionary"""
        return cls(
            event_id=data.get("event_id", ""),
            sender=data.get("sender", ""),
            origin_server_ts=data.get("origin_server_ts", 0),
            room_id=room_id,
            content=data.get("content", {}),
            event_type="m.room.member",
            unsigned=data.get("unsigned"),
        )


@dataclass
class MatrixRoom:
    """Represents a Matrix room"""

    room_id: str
    display_name: str = ""
    topic: str = ""
    member_count: int = 0
    encrypted: bool = False
    members: Dict[str, str] = None  # user_id -> display_name

    def __post_init__(self):
        if self.members is None:
            self.members = {}

    def user_name(self, user_id: str) -> str:
        """Get display name for a user"""
        return self.members.get(user_id, user_id)

    @property
    def is_group(self) -> bool:
        """Check if room is a group (more than 2 members)"""
        return self.member_count > 2


def parse_event(event_data: Dict[str, Any], room_id: str) -> MatrixEvent:
    """
    Parse event data into appropriate event type

    Args:
        event_data: Raw event data from Matrix
        room_id: Room ID the event belongs to

    Returns:
        Parsed event object
    """
    event_type = event_data.get("type", "")
    content = event_data.get("content", {})

    if event_type == "m.room.message":
        msgtype = content.get("msgtype", "")
        if msgtype == "m.text":
            return RoomMessageText.from_dict(event_data, room_id)
        elif msgtype == "m.image":
            return RoomMessageImage.from_dict(event_data, room_id)
        elif msgtype == "m.file":
            return RoomMessageFile.from_dict(event_data, room_id)
        else:
            return RoomMessageEvent.from_dict(event_data, room_id)
    elif event_type == "m.room.member" and content.get("membership") == "invite":
        return InviteEvent.from_dict(event_data, room_id)
    else:
        return MatrixEvent.from_dict(event_data, room_id)
