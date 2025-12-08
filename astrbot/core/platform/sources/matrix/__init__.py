"""
Matrix protocol adapter for AstrBot.

Note: E2EE (end-to-end encryption) support has been removed from this
adapter. The previous implementation used vodozemac for Olm/Megolm but was
intentionally removed. The Matrix adapter continues to support non-encrypted
rooms and media types.
"""

from .matrix_adapter import MatrixPlatformAdapter
from .matrix_event import MatrixPlatformEvent

__all__ = [
    "MatrixPlatformAdapter",
    "MatrixPlatformEvent",
]
